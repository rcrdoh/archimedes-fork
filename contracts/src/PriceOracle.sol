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

    event PriceUpdated(uint256 oldPrice, uint256 newPrice, uint256 timestamp);
    event PriceForced(uint256 oldPrice, uint256 newPrice, uint256 timestamp);
    event MaxDeviationBpsChanged(uint256 oldBps, uint256 newBps);
    event UpdaterChanged(address oldUpdater, address newUpdater);

    error StalePrice();
    error UnauthorizedUpdater();
    error ZeroPrice();
    error PriceDeviationTooLarge(uint256 oldPrice, uint256 newPrice, uint256 maxBps);
    error InvalidDeviationBound();

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
        emit PriceUpdated(oldPrice, _newPrice, block.timestamp);
    }

    /// @notice Emergency override — owner-only escape hatch for legitimately
    ///         gapped markets (e.g. a >maxDeviationBps overnight move). Skips
    ///         the deviation bound but still rejects zero. Emits a distinct
    ///         event so forced updates are auditable on-chain.
    function forceSetPrice(uint256 _newPrice) external onlyOwner {
        if (_newPrice == 0) revert ZeroPrice();
        uint256 oldPrice = price;
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
