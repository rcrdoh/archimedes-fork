// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

import "./interfaces/IVaultFactory.sol";
import "./Vault.sol";

/// @title VaultFactory
/// @notice Creates and tracks Archimedes vaults.
///         Tier 1 = agent-created (verified), Tier 2 = community (permissionless).
contract VaultFactory is IVaultFactory, Ownable {
    // ─── State ───────────────────────────────────────────────────────

    address public immutable override agentAddress;
    address public immutable override ammRouter;
    address public immutable override usdc;

    /// @notice Trace registry passed to every vault this factory creates, so each vault
    ///         enforces commit-before-trade in rebalance() (#589).
    address public immutable traceRegistry;

    address public platformFeeRecipient;

    address[] private _vaults;
    mapping(address => address[]) private _creatorVaults;

    // ─── Events ──────────────────────────────────────────────────────

    // (inherited from IVaultFactory)

    // ─── Constructor ─────────────────────────────────────────────────

    constructor(
        address _agentAddress,
        address _ammRouter,
        address _usdc,
        address _traceRegistry,
        address _platformFeeRecipient,
        address _owner
    ) Ownable(_owner) {
        require(_traceRegistry != address(0), "Trace registry required");
        agentAddress = _agentAddress;
        ammRouter = _ammRouter;
        usdc = _usdc;
        traceRegistry = _traceRegistry;
        platformFeeRecipient = _platformFeeRecipient;
    }

    // ─── Vault Creation ──────────────────────────────────────────────

    function createVault(
        string calldata name,
        string calldata symbol,
        uint16 managementFeeBps,
        uint16 performanceFeeBps,
        bool agentAssisted
    ) external override returns (address vault) {
        // Tier determination: agent address creates Tier 1, anyone else creates Tier 2
        uint8 vaultTier = msg.sender == agentAddress ? uint8(1) : uint8(2);

        Vault newVault = new Vault(
            usdc,
            ammRouter,
            traceRegistry,
            msg.sender,
            vaultTier,
            managementFeeBps,
            performanceFeeBps,
            agentAssisted,
            platformFeeRecipient,
            name,
            symbol
        );

        vault = address(newVault);

        _vaults.push(vault);
        _creatorVaults[msg.sender].push(vault);

        emit VaultCreated(vault, msg.sender, name, symbol, vaultTier);
    }

    // ─── Views ───────────────────────────────────────────────────────

    function getVaults() external view override returns (address[] memory) {
        return _vaults;
    }

    function getVaultsByCreator(address creator_) external view override returns (address[] memory) {
        return _creatorVaults[creator_];
    }

    function vaultCount() external view override returns (uint256) {
        return _vaults.length;
    }

    // ─── Admin ───────────────────────────────────────────────────────

    function setPlatformFeeRecipient(address _recipient) external onlyOwner {
        platformFeeRecipient = _recipient;
    }
}
