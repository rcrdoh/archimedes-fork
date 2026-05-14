// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

import "./interfaces/IAssetRegistry.sol";

/// @title AssetRegistry
/// @notice On-chain registry of all assets and vaults in the Archimedes ecosystem.
///         Powers the leaderboard and asset discovery.
contract AssetRegistry is IAssetRegistry, Ownable {
    // ─── Structs ─────────────────────────────────────────────────────

    struct SyntheticInfo {
        bytes32 oracleId;
        bytes metadata;
        bool registered;
    }

    struct BridgedInfo {
        uint256 sourceChainId;
        address sourceToken;
        bool registered;
    }

    struct VaultInfo {
        uint8 tier;
        bytes metadata;
        uint256 aum;
        bool registered;
    }

    // ─── State ───────────────────────────────────────────────────────

    /// @notice Synthetic assets
    mapping(address => SyntheticInfo) private _synthetics;
    address[] private _syntheticList;

    /// @notice Bridged assets
    mapping(address => BridgedInfo) private _bridged;
    address[] private _bridgedList;

    /// @notice Vaults
    mapping(address => VaultInfo) private _vaults;
    address[] private _vaultList;

    // ─── Constructor ─────────────────────────────────────────────────

    constructor(address _owner) Ownable(_owner) {}

    // ─── Synthetic Assets ────────────────────────────────────────────

    function registerSynthetic(
        address token,
        bytes32 oracleId,
        bytes calldata metadata
    ) external override onlyOwner {
        require(!_synthetics[token].registered, "Already registered");
        _synthetics[token] = SyntheticInfo({
            oracleId: oracleId,
            metadata: metadata,
            registered: true
        });
        _syntheticList.push(token);

        emit SyntheticRegistered(token, _symbolFromMetadata(metadata));
    }

    function getSynthetic(address token) external view override returns (bytes memory metadata) {
        return _synthetics[token].metadata;
    }

    function getAllSynthetics() external view override returns (address[] memory) {
        return _syntheticList;
    }

    // ─── Bridged Assets ──────────────────────────────────────────────

    function registerBridged(
        address token,
        uint256 sourceChainId,
        address sourceToken
    ) external override onlyOwner {
        require(!_bridged[token].registered, "Already registered");
        _bridged[token] = BridgedInfo({
            sourceChainId: sourceChainId,
            sourceToken: sourceToken,
            registered: true
        });
        _bridgedList.push(token);

        emit BridgedRegistered(token, sourceChainId);
    }

    // ─── Vaults ──────────────────────────────────────────────────────

    function registerVault(
        address vault,
        uint8 tier,
        bytes calldata metadata
    ) external override onlyOwner {
        require(!_vaults[vault].registered, "Already registered");
        _vaults[vault] = VaultInfo({
            tier: tier,
            metadata: metadata,
            aum: 0,
            registered: true
        });
        _vaultList.push(vault);

        emit VaultRegistered(vault, tier, msg.sender);
    }

    function updateVaultMetrics(address vault, bytes calldata metrics) external override onlyOwner {
        require(_vaults[vault].registered, "Vault not registered");

        // Decode AUM from metrics (first 32 bytes)
        if (metrics.length >= 32) {
            _vaults[vault].aum = abi.decode(metrics[:32], (uint256));
        }
        _vaults[vault].metadata = metrics;

        emit VaultMetricsUpdated(vault, _vaults[vault].aum, block.timestamp);
    }

    function getLeaderboard(uint8 tier, uint256 limit)
        external
        view
        override
        returns (address[] memory vaults)
    {
        // Count matching vaults
        uint256 total;
        for (uint256 i = 0; i < _vaultList.length; i++) {
            if (tier == 0 || _vaults[_vaultList[i]].tier == tier) {
                total++;
            }
        }

        if (total == 0) return new address[](0);

        // Build full sorted array
        address[] memory allAddrs = new address[](total);
        uint256[] memory allAums = new uint256[](total);
        uint256 idx;

        for (uint256 i = 0; i < _vaultList.length; i++) {
            if (tier == 0 || _vaults[_vaultList[i]].tier == tier) {
                allAddrs[idx] = _vaultList[i];
                allAums[idx] = _vaults[_vaultList[i]].aum;
                idx++;
            }
        }

        // Simple insertion sort descending by AUM
        for (uint256 i = 1; i < total; i++) {
            address keyAddr = allAddrs[i];
            uint256 keyAum = allAums[i];
            uint256 j = i;
            while (j > 0 && allAums[j - 1] < keyAum) {
                allAddrs[j] = allAddrs[j - 1];
                allAums[j] = allAums[j - 1];
                j--;
            }
            allAddrs[j] = keyAddr;
            allAums[j] = keyAum;
        }

        // Apply limit
        uint256 resultCount = limit > 0 && limit < total ? limit : total;

        vaults = new address[](resultCount);
        for (uint256 i = 0; i < resultCount; i++) {
            vaults[i] = allAddrs[i];
        }
    }

    function vaultCount() external view override returns (uint256) {
        return _vaultList.length;
    }

    // ─── Helpers ─────────────────────────────────────────────────────

    function _symbolFromMetadata(bytes memory metadata) internal pure returns (string memory) {
        // Try to extract symbol from ABI-encoded metadata
        // For now, just return empty string — the event still fires correctly
        return "";
    }
}
