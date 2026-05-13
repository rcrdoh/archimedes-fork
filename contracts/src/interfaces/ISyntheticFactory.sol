// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

/// @title ISyntheticFactory
/// @notice Creates and manages synthetic assets backed by USDC collateral.
///         Hackathon: 100% collateral ratio, no liquidation engine.
/// @dev Owner: Chuan (implements). Consumers: Marten (mint/redeem from backend),
///      Daniel (frontend reads via getPrice/getSynthetics).
///      Vaults call mint/redeem during rebalance.
interface ISyntheticFactory {
    // ── Events ───────────────────────────────────────────────
    event SyntheticCreated(address indexed token, string symbol, address oracle);
    event Minted(address indexed user, address indexed token, uint256 usdcIn, uint256 synthOut);
    event Redeemed(address indexed user, address indexed token, uint256 synthIn, uint256 usdcOut);

    // ── Admin ────────────────────────────────────────────────
    /// @notice Create a new synthetic asset with a price oracle.
    /// @param name Full name (e.g. "Synthetic Tesla")
    /// @param symbol Ticker (e.g. "sTSLA")
    /// @param oracle Address of IPriceOracle for this asset
    /// @return token Address of the newly created ERC-20 synthetic token
    function createSynthetic(
        string calldata name,
        string calldata symbol,
        address oracle
    ) external returns (address token);

    // ── User / Vault ─────────────────────────────────────────
    /// @notice Mint synthetic tokens by depositing USDC.
    /// @param synthetic The synthetic token to mint
    /// @param usdcAmount Amount of USDC to deposit (6 decimals)
    /// @return synthAmount Amount of synthetic tokens minted (18 decimals)
    function mint(
        address synthetic,
        uint256 usdcAmount
    ) external returns (uint256 synthAmount);

    /// @notice Redeem synthetic tokens for USDC.
    /// @param synthetic The synthetic token to burn
    /// @param synthAmount Amount of synthetic tokens to redeem (18 decimals)
    /// @return usdcAmount Amount of USDC returned (6 decimals)
    function redeem(
        address synthetic,
        uint256 synthAmount
    ) external returns (uint256 usdcAmount);

    // ── Views ────────────────────────────────────────────────
    /// @notice Get the current USD price for a synthetic (from its oracle).
    /// @return price Price in USD with 8 decimals
    function getPrice(address synthetic) external view returns (uint256 price);

    /// @notice Total USDC collateral held by the protocol.
    function totalCollateral() external view returns (uint256);

    /// @notice Total USD value of all outstanding synthetic tokens.
    function totalSynthValue() external view returns (uint256);

    /// @notice Collateral health ratio (collateral / synthValue), 18 decimals.
    ///         1e18 = 100% collateralized. Should always be >= 1e18 in hackathon.
    function healthRatio() external view returns (uint256);

    /// @notice List all registered synthetic token addresses.
    function getSynthetics() external view returns (address[] memory);

    /// @notice Get the USDC token address used as collateral.
    function usdc() external view returns (address);
}
