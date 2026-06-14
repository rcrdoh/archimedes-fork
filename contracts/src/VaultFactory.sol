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
        address _platformFeeRecipient,
        address _owner
    ) Ownable(_owner) {
        agentAddress = _agentAddress;
        ammRouter = _ammRouter;
        usdc = _usdc;
        platformFeeRecipient = _platformFeeRecipient;
    }

    // ─── Vault Creation ──────────────────────────────────────────────

    function createVault(
        string calldata name,
        string calldata symbol,
        uint16 managementFeeBps,
        uint16 performanceFeeBps,
        bool agentAssisted,
        address _vaultOwner // explicit owner; address(0) defaults to msg.sender
    ) external override returns (address vault) {
        // Tier determination: agent address creates Tier 1, anyone else creates Tier 2
        uint8 vaultTier = msg.sender == agentAddress ? uint8(1) : uint8(2);

        // Resolve owner: explicit governance key preferred; fall back to msg.sender.
        // This separates Ownable admin rights (setTokenOracles, setMaxSlippageBps, pause)
        // from the creator role (Tier 1 detection, fee accrual, rebalance authority).
        address resolvedOwner = _vaultOwner != address(0) ? _vaultOwner : msg.sender;

        Vault newVault = new Vault(
            usdc,
            ammRouter,
            msg.sender, // creator (unchanged — determines tier, receives fees)
            vaultTier,
            managementFeeBps,
            performanceFeeBps,
            agentAssisted,
            platformFeeRecipient,
            name,
            symbol,
            resolvedOwner // owner separate from creator (AUDIT B1)
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
