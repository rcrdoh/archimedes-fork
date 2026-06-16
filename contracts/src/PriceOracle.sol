// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

/// @title PriceOracle
/// @notice Admin-updatable price oracle for any asset on Arc testnet.
///         In production, replace with Chainlink feed. For the hackathon,
///         the backend agent pushes price updates periodically.
contract PriceOracle is Ownable {
    /// @notice Asset price in USDC (6 decimals). e.g. $392.60 → 392600000
    uint256 public price;

    /// @notice Human-readable label (e.g. "TSLA", "NVDA", "SPY")
    string public symbol;

    /// @notice Timestamp of the last price update
    uint256 public lastUpdated;

    /// @notice Maximum age before stale (24 hours — hackathon testnet, Circle daily limit)
    uint256 public constant MAX_STALENESS = 24 hours;

    /// @notice Address allowed to push price updates (e.g. Circle wallet)
    address public updater;

    /// @notice Timestamp of the last *setPrice* update (0 until the first one).
    ///         Distinct from lastUpdated (which the constructor seeds) so the
    ///         updateCooldown applies only between two actual updater pushes —
    ///         not between deploy and the first push. forceSetPrice does not
    ///         touch this field; the cooldown only governs the setPrice path.
    uint256 public lastSetPriceTime;

    /// @notice Max allowed move per setPrice, in basis points vs the prior price.
    ///         Default 2000 bps (20%) — generous for a daily-update cadence but
    ///         blocks fat-finger / glitched-feed / compromised-key writes that
    ///         would otherwise flow straight into Vault.totalAssets().
    ///         Owner-configurable via setMaxDeviationBps; for a legitimately
    ///         gapped market the owner can use forceSetPrice (two-step escape
    ///         hatch) so the oracle can never be bricked permanently.
    uint256 public maxDeviationBps = 2000;

    /// @notice Basis-point denominator (100% = 10_000 bps)
    uint256 public constant BPS_DENOMINATOR = 10_000;

    /// @notice Hard cap on single forceSetPrice moves (900% = 10× max change per call).
    ///         Prevents pathological oracle manipulation; legitimate >10× gaps require
    ///         two sequential calls. Unlike setPrice's maxDeviationBps this constant is
    ///         not owner-configurable — it exists precisely to bound a compromised key.
    uint256 public constant FORCE_MAX_DEVIATION_BPS = 90_000;

    /// @notice Minimum spacing between two consecutive setPrice calls, in seconds.
    ///         setPrice already bounds a single move to maxDeviationBps, but with no
    ///         spacing an attacker could chain N max-deviation calls in one block to
    ///         ratchet the price arbitrarily (issue #587). Requiring a gap of at least
    ///         updateCooldown seconds between accepted updates blocks that intra-block
    ///         chaining and limits a compromised key to one bounded move per window,
    ///         giving the owner time to react (rotate the key / forceSetPrice).
    ///         Owner-configurable via setUpdateCooldown; forceSetPrice (owner escape
    ///         hatch) is exempt so the owner can always reprice out-of-band.
    ///         Default 30s — well above Arc's sub-second block time (so it defeats the
    ///         same-block ratchet this guards against) yet comfortably below the oracle
    ///         runner's 60s push cadence (ORACLE_INTERVAL_SECONDS), so legitimate
    ///         updates never trip it. Operators who slow the on-chain push cadence can
    ///         raise this toward MAX_UPDATE_COOLDOWN for a stronger rate limit.
    uint256 public updateCooldown = 30;

    /// @notice Upper bound on the owner-configurable cooldown (1 hour). Prevents the
    ///         owner from setting a cooldown so long that legitimate daily updates are
    ///         blocked, while still allowing the bound to be tuned for the deploy cadence.
    uint256 public constant MAX_UPDATE_COOLDOWN = 1 hours;

    event PriceUpdated(uint256 oldPrice, uint256 newPrice, uint256 timestamp);
    event PriceForced(uint256 oldPrice, uint256 newPrice, uint256 timestamp);
    event MaxDeviationBpsChanged(uint256 oldBps, uint256 newBps);
    event UpdaterChanged(address oldUpdater, address newUpdater);
    event UpdateCooldownChanged(uint256 oldCooldown, uint256 newCooldown);

    error StalePrice();
    error UnauthorizedUpdater();
    error ZeroPrice();
    error PriceDeviationTooLarge(uint256 oldPrice, uint256 newPrice, uint256 maxBps);
    error InvalidDeviationBound();
    error UpdateRateLimited(uint256 lastUpdated, uint256 cooldown, uint256 nowTs);
    error InvalidCooldown();

    modifier onlyUpdater() {
        if (msg.sender != owner() && msg.sender != updater) revert UnauthorizedUpdater();
        _;
    }

    constructor(string memory _symbol, uint256 _initialPrice, address _owner) Ownable(_owner) {
        symbol = _symbol;
        price = _initialPrice;
        lastUpdated = block.timestamp;
        updater = _owner;
        emit PriceUpdated(0, _initialPrice, block.timestamp);
    }

    /// @notice Push a new price. Bounded: rejects zero and any move larger
    ///         than maxDeviationBps vs the prior price. If the market truly
    ///         gapped beyond the bound, the owner uses forceSetPrice (or
    ///         widens the bound via setMaxDeviationBps).
    function setPrice(uint256 _newPrice) external onlyUpdater {
        if (_newPrice == 0) revert ZeroPrice();
        // Rate-limit: require at least updateCooldown seconds between two
        // accepted setPrice pushes (issue #587). Skipped on the very first
        // push (lastSetPriceTime == 0). Combined with the per-call deviation
        // bound, this caps a compromised updater key to one bounded move per
        // cooldown window — it cannot chain many max-deviation calls in a block
        // to ratchet the price. forceSetPrice (owner escape hatch) is exempt.
        if (lastSetPriceTime != 0 && block.timestamp < lastSetPriceTime + updateCooldown) {
            revert UpdateRateLimited(lastSetPriceTime, updateCooldown, block.timestamp);
        }
        uint256 oldPrice = price;
        // Deviation bound only applies once a prior price exists; a zero
        // prior price (bootstrap) accepts any positive first price.
        if (oldPrice != 0) {
            uint256 diff = _newPrice > oldPrice ? _newPrice - oldPrice : oldPrice - _newPrice;
            if (diff * BPS_DENOMINATOR > oldPrice * maxDeviationBps) {
                revert PriceDeviationTooLarge(oldPrice, _newPrice, maxDeviationBps);
            }
        }
        price = _newPrice;
        lastUpdated = block.timestamp;
        lastSetPriceTime = block.timestamp;
        emit PriceUpdated(oldPrice, _newPrice, block.timestamp);
    }

    /// @notice Emergency override — owner-only escape hatch for legitimately
    ///         gapped markets (e.g. a >maxDeviationBps overnight move). Bounded
    ///         by FORCE_MAX_DEVIATION_BPS (900% / 10×) when a prior price exists;
    ///         a legitimate >10× gap requires two sequential calls. Emits a
    ///         distinct event so forced updates are auditable on-chain.
    function forceSetPrice(uint256 _newPrice) external onlyOwner {
        if (_newPrice == 0) revert ZeroPrice();
        uint256 oldPrice = price;
        if (oldPrice != 0) {
            uint256 diff = _newPrice > oldPrice ? _newPrice - oldPrice : oldPrice - _newPrice;
            if (diff * BPS_DENOMINATOR > oldPrice * FORCE_MAX_DEVIATION_BPS) {
                revert PriceDeviationTooLarge(oldPrice, _newPrice, FORCE_MAX_DEVIATION_BPS);
            }
        }
        price = _newPrice;
        lastUpdated = block.timestamp;
        emit PriceForced(oldPrice, _newPrice, block.timestamp);
    }

    /// @notice Adjust the per-update deviation bound. Must be in (0, 10_000];
    ///         a zero bound would brick setPrice entirely and >100% is
    ///         meaningless (use forceSetPrice for gap recovery instead).
    function setMaxDeviationBps(uint256 _maxDeviationBps) external onlyOwner {
        if (_maxDeviationBps == 0 || _maxDeviationBps > BPS_DENOMINATOR) revert InvalidDeviationBound();
        uint256 old = maxDeviationBps;
        maxDeviationBps = _maxDeviationBps;
        emit MaxDeviationBpsChanged(old, _maxDeviationBps);
    }

    /// @notice Adjust the minimum spacing between setPrice calls (issue #587).
    ///         Bounded above by MAX_UPDATE_COOLDOWN so the owner cannot set a
    ///         cooldown long enough to block legitimate daily updates. A value
    ///         of 0 disables rate-limiting (the per-call deviation bound still
    ///         applies) — a deliberate, owner-only choice.
    function setUpdateCooldown(uint256 _cooldown) external onlyOwner {
        if (_cooldown > MAX_UPDATE_COOLDOWN) revert InvalidCooldown();
        uint256 old = updateCooldown;
        updateCooldown = _cooldown;
        emit UpdateCooldownChanged(old, _cooldown);
    }

    function setUpdater(address _updater) external onlyOwner {
        address old = updater;
        updater = _updater;
        emit UpdaterChanged(old, _updater);
    }

    function getPrice() external view returns (uint256) {
        if (block.timestamp > lastUpdated + MAX_STALENESS) revert StalePrice();
        return price;
    }

    function isFresh() external view returns (bool) {
        return block.timestamp <= lastUpdated + MAX_STALENESS;
    }
}
