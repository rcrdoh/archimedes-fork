// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

/// @title IPriceOracle
/// @notice Hackathon mock oracle — owner-updatable price feed.
///         Post-hackathon: replace with Pyth/Chainlink integration.
/// @dev Owner: Chuan (implements) + Marten (calls batchSetPrices from oracle updater service)
interface IPriceOracle {
    // ── Events ───────────────────────────────────────────────
    event PriceUpdated(address indexed token, uint256 price, uint256 timestamp);
    event BatchPricesUpdated(uint256 count, uint256 timestamp);

    // ── Write (owner only) ───────────────────────────────────
    /// @notice Set the price for a single token.
    /// @param token The synthetic token address
    /// @param price Price in USD with 8 decimals (e.g. 18500000000 = $185.00)
    function setPrice(address token, uint256 price) external;

    /// @notice Batch-update prices for multiple tokens in one tx.
    /// @param tokens Array of token addresses
    /// @param prices Array of prices (USD, 8 decimals) — must match tokens length
    function batchSetPrices(address[] calldata tokens, uint256[] calldata prices) external;

    // ── Read ─────────────────────────────────────────────────
    /// @notice Get the current price for a token.
    /// @param token The token address
    /// @return price Price in USD with 8 decimals
    /// @return updatedAt Timestamp of last price update
    function getPrice(address token) external view returns (uint256 price, uint256 updatedAt);

    /// @notice Check if a price is stale (older than maxAge seconds).
    /// @param token The token address
    /// @param maxAge Maximum acceptable age in seconds
    /// @return fresh True if price was updated within maxAge
    function isFresh(address token, uint256 maxAge) external view returns (bool fresh);
}
