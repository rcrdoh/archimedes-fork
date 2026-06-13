// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";

import "./interfaces/IVault.sol";
import "./interfaces/IAMMRouter.sol";
import "./PriceOracle.sol";

/// @title Vault
/// @notice ERC-4626 tokenized vault that holds synthetic/bridged assets.
///         Users deposit USDC, receive vault shares. Manager rebalances via AMM.
///         Non-custodial: agent has rebalance authority, NOT withdraw-to-platform authority.
contract Vault is IVault, ERC20, Ownable, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

    // ─── Constants ───────────────────────────────────────────────────

    uint256 public constant BPS = 10000;
    uint256 public constant SECONDS_PER_YEAR = 365 days;
    uint256 public constant PLATFORM_FEE_BPS = 1000; // 10% platform cut

    /// @notice First-depositor share-inflation guard (audit 2026-06-10 finding #4, issue #507).
    ///
    ///         Chosen mitigation: **Option B — dead shares.** On the first deposit a fixed
    ///         MIN_LIQUIDITY of shares is minted to an unrecoverable sink and subtracted from
    ///         the receiver. An attacker can no longer own ~100% of a dust supply and then
    ///         donate USDC to inflate NAV: the sink permanently holds MIN_LIQUIDITY shares,
    ///         so the attacker's share of any donation is at most 1/(MIN_LIQUIDITY+1) — the
    ///         donation is overwhelmingly burned, making the attack strictly unprofitable,
    ///         and later depositors' shares no longer round to zero.
    ///
    ///         Why not Option A (OZ-style virtual decimals offset): a decimals offset of
    ///         d > 0 rescales shares-per-asset by 10**d, which silently breaks this vault's
    ///         performance-fee math — `highWaterMark` is initialized to 1e18 assuming a 1:1
    ///         share:asset scale, so nav-per-share would start at 1e18/10**d and the
    ///         performance fee would never (or wrongly) accrue. Dead shares preserve the
    ///         1:1 scale and leave the fee logic untouched. Cost: the first depositor
    ///         forfeits MIN_LIQUIDITY share-wei (1e3 = 0.001 USDC at 6 decimals) — negligible.
    uint256 public constant MIN_LIQUIDITY = 1e3;

    /// @notice Sink for dead shares (OZ ERC20 forbids minting to address(0)).
    address public constant DEAD_SHARES_SINK = address(0xdEaD);

    /// @notice Hard cap on the owner-configurable slippage tolerance (5%).
    ///         Prevents the owner from effectively disabling swap protection.
    uint256 public constant MAX_SLIPPAGE_CAP_BPS = 500;

    // ─── Immutables ──────────────────────────────────────────────────

    address public immutable override asset;
    IAMMRouter public immutable ammRouter;
    address public immutable override creator;
    uint8 public immutable override tier;
    uint16 public immutable override managementFeeBps;
    uint16 public immutable override performanceFeeBps;
    bool public immutable override isAgentAssisted;

    // ─── State ───────────────────────────────────────────────────────

    address public agent;

    /// @notice Last timestamp when management fee was accrued
    uint256 public lastFeeTimestamp;

    /// @notice High water mark (USDC per share, scaled by 1e18)
    uint256 public override highWaterMark = 1e18;

    /// @notice Total accrued management fees in vault shares
    uint256 public accruedManagementShares;

    /// @notice Platform fee recipient
    address public platformFeeRecipient;

    /// @notice Target allocations: token → weight in basis points
    mapping(address => uint256) public targetWeightBps;
    address[] public targetTokens;

    /// @notice Current holdings: token → amount held by vault
    mapping(address => uint256) public holdings;
    address[] public heldTokens;

    /// @notice Oracle address for each held token (for NAV pricing)
    mapping(address => address) public override tokenOracle;

    /// @notice Max slippage tolerance (in bps) applied to every AMM swap,
    ///         relative to the oracle-implied fair output. Owner-configurable,
    ///         hard-capped at MAX_SLIPPAGE_CAP_BPS. Default 100 bps (1%) —
    ///         covers the 30 bps AMM fee plus bounded price impact.
    uint256 public maxSlippageBps = 100;

    // ─── Errors ──────────────────────────────────────────────────────

    error ZeroAmount();
    error ZeroShares();
    error ZeroAssets();
    error Unauthorized();
    error InvalidAllocations();
    error InsufficientBalance();
    error InsufficientLiquidity();
    error SlippageBpsTooHigh();
    error OracleNotSet();
    error InvalidOraclePrice();

    // ─── Events (Vault-local) ────────────────────────────────────────

    event MaxSlippageBpsSet(uint256 oldBps, uint256 newBps);

    // ─── Constructor ─────────────────────────────────────────────────

    constructor(
        address _usdc,
        address _ammRouter,
        address _creator,
        uint8 _tier,
        uint16 _managementFeeBps,
        uint16 _performanceFeeBps,
        bool _agentAssisted,
        address _platformFeeRecipient,
        string memory _name,
        string memory _symbol
    ) ERC20(_name, _symbol) Ownable(_creator) {
        asset = _usdc;
        ammRouter = IAMMRouter(_ammRouter);
        creator = _creator;
        tier = _tier;
        managementFeeBps = _managementFeeBps;
        performanceFeeBps = _performanceFeeBps;
        isAgentAssisted = _agentAssisted;
        platformFeeRecipient = _platformFeeRecipient;
        lastFeeTimestamp = block.timestamp;
    }

    // ─── Modifiers ───────────────────────────────────────────────────

    modifier onlyManager() {
        if (msg.sender != creator && msg.sender != agent) revert Unauthorized();
        _;
    }

    // ─── ERC-4626: Deposit ───────────────────────────────────────────

    function deposit(uint256 assets, address receiver)
        external
        override
        nonReentrant
        whenNotPaused
        returns (uint256 shares)
    {
        if (assets == 0) revert ZeroAmount();

        _accrueFees();

        shares = previewDeposit(assets);
        if (shares == 0) revert ZeroShares();

        // Inflation-attack guard: lock MIN_LIQUIDITY dead shares on the first deposit.
        // previewDeposit already subtracted MIN_LIQUIDITY from the receiver's shares,
        // so total minted == assets and the 1:1 share:asset scale is preserved.
        if (totalSupply() == 0) {
            _mint(DEAD_SHARES_SINK, MIN_LIQUIDITY);
        }

        // Mint shares to receiver
        _mint(receiver, shares);

        // Transfer USDC from sender to vault
        IERC20(asset).safeTransferFrom(msg.sender, address(this), assets);

        // Track USDC as a holding
        _addHolding(address(asset), assets);

        emit Deposit(msg.sender, receiver, assets, shares);
    }

    // ─── ERC-4626: Withdraw ──────────────────────────────────────────

    function withdraw(uint256 assets, address receiver, address owner_)
        external
        override
        nonReentrant
        whenNotPaused
        returns (uint256 shares)
    {
        if (assets == 0) revert ZeroAmount();

        _accrueFees();

        shares = _convertToShares(assets);
        if (shares == 0) revert ZeroShares();

        // Ensure we have enough USDC — liquidate positions if needed
        uint256 usdcOnHand = IERC20(asset).balanceOf(address(this));
        if (usdcOnHand < assets) {
            _liquidateToUsdc(assets - usdcOnHand);
        }

        // ERC-4626 allowance enforcement (audit 2026-06-13 CRITICAL): a caller may only
        // burn `owner_`'s shares when it IS the owner, or when the owner has granted it a
        // share allowance. Without this, anyone could pass a victim as `owner_` and a
        // chosen `receiver` to drain the victim's deposit. `_spendAllowance` is a no-op
        // for an infinite (type(uint256).max) allowance, matching the canonical pattern.
        if (msg.sender != owner_) {
            _spendAllowance(owner_, msg.sender, shares);
        }
        _burn(owner_, shares);

        IERC20(asset).safeTransfer(receiver, assets);

        emit Withdraw(msg.sender, receiver, owner_, assets, shares);
    }

    // ─── ERC-4626: Redeem ────────────────────────────────────────────

    function redeem(uint256 shares, address receiver, address owner_)
        external
        override
        nonReentrant
        whenNotPaused
        returns (uint256 assets)
    {
        if (shares == 0) revert ZeroShares();

        _accrueFees();

        assets = previewRedeem(shares);
        if (assets == 0) revert ZeroAssets();

        // Ensure we have enough USDC — liquidate positions if needed
        uint256 usdcOnHand = IERC20(asset).balanceOf(address(this));
        if (usdcOnHand < assets) {
            _liquidateToUsdc(assets - usdcOnHand);
        }

        // ERC-4626 allowance enforcement (audit 2026-06-13 CRITICAL): a caller may only
        // burn `owner_`'s shares when it IS the owner, or when the owner has granted it a
        // share allowance. Without this, anyone could pass a victim as `owner_` and a
        // chosen `receiver` to drain the victim's deposit. `_spendAllowance` is a no-op
        // for an infinite (type(uint256).max) allowance, matching the canonical pattern.
        if (msg.sender != owner_) {
            _spendAllowance(owner_, msg.sender, shares);
        }
        _burn(owner_, shares);

        IERC20(asset).safeTransfer(receiver, assets);

        emit Withdraw(msg.sender, receiver, owner_, assets, shares);
    }

    // ─── Views ───────────────────────────────────────────────────────

    /// @notice Total NAV in USDC terms — prices all held tokens via oracles.
    function totalAssets() public view override returns (uint256) {
        uint256 nav = IERC20(asset).balanceOf(address(this));

        for (uint256 i = 0; i < heldTokens.length; i++) {
            if (heldTokens[i] == address(asset)) continue;
            uint256 balance = IERC20(heldTokens[i]).balanceOf(address(this));
            if (balance == 0) continue;

            address oracle = tokenOracle[heldTokens[i]];
            if (oracle == address(0)) continue;

            // synth tokens: 18 decimals, oracle price: 6 decimals (USDC)
            // value in USDC (6 decimals) = balance(18) * price(6) / 1e18
            uint256 price = PriceOracle(oracle).getPrice();
            nav += (balance * price) / 1e18;
        }

        return nav;
    }

    function previewDeposit(uint256 assets) public view override returns (uint256 shares) {
        uint256 _totalSupply = totalSupply();
        uint256 _totalAssets = totalAssets();

        if (_totalSupply == 0) {
            // First deposit: 1:1 rate minus the MIN_LIQUIDITY dead shares locked in
            // deposit() (inflation-attack guard — see MIN_LIQUIDITY doc above).
            // Deposits of <= MIN_LIQUIDITY return 0 and deposit() reverts ZeroShares,
            // so a 1-wei first deposit (the classic attack setup) is impossible.
            shares = assets > MIN_LIQUIDITY ? assets - MIN_LIQUIDITY : 0;
        } else if (_totalAssets == 0) {
            // Degenerate: supply exists but NAV is zero — keep legacy 1:1 fallback.
            shares = assets;
        } else {
            shares = (assets * _totalSupply) / _totalAssets;
        }
    }

    function previewRedeem(uint256 shares) public view override returns (uint256 assets) {
        uint256 _totalSupply = totalSupply();
        if (_totalSupply == 0) return 0;
        assets = (shares * totalAssets()) / _totalSupply;
    }

    // ─── Management ──────────────────────────────────────────────────

    function rebalance(
        address[] calldata tokensIn,
        uint256[] calldata amountsIn,
        address[] calldata tokensOut,
        uint256[] calldata amountsOut
    ) external override onlyManager nonReentrant whenNotPaused {
        _accrueFees();

        // Sell tokens (swap tokenOut -> USDC via AMM)
        for (uint256 i = 0; i < tokensOut.length; i++) {
            address tokenOut = tokensOut[i];
            uint256 amount = amountsOut[i];

            if (tokenOut == address(asset)) {
                // Selling USDC directly — no swap needed, just track
                continue;
            }

            // Approve router
            IERC20(tokenOut).safeIncreaseAllowance(address(ammRouter), amount);

            // Swap tokenOut -> USDC with oracle-derived slippage floor
            uint256 usdcReceived =
                ammRouter.swap(tokenOut, asset, amount, _oracleMinOut(tokenOut, asset, amount));

            _removeHolding(tokenOut, amount);
            _addHolding(address(asset), usdcReceived);
        }

        // Buy tokens (swap USDC -> tokenIn via AMM)
        for (uint256 i = 0; i < tokensIn.length; i++) {
            address tokenIn = tokensIn[i];
            uint256 amount = amountsIn[i];

            if (tokenIn == address(asset)) {
                // Buying USDC directly — no swap needed
                continue;
            }

            // Approve router
            IERC20(asset).safeIncreaseAllowance(address(ammRouter), amount);

            // Swap USDC -> tokenIn with oracle-derived slippage floor
            uint256 tokensReceived =
                ammRouter.swap(asset, tokenIn, amount, _oracleMinOut(asset, tokenIn, amount));

            _removeHolding(asset, amount);
            _addHolding(tokenIn, tokensReceived);
        }

        emit Rebalanced(msg.sender, tokensIn.length + tokensOut.length, block.timestamp);
    }

    function setTargetAllocations(
        address[] calldata tokens,
        uint256[] calldata weightsBps
    ) external override onlyManager {
        if (tokens.length != weightsBps.length) revert InvalidAllocations();

        uint256 totalWeight;
        for (uint256 i = 0; i < weightsBps.length; i++) {
            totalWeight += weightsBps[i];
        }
        if (totalWeight != BPS) revert InvalidAllocations();

        // Clear old allocations
        for (uint256 i = 0; i < targetTokens.length; i++) {
            targetWeightBps[targetTokens[i]] = 0;
        }

        // Set new allocations
        delete targetTokens;
        for (uint256 i = 0; i < tokens.length; i++) {
            targetWeightBps[tokens[i]] = weightsBps[i];
            targetTokens.push(tokens[i]);
        }

        emit TargetAllocationsSet(tokens.length, block.timestamp);
    }

    /// @notice Set oracle addresses for held tokens (needed for NAV pricing).
    ///         Must be called before rebalance so totalAssets() is accurate.
    function setTokenOracles(
        address[] calldata tokens,
        address[] calldata oracles
    ) external override onlyManager {
        if (tokens.length != oracles.length) revert InvalidAllocations();
        for (uint256 i = 0; i < tokens.length; i++) {
            tokenOracle[tokens[i]] = oracles[i];
        }
        emit TokenOraclesSet(tokens.length);
    }

    function getHoldings()
        external
        view
        override
        returns (address[] memory tokens, uint256[] memory amounts)
    {
        tokens = heldTokens;
        amounts = new uint256[](tokens.length);
        for (uint256 i = 0; i < tokens.length; i++) {
            amounts[i] = IERC20(tokens[i]).balanceOf(address(this));
        }
    }

    function getTargetAllocations()
        external
        view
        override
        returns (address[] memory tokens, uint256[] memory weights)
    {
        tokens = targetTokens;
        weights = new uint256[](tokens.length);
        for (uint256 i = 0; i < tokens.length; i++) {
            weights[i] = targetWeightBps[tokens[i]];
        }
    }

    // ─── Admin ───────────────────────────────────────────────────────

    function setAgent(address _agent) external onlyOwner {
        agent = _agent;
    }

    function setPlatformFeeRecipient(address _recipient) external onlyOwner {
        platformFeeRecipient = _recipient;
    }

    /// @notice Set the max slippage tolerance applied to all AMM swaps.
    ///         Bounded by MAX_SLIPPAGE_CAP_BPS so swap protection can never
    ///         be effectively disabled.
    function setMaxSlippageBps(uint256 _maxSlippageBps) external onlyOwner {
        if (_maxSlippageBps > MAX_SLIPPAGE_CAP_BPS) revert SlippageBpsTooHigh();
        emit MaxSlippageBpsSet(maxSlippageBps, _maxSlippageBps);
        maxSlippageBps = _maxSlippageBps;
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    // ─── Internal ────────────────────────────────────────────────────

    /// @notice Compute the minimum acceptable output for an AMM swap from the
    ///         on-chain oracle price, minus the bounded slippage tolerance.
    /// @dev    Exactly one side of every vault swap is USDC (the vault asset);
    ///         the other side is a synth token. Decimal conventions (matching
    ///         totalAssets()): USDC has 6 decimals; synth tokens have 18;
    ///         oracle prices are USDC (6 decimals) per 1e18 synth units.
    ///
    ///         synth -> USDC: expectedOut(6) = amountIn(18) * price(6) / 1e18
    ///         USDC -> synth: expectedOut(18) = amountIn(6) * 1e18 / price(6)
    ///
    ///         Reverts if the non-USDC side has no registered oracle (an
    ///         unpriced swap would be unprotected) or the oracle price is zero.
    ///         PriceOracle.getPrice() itself reverts when the price is stale,
    ///         so stale oracles block swaps rather than mispricing them.
    function _oracleMinOut(address tokenIn, address tokenOut, uint256 amountIn)
        internal
        view
        returns (uint256 minAmountOut)
    {
        address synth = tokenIn == address(asset) ? tokenOut : tokenIn;
        address oracle = tokenOracle[synth];
        if (oracle == address(0)) revert OracleNotSet();

        uint256 price = PriceOracle(oracle).getPrice();
        if (price == 0) revert InvalidOraclePrice();

        uint256 expectedOut = tokenIn == address(asset)
            ? (amountIn * 1e18) / price // buy: USDC(6) -> synth(18)
            : (amountIn * price) / 1e18; // sell: synth(18) -> USDC(6)

        minAmountOut = (expectedOut * (BPS - maxSlippageBps)) / BPS;
    }

    /// @notice Liquidate non-USDC positions to cover a USDC shortfall.
    ///         Sells proportionally from each held token via the AMM.
    function _liquidateToUsdc(uint256 shortfall) internal {
        // First pass: calculate total non-USDC holdings value
        uint256 totalNonUsdcValue;
        for (uint256 i = 0; i < heldTokens.length; i++) {
            if (heldTokens[i] == address(asset)) continue;
            uint256 balance = IERC20(heldTokens[i]).balanceOf(address(this));
            if (balance == 0) continue;
            address oracle = tokenOracle[heldTokens[i]];
            if (oracle == address(0)) continue;

            uint256 price = PriceOracle(oracle).getPrice();
            totalNonUsdcValue += (balance * price) / 1e18;
        }

        if (totalNonUsdcValue == 0) revert InsufficientLiquidity();

        // Add 0.5% buffer for slippage
        uint256 liquidationTarget = shortfall + (shortfall / 200);

        // Second pass: sell proportionally from each non-USDC token
        for (uint256 i = 0; i < heldTokens.length; i++) {
            if (heldTokens[i] == address(asset)) continue;
            uint256 balance = IERC20(heldTokens[i]).balanceOf(address(this));
            if (balance == 0) continue;
            address oracle = tokenOracle[heldTokens[i]];
            if (oracle == address(0)) continue;

            uint256 price = PriceOracle(oracle).getPrice();
            uint256 tokenValue = (balance * price) / 1e18;
            if (tokenValue == 0) continue;

            // This token's proportional share of the liquidation
            uint256 targetValue = (liquidationTarget * tokenValue) / totalNonUsdcValue;
            uint256 tokensToSell = (targetValue * 1e18) / price;
            if (tokensToSell == 0) continue;
            if (tokensToSell > balance) tokensToSell = balance;

            // Approve router and swap to USDC with oracle-derived slippage floor
            IERC20(heldTokens[i]).safeIncreaseAllowance(address(ammRouter), tokensToSell);
            ammRouter.swap(
                heldTokens[i], asset, tokensToSell, _oracleMinOut(heldTokens[i], asset, tokensToSell)
            );
        }

        // Verify we now have enough USDC
        uint256 usdcAfter = IERC20(asset).balanceOf(address(this));
        if (usdcAfter < shortfall) revert InsufficientLiquidity();
    }

    function _accrueFees() internal {
        uint256 timeDelta = block.timestamp - lastFeeTimestamp;
        if (timeDelta == 0) return;

        uint256 _totalAssets = totalAssets();
        uint256 _totalSupply = totalSupply();

        // Management fee: annualized fee proportional to time elapsed
        if (managementFeeBps > 0 && _totalAssets > 0) {
            uint256 mgmtFee = (_totalAssets * managementFeeBps * timeDelta) /
                              (BPS * SECONDS_PER_YEAR);

            // Mint shares to platform as fee
            uint256 feeShares;
            if (_totalSupply == 0) {
                feeShares = mgmtFee;
            } else {
                feeShares = (mgmtFee * _totalSupply) / _totalAssets;
            }

            if (feeShares > 0) {
                // Platform gets 10% of fee
                uint256 platformShares = (feeShares * PLATFORM_FEE_BPS) / BPS;
                uint256 creatorShares = feeShares - platformShares;

                if (platformShares > 0 && platformFeeRecipient != address(0)) {
                    _mint(platformFeeRecipient, platformShares);
                }
                if (creatorShares > 0) {
                    _mint(creator, creatorShares);
                }

                accruedManagementShares += feeShares;
            }
        }

        // Performance fee: check if NAV/share exceeds HWM
        if (performanceFeeBps > 0 && _totalSupply > 0 && _totalAssets > 0) {
            uint256 navPerShare = (_totalAssets * 1e18) / _totalSupply;
            if (navPerShare > highWaterMark) {
                uint256 gain = navPerShare - highWaterMark;
                uint256 perfFeePerShare = (gain * performanceFeeBps) / BPS;
                // Convert to total shares
                uint256 perfShares = (perfFeePerShare * _totalSupply) / 1e18;

                if (perfShares > 0) {
                    uint256 platformShares = (perfShares * PLATFORM_FEE_BPS) / BPS;
                    uint256 creatorShares = perfShares - platformShares;

                    if (platformShares > 0 && platformFeeRecipient != address(0)) {
                        _mint(platformFeeRecipient, platformShares);
                    }
                    if (creatorShares > 0) {
                        _mint(creator, creatorShares);
                    }

                    highWaterMark = navPerShare;
                }
            }
        }

        lastFeeTimestamp = block.timestamp;
    }

    /// @dev Shares to burn for an exact-assets withdraw. Rounds UP (against the
    ///      withdrawer), per ERC-4626 previewWithdraw semantics — audit finding #4
    ///      flagged the old round-down as a depositor-favored rounding leak.
    function _convertToShares(uint256 assets) internal view returns (uint256 shares) {
        uint256 _totalSupply = totalSupply();
        uint256 _totalAssets = totalAssets();
        if (_totalSupply == 0 || _totalAssets == 0) {
            shares = assets;
        } else {
            shares = (assets * _totalSupply + _totalAssets - 1) / _totalAssets;
        }
    }

    function _addHolding(address token, uint256 amount) internal {
        if (holdings[token] == 0) {
            heldTokens.push(token);
        }
        holdings[token] += amount;
    }

    function _removeHolding(address token, uint256 amount) internal {
        if (holdings[token] < amount) {
            // Use actual balance if tracking is off
            holdings[token] = IERC20(token).balanceOf(address(this));
        }
        if (holdings[token] >= amount) {
            holdings[token] -= amount;
        } else {
            holdings[token] = 0;
        }
        if (holdings[token] == 0) {
            _removeFromHeldTokens(token);
        }
    }

    function _removeFromHeldTokens(address token) internal {
        for (uint256 i = 0; i < heldTokens.length; i++) {
            if (heldTokens[i] == token) {
                heldTokens[i] = heldTokens[heldTokens.length - 1];
                heldTokens.pop();
                break;
            }
        }
    }
}
