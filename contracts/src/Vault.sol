// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import "./interfaces/IVault.sol";
import "./interfaces/IAMMRouter.sol";

/// @title Vault
/// @notice ERC-4626 tokenized vault that holds synthetic/bridged assets.
///         Users deposit USDC, receive vault shares. Manager rebalances via AMM.
///         Non-custodial: agent has rebalance authority, NOT withdraw-to-platform authority.
contract Vault is IVault, ERC20, Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ─── Constants ───────────────────────────────────────────────────

    uint256 public constant BPS = 10000;
    uint256 public constant SECONDS_PER_YEAR = 365 days;
    uint256 public constant PLATFORM_FEE_BPS = 1000; // 10% platform cut

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

    // ─── Errors ──────────────────────────────────────────────────────

    error ZeroAmount();
    error ZeroShares();
    error ZeroAssets();
    error Unauthorized();
    error InvalidAllocations();
    error InsufficientBalance();

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
        returns (uint256 shares)
    {
        if (assets == 0) revert ZeroAmount();

        _accrueFees();

        shares = previewDeposit(assets);
        if (shares == 0) revert ZeroShares();

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
        returns (uint256 shares)
    {
        if (assets == 0) revert ZeroAmount();

        _accrueFees();

        shares = _convertToShares(assets);
        if (shares == 0) revert ZeroShares();

        _burn(owner_, shares);

        _removeHolding(address(asset), assets);
        IERC20(asset).safeTransfer(receiver, assets);

        emit Withdraw(msg.sender, receiver, owner_, assets, shares);
    }

    // ─── ERC-4626: Redeem ────────────────────────────────────────────

    function redeem(uint256 shares, address receiver, address owner_)
        external
        override
        nonReentrant
        returns (uint256 assets)
    {
        if (shares == 0) revert ZeroShares();

        _accrueFees();

        assets = previewRedeem(shares);
        if (assets == 0) revert ZeroAssets();

        _burn(owner_, shares);

        _removeHolding(address(asset), assets);
        IERC20(asset).safeTransfer(receiver, assets);

        emit Withdraw(msg.sender, receiver, owner_, assets, shares);
    }

    // ─── Views ───────────────────────────────────────────────────────

    function totalAssets() public view override returns (uint256) {
        return IERC20(asset).balanceOf(address(this));
    }

    function previewDeposit(uint256 assets) public view override returns (uint256 shares) {
        uint256 _totalSupply = totalSupply();
        uint256 _totalAssets = totalAssets();

        if (_totalSupply == 0 || _totalAssets == 0) {
            // 1:1 initial rate
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
    ) external override onlyManager nonReentrant {
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

            // Swap tokenOut -> USDC
            uint256 usdcReceived = ammRouter.swap(tokenOut, asset, amount, 0);

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

            // Swap USDC -> tokenIn
            uint256 tokensReceived = ammRouter.swap(asset, tokenIn, amount, 0);

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

    // ─── Internal ────────────────────────────────────────────────────

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

    function _convertToShares(uint256 assets) internal view returns (uint256 shares) {
        uint256 _totalSupply = totalSupply();
        uint256 _totalAssets = totalAssets();
        if (_totalSupply == 0 || _totalAssets == 0) {
            shares = assets;
        } else {
            shares = (assets * _totalSupply) / _totalAssets;
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
