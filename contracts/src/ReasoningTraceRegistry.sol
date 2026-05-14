// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

import "./interfaces/IReasoningTraceRegistry.sol";

/// @title ReasoningTraceRegistry
/// @notice On-chain provenance anchoring of agent reasoning traces.
///         Stores keccak256 hashes — full traces live off-chain in Postgres.
///         Anyone can verify a trace by recomputing its hash and comparing.
contract ReasoningTraceRegistry is IReasoningTraceRegistry, Ownable {
    // ─── Structs ─────────────────────────────────────────────────────

    struct Trace {
        address agent;
        address vault;
        bytes32 traceHash;
        uint256 timestamp;
        bytes metadata;
    }

    // ─── State ───────────────────────────────────────────────────────

    /// @notice All traces (1-indexed, trace 0 is empty)
    Trace[] private _traces;

    /// @notice agent address => trace IDs
    mapping(address => uint256[]) private _agentTraces;

    /// @notice vault address => trace IDs
    mapping(address => uint256[]) private _vaultTraces;

    // ─── Constructor ─────────────────────────────────────────────────

    constructor(address _owner) Ownable(_owner) {
        // Push empty trace at index 0 (1-indexed)
        _traces.push();
    }

    // ─── Write ───────────────────────────────────────────────────────

    function publishTrace(
        address vault,
        bytes32 traceHash,
        bytes calldata metadata
    ) external override returns (uint256 traceId) {
        traceId = _traces.length;

        _traces.push(Trace({
            agent: msg.sender,
            vault: vault,
            traceHash: traceHash,
            timestamp: block.timestamp,
            metadata: metadata
        }));

        _agentTraces[msg.sender].push(traceId);
        _vaultTraces[vault].push(traceId);

        emit TracePublished(traceId, msg.sender, vault, traceHash, block.timestamp);
    }

    // ─── Read ────────────────────────────────────────────────────────

    function verifyTrace(uint256 traceId, bytes calldata fullTrace)
        external
        view
        override
        returns (bool valid)
    {
        if (traceId == 0 || traceId >= _traces.length) return false;
        return _traces[traceId].traceHash == keccak256(fullTrace);
    }

    function getTraces(address agent, uint256 from, uint256 to)
        external
        view
        override
        returns (bytes32[] memory hashes)
    {
        uint256[] storage ids = _agentTraces[agent];
        if (ids.length == 0 || from > to) return new bytes32[](0);

        // Clamp range
        if (from >= ids.length) from = ids.length;
        if (to >= ids.length) to = ids.length - 1;

        uint256 count = to - from + 1;
        hashes = new bytes32[](count);
        for (uint256 i = 0; i < count; i++) {
            hashes[i] = _traces[ids[from + i]].traceHash;
        }
    }

    function getTraceById(uint256 traceId)
        external
        view
        override
        returns (
            address agent,
            address vault,
            bytes32 traceHash,
            uint256 timestamp,
            bytes memory metadata
        )
    {
        require(traceId > 0 && traceId < _traces.length, "Invalid trace ID");
        Trace storage t = _traces[traceId];
        return (t.agent, t.vault, t.traceHash, t.timestamp, t.metadata);
    }

    function traceCount() external view override returns (uint256) {
        return _traces.length - 1; // Subtract empty index 0
    }

    function getTracesByVault(address vault) external view override returns (uint256[] memory traceIds) {
        return _vaultTraces[vault];
    }
}
