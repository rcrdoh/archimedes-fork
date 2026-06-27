// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

/// @title IReasoningTraceRegistry
/// @notice On-chain anchoring of agent reasoning traces.
///         Stores hashes (not full traces) — full traces live off-chain in Postgres.
///         Anyone can verify a trace by recomputing its hash and comparing.
///         v1.5 adds commit-reveal provenance per docs/specs/commit-reveal-trace-spec.md:
///         the agent commits the trace hash BEFORE the trade executes and reveals the
///         content afterwards, proving commit block < execution < reveal block.
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

    event TraceCommitted(
        uint256 indexed traceId,
        bytes32 indexed contentHash,
        address indexed committer,
        address vault,
        uint256 commitBlock,
        uint64 claimedExecutionTime
    );

    event TraceRevealed(
        uint256 indexed traceId,
        string storagePointer,
        uint256 revealBlock
    );

    /// @notice Emitted when a vault consumes a matching commitment as it executes
    ///         the covered trade (the on-chain commit-before-trade enforcement point).
    event TradeExecuted(
        uint256 indexed traceId,
        address indexed vault,
        bytes32 indexed tradeId,
        uint256 executeBlock
    );

    event VaultAgentSet(address indexed vault, address indexed agent, bool authorized);

    // ── Write ────────────────────────────────────────────────
    /// @notice Publish a reasoning trace hash on-chain (v1 anchor-after-the-fact).
    ///         Kept for backwards compatibility; as of v1.5 it is GATED — the caller
    ///         must be authorized for the vault (see isAuthorizedForVault). It carries
    ///         no temporal-binding guarantee; prefer commit() + reveal().
    /// @param vault The vault this trace applies to
    /// @param traceHash keccak256 hash of the full trace content
    /// @param metadata ABI-encoded metadata (decision_type, trigger, etc.)
    /// @return traceId Auto-incrementing trace ID
    function publishTrace(
        address vault,
        bytes32 traceHash,
        bytes calldata metadata
    ) external returns (uint256 traceId);

    /// @notice Commit a reasoning trace hash BEFORE the trade it covers executes.
    ///         Time-lock: claimedExecutionTime must be strictly after the commit
    ///         block's timestamp, i.e. the covered execution lands >= 1 block later.
    ///         Caller must be authorized for the vault.
    /// @param vault The vault the upcoming trade applies to
    /// @param contentHash keccak256 of the canonical trace JSON
    /// @param claimedExecutionTime Unix time the covered trade is claimed to execute at
    /// @param tradeId Identifier binding this commitment to a specific trade —
    ///        keccak256(abi.encode(tokensIn, amountsIn, tokensOut, amountsOut)) of the
    ///        rebalance the commitment authorizes (#589). The Vault recomputes this in
    ///        rebalance() and calls executeTrade(tradeId); a mismatch means no matching
    ///        commitment exists and the trade reverts.
    /// @param tradeIntentSummary ABI-encoded: decisionType, numTrades, totalNotionalUsdc
    /// @return traceId Auto-incrementing trace ID (shared ID space with publishTrace)
    function commit(
        address vault,
        bytes32 contentHash,
        uint64 claimedExecutionTime,
        bytes32 tradeId,
        bytes calldata tradeIntentSummary
    ) external returns (uint256 traceId);

    /// @notice Consume the fresh commitment that authorizes `tradeId` for the calling
    ///         vault, at the moment the vault executes that trade. MUST be called by the
    ///         vault itself (msg.sender == vault). Reverts if no fresh (committed in an
    ///         earlier block, unrevealed, not-yet-executed) commitment binds this
    ///         (vault, tradeId) — this is the on-chain "a trade cannot settle without a
    ///         prior matching commit" guarantee (#589 / #510 acceptance criterion 1).
    /// @param tradeId keccak256(abi.encode(tokensIn, amountsIn, tokensOut, amountsOut))
    /// @return traceId The trace ID of the consumed commitment
    function executeTrade(bytes32 tradeId) external returns (uint256 traceId);

    /// @notice The trace ID of the fresh, unconsumed commitment binding (vault, tradeId),
    ///         or 0 if none exists. View counterpart to executeTrade for off-chain checks.
    function pendingTradeCommitment(address vault, bytes32 tradeId)
        external
        view
        returns (uint256 traceId);

    /// @notice Reveal the full trace content AFTER the trade settles.
    ///         Verifies keccak256(fullTraceContent) matches the committed hash,
    ///         that the reveal lands in a later block than the commit, and that
    ///         the claimed execution time has passed. Only the committer may reveal.
    /// @param traceId The trace ID returned by commit()
    /// @param storagePointer Off-chain pointer to the canonical trace (URL/IPFS/Arweave)
    /// @param fullTraceContent Full trace bytes for on-chain hash verification
    function reveal(
        uint256 traceId,
        string calldata storagePointer,
        bytes calldata fullTraceContent
    ) external;

    /// @notice Grant or revoke an agent's anchoring authority for a vault.
    ///         Registry-owner only. Vault contracts exposing agent()/creator()/owner()
    ///         are also recognized automatically (no explicit grant needed).
    function setVaultAgent(address vault, address agent, bool authorized) external;

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

    /// @notice Get a commit-reveal commitment by trace ID.
    /// @param traceId The trace ID returned by commit()
    /// @return contentHash The committed keccak256 hash
    /// @return committer Address that made the commitment
    /// @return vault The vault the covered trade applies to
    /// @return commitBlock Block number of the commit transaction
    /// @return claimedExecutionTime Unix time the covered trade was claimed to execute at
    /// @return revealed True once reveal() has succeeded
    /// @return revealBlock Block number of the reveal transaction (0 until revealed)
    /// @return storagePointer Off-chain pointer to the canonical trace (empty until revealed)
    function getCommitment(uint256 traceId)
        external
        view
        returns (
            bytes32 contentHash,
            address committer,
            address vault,
            uint256 commitBlock,
            uint64 claimedExecutionTime,
            bool revealed,
            uint256 revealBlock,
            string memory storagePointer
        );

    /// @notice True if `account` may anchor traces for `vault` — either explicitly
    ///         granted via setVaultAgent, or recognized live as the vault's
    ///         agent()/creator()/owner().
    function isAuthorizedForVault(address vault, address account) external view returns (bool);
}
