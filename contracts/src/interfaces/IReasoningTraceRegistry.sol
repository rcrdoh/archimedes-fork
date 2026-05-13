// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

/// @title IReasoningTraceRegistry
/// @notice On-chain anchoring of agent reasoning traces.
///         Stores hashes (not full traces) — full traces live off-chain in Postgres.
///         Anyone can verify a trace by recomputing its hash and comparing.
/// @dev Owner: Chuan (implements). Consumer: Marten (publishes trace hashes from agent loop).
///      Daniel (frontend reads trace IDs + hashes for verification UI).
interface IReasoningTraceRegistry {
    // ── Events ───────────────────────────────────────────────
    event TracePublished(
        uint256 indexed traceId,
        address indexed agent,
        address indexed vault,
        bytes32 traceHash,
        uint256 timestamp
    );

    // ── Write ────────────────────────────────────────────────
    /// @notice Publish a reasoning trace hash on-chain.
    /// @param vault The vault this trace applies to
    /// @param traceHash SHA-256 hash of the full trace content
    /// @param metadata ABI-encoded metadata (decision_type, trigger, etc.)
    /// @return traceId Auto-incrementing trace ID
    function publishTrace(
        address vault,
        bytes32 traceHash,
        bytes calldata metadata
    ) external returns (uint256 traceId);

    // ── Read ─────────────────────────────────────────────────
    /// @notice Verify a full trace matches the on-chain hash.
    /// @param traceId The trace to verify
    /// @param fullTrace The full trace content to hash and compare
    /// @return valid True if SHA-256(fullTrace) matches the stored hash
    function verifyTrace(
        uint256 traceId,
        bytes calldata fullTrace
    ) external view returns (bool valid);

    /// @notice Get trace hashes published by an agent within a range.
    /// @param agent Agent address
    /// @param from Start trace ID (inclusive)
    /// @param to End trace ID (inclusive)
    /// @return hashes Array of trace hashes
    function getTraces(
        address agent,
        uint256 from,
        uint256 to
    ) external view returns (bytes32[] memory hashes);

    /// @notice Get trace details by ID.
    /// @param traceId The trace ID
    /// @return agent Agent that published this trace
    /// @return vault Vault the trace applies to
    /// @return traceHash The stored hash
    /// @return timestamp When the trace was published
    /// @return metadata The encoded metadata
    function getTraceById(uint256 traceId)
        external
        view
        returns (
            address agent,
            address vault,
            bytes32 traceHash,
            uint256 timestamp,
            bytes memory metadata
        );

    /// @notice Total number of published traces.
    function traceCount() external view returns (uint256);

    /// @notice Get all trace IDs for a specific vault.
    function getTracesByVault(address vault) external view returns (uint256[] memory traceIds);
}
