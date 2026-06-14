// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

/// @title IVaultFactory
/// @notice Creates and tracks Archimedes vaults.
///         Tier 1 vaults are created by the platform agent address.
///         Tier 2 vaults are created by any wallet (permissionless).
/// @dev Owner: Chuan (implements). Consumers: Daniel (frontend vault creation flow),
///      Marten (registers new vaults in backend).
interface IVaultFactory {
    // ── Events ───────────────────────────────────────────────
    event VaultCreated(
        address indexed vault,
        address indexed creator,
        string name,
        string symbol,
        uint8 tier
    );

    // ── Vault Creation ───────────────────────────────────────
    /// @notice Create a new managed vault.
    /// @param name Human-readable name (e.g. "Momentum Alpha")
    /// @param symbol Vault token ticker (e.g. "vMOMENTUM")
    /// @param managementFeeBps Annual management fee in bps (e.g. 150 = 1.50%)
    /// @param performanceFeeBps Performance fee in bps above HWM (e.g. 2000 = 20%)
    /// @param agentAssisted Whether to opt into AI rebalancing
    /// @return vault Address of the newly created Vault contract
    function createVault(
        string calldata name,
        string calldata symbol,
        uint16 managementFeeBps,
        uint16 performanceFeeBps,
        bool agentAssisted
    ) external returns (address vault);

    // ── Views ────────────────────────────────────────────────
    /// @notice List all vault addresses.
    function getVaults() external view returns (address[] memory);

    /// @notice List vaults created by a specific address.
    function getVaultsByCreator(address creator) external view returns (address[] memory);

    /// @notice Total number of vaults.
    function vaultCount() external view returns (uint256);

    /// @notice The platform agent address (creates Tier 1 vaults).
    function agentAddress() external view returns (address);

    /// @notice The AMM router used by vaults for rebalancing.
    function ammRouter() external view returns (address);

    /// @notice The USDC token address.
    function usdc() external view returns (address);
}
