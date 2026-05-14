// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

/// @title IVault
/// @notice An ERC-4626 tokenized vault that holds synthetic/bridged assets.
///         Users deposit USDC, receive vault tokens. Manager (or agent) rebalances.
///         Non-custodial: agent has rebalance authority, NOT withdraw-to-platform authority.
/// @dev Owner: Chuan (implements). Consumers: Daniel (frontend deposit/withdraw via user wallet),
///      Marten (agent rebalance execution), Önder (vault metrics for portfolio math).
interface IVault {
    // ── Events ───────────────────────────────────────────────
    event Deposit(address indexed sender, address indexed receiver, uint256 assets, uint256 shares);
    event Withdraw(address indexed sender, address indexed receiver, address indexed owner, uint256 assets, uint256 shares);
    event Rebalanced(address indexed caller, uint256 tradesCount, uint256 timestamp);
    event TargetAllocationsSet(uint256 tokensCount, uint256 timestamp);
    event FeesCollected(uint256 managementFee, uint256 performanceFee);

    // ── ERC-4626 Standard ────────────────────────────────────
    /// @notice Deposit USDC and receive vault shares.
    /// @param assets Amount of USDC to deposit (6 decimals)
    /// @param receiver Address to receive vault shares
    /// @return shares Amount of vault shares minted
    function deposit(uint256 assets, address receiver) external returns (uint256 shares);

    /// @notice Withdraw USDC by burning vault shares (specifying asset amount).
    /// @param assets Amount of USDC to withdraw
    /// @param receiver Address to receive USDC
    /// @param owner Address whose shares are burned
    /// @return shares Amount of shares burned
    function withdraw(uint256 assets, address receiver, address owner) external returns (uint256 shares);

    /// @notice Redeem vault shares for USDC (specifying share amount).
    /// @param shares Amount of vault shares to redeem
    /// @param receiver Address to receive USDC
    /// @param owner Address whose shares are burned
    /// @return assets Amount of USDC received
    function redeem(uint256 shares, address receiver, address owner) external returns (uint256 assets);

    /// @notice Total assets (NAV) in USDC terms.
    function totalAssets() external view returns (uint256);

    /// @notice Preview how many shares a deposit would yield.
    function previewDeposit(uint256 assets) external view returns (uint256 shares);

    /// @notice Preview how many assets a redemption would yield.
    function previewRedeem(uint256 shares) external view returns (uint256 assets);

    // ── Management ───────────────────────────────────────────
    /// @notice Execute a rebalance: sell some tokens, buy others, all via AMM.
    ///         Restricted to vault creator OR platform agent address.
    /// @param tokensIn Tokens to buy (receive into vault)
    /// @param amountsIn Amounts to buy of each token
    /// @param tokensOut Tokens to sell (send from vault)
    /// @param amountsOut Amounts to sell of each token
    function rebalance(
        address[] calldata tokensIn,
        uint256[] calldata amountsIn,
        address[] calldata tokensOut,
        uint256[] calldata amountsOut
    ) external;

    /// @notice Set target allocations for the vault (basis points, must sum to 10000).
    ///         Only callable by vault creator.
    /// @param tokens Token addresses for the target allocation
    /// @param weightsBps Weight in basis points per token
    function setTargetAllocations(
        address[] calldata tokens,
        uint256[] calldata weightsBps
    ) external;

    // ── Views ────────────────────────────────────────────────
    /// @notice Get all current holdings (token addresses + amounts).
    function getHoldings()
        external
        view
        returns (address[] memory tokens, uint256[] memory amounts);

    /// @notice Get target allocations.
    function getTargetAllocations()
        external
        view
        returns (address[] memory tokens, uint256[] memory weights);

    /// @notice Vault creator address.
    function creator() external view returns (address);

    /// @notice Vault tier (1 = Archimedes verified, 2 = community).
    function tier() external view returns (uint8);

    /// @notice Management fee in basis points.
    function managementFeeBps() external view returns (uint16);

    /// @notice Performance fee in basis points.
    function performanceFeeBps() external view returns (uint16);

    /// @notice High water mark for performance fee calculation (USDC per share, 18 decimals).
    function highWaterMark() external view returns (uint256);

    /// @notice Whether this vault has agent-assisted rebalancing.
    function isAgentAssisted() external view returns (bool);

    /// @notice USDC token address.
    function asset() external view returns (address);
}
