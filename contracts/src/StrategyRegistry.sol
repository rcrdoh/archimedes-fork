// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

import "./interfaces/IStrategyRegistry.sol";

/// @title StrategyRegistry
/// @notice On-chain provenance anchoring of Tier-1 (rigor-gate-passed) strategies.
///         Stores keccak256 hashes — full strategy passports live off-chain.
///         Anyone can verify a strategy by recomputing its hash and comparing.
///
///         Registration is restricted to the contract owner (the platform agent).
///         Only strategies that have passed the rigor gate (DSR + PBO +
///         walk-forward OOS + look-ahead audit) should be registered here.
///         Candidate / rejected strategies MUST NOT be anchored on-chain.
contract StrategyRegistry is IStrategyRegistry, Ownable {
    // ─── Structs ─────────────────────────────────────────────────────

    struct Strategy {
        address registrar;
        bytes32 methodologyHash;
        bytes32 paperCorpusHash;
        bytes32 regimeTag;
        uint256 timestamp;
        string metadataURI;
    }

    // ─── State ───────────────────────────────────────────────────────

    /// @notice strategyId (keccak256 content hash) → Strategy data
    mapping(bytes32 => Strategy) private _strategies;

    /// @notice Ordered list of all registered strategy IDs (for enumeration)
    bytes32[] private _strategyIds;

    // ─── Constructor ─────────────────────────────────────────────────

    constructor(address _owner) Ownable(_owner) {}

    // ─── Write ───────────────────────────────────────────────────────

    function registerStrategy(
        bytes32 strategyId,
        bytes32 methodologyHash,
        bytes32 paperCorpusHash,
        bytes32 regimeTag,
        string calldata metadataURI
    ) external override onlyOwner {
        require(strategyId != bytes32(0), "Invalid strategy ID");
        require(
            _strategies[strategyId].timestamp == 0,
            "Already registered"
        );

        _strategies[strategyId] = Strategy({
            registrar: msg.sender,
            methodologyHash: methodologyHash,
            paperCorpusHash: paperCorpusHash,
            regimeTag: regimeTag,
            timestamp: block.timestamp,
            metadataURI: metadataURI
        });

        _strategyIds.push(strategyId);

        emit StrategyRegistered(
            strategyId,
            msg.sender,
            methodologyHash,
            paperCorpusHash,
            block.timestamp
        );
    }

    // ─── Read ────────────────────────────────────────────────────────

    function isRegistered(bytes32 strategyId)
        external
        view
        override
        returns (bool)
    {
        return _strategies[strategyId].timestamp != 0;
    }

    function getStrategy(bytes32 strategyId)
        external
        view
        override
        returns (
            address registrar,
            bytes32 methodologyHash,
            bytes32 paperCorpusHash,
            bytes32 regimeTag,
            uint256 timestamp,
            string memory metadataURI
        )
    {
        require(
            _strategies[strategyId].timestamp != 0,
            "Strategy not found"
        );
        Strategy storage s = _strategies[strategyId];
        return (
            s.registrar,
            s.methodologyHash,
            s.paperCorpusHash,
            s.regimeTag,
            s.timestamp,
            s.metadataURI
        );
    }

    function strategyCount() external view override returns (uint256) {
        return _strategyIds.length;
    }

    function strategyByIndex(uint256 index)
        external
        view
        override
        returns (bytes32)
    {
        require(index < _strategyIds.length, "Index out of bounds");
        return _strategyIds[index];
    }
}
