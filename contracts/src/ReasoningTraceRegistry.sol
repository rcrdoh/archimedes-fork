// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

import "./interfaces/IReasoningTraceRegistry.sol";

/// @title ReasoningTraceRegistry
/// @notice On-chain provenance anchoring of agent reasoning traces.
///         Stores keccak256 hashes — full traces live off-chain in Postgres.
///         Anyone can verify a trace by recomputing its hash and comparing.
///
///         v1.5 (commit-reveal, per docs/specs/commit-reveal-trace-spec.md +
///         audit 2026-06-10 finding #18):
///         - commit() anchors the trace hash BEFORE the covered trade executes,
///           with a time-lock requiring the claimed execution to land at least
///           one block after the commit.
///         - reveal() publishes the content AFTER settlement; the contract
///           recomputes the hash and verifies the binding on-chain.
///         - All anchoring (publishTrace AND commit) is scoped to the vault's
///           agent/owner — arbitrary addresses cannot forge anchors for a vault.
contract ReasoningTraceRegistry is IReasoningTraceRegistry, Ownable {
    // ─── Structs ─────────────────────────────────────────────────────

    struct Trace {
        address agent;
        address vault;
        bytes32 traceHash;
        uint256 timestamp;
        bytes metadata;
    }

    struct Commitment {
        bytes32 contentHash;
        address committer;
        uint64 commitBlock;
        uint64 claimedExecutionTime;
        uint64 revealBlock; // 0 until revealed
        string storagePointer; // empty until revealed
    }

    // ─── State ───────────────────────────────────────────────────────

    /// @notice All traces (1-indexed, trace 0 is empty)
    Trace[] private _traces;

    /// @notice agent address => trace IDs
    mapping(address => uint256[]) private _agentTraces;

    /// @notice vault address => trace IDs
    mapping(address => uint256[]) private _vaultTraces;

    /// @notice trace ID => commit-reveal commitment (only set for commit() traces)
    mapping(uint256 => Commitment) private _commitments;

    /// @notice vault => agent => explicitly granted anchoring authority
    mapping(address => mapping(address => bool)) private _vaultAgents;

    // ─── Constructor ─────────────────────────────────────────────────

    constructor(address _owner) Ownable(_owner) {
        // Push empty trace at index 0 (1-indexed)
        _traces.push();
    }

    // ─── Authorization ───────────────────────────────────────────────

    function setVaultAgent(address vault, address agent, bool authorized) external override onlyOwner {
        _vaultAgents[vault][agent] = authorized;
        emit VaultAgentSet(vault, agent, authorized);
    }

    function isAuthorizedForVault(address vault, address account) public view override returns (bool) {
        if (_vaultAgents[vault][account]) return true;
        if (vault.code.length == 0) return false;
        // Live introspection of Vault-shaped contracts: agent(), creator(), owner().
        return _roleMatches(vault, bytes4(keccak256("agent()")), account)
            || _roleMatches(vault, bytes4(keccak256("creator()")), account)
            || _roleMatches(vault, bytes4(keccak256("owner()")), account);
    }

    /// @dev Non-reverting role probe: staticcall the zero-arg selector and compare
    ///      the returned address. Any failure (missing function, wrong return shape)
    ///      reads as "no match" rather than reverting.
    function _roleMatches(address vault, bytes4 selector, address account) private view returns (bool) {
        (bool ok, bytes memory data) = vault.staticcall(abi.encodeWithSelector(selector));
        return ok && data.length == 32 && abi.decode(data, (address)) == account;
    }

    // ─── Write ───────────────────────────────────────────────────────

    /// @inheritdoc IReasoningTraceRegistry
    /// @dev v1 anchor-after-the-fact, kept for backwards compatibility with the
    ///      existing backend publisher. As of v1.5 it is gated by vault authority —
    ///      it no longer accepts anchors from arbitrary addresses. It carries no
    ///      temporal-binding guarantee; new integrations should use commit()+reveal().
    function publishTrace(
        address vault,
        bytes32 traceHash,
        bytes calldata metadata
    ) external override returns (uint256 traceId) {
        require(isAuthorizedForVault(vault, msg.sender), "Not authorized for vault");
        traceId = _pushTrace(vault, traceHash, metadata);
        emit TracePublished(traceId, msg.sender, vault, traceHash, block.timestamp);
    }

    /// @inheritdoc IReasoningTraceRegistry
    function commit(
        address vault,
        bytes32 contentHash,
        uint64 claimedExecutionTime,
        bytes calldata tradeIntentSummary
    ) external override returns (uint256 traceId) {
        require(isAuthorizedForVault(vault, msg.sender), "Not authorized for vault");
        require(contentHash != bytes32(0), "Empty content hash");
        // Time-lock: the covered execution must be claimed strictly after this
        // block's timestamp — i.e. it lands at least one block after the commit.
        require(claimedExecutionTime > block.timestamp, "Time-lock: execution must follow commit");

        traceId = _pushTrace(vault, contentHash, tradeIntentSummary);

        _commitments[traceId] = Commitment({
            contentHash: contentHash,
            committer: msg.sender,
            commitBlock: uint64(block.number),
            claimedExecutionTime: claimedExecutionTime,
            revealBlock: 0,
            storagePointer: ""
        });

        emit TraceCommitted(traceId, contentHash, msg.sender, vault, block.number, claimedExecutionTime);
    }

    /// @inheritdoc IReasoningTraceRegistry
    function reveal(
        uint256 traceId,
        string calldata storagePointer,
        bytes calldata fullTraceContent
    ) external override {
        Commitment storage c = _commitments[traceId];
        require(c.committer != address(0), "No commitment");
        require(c.revealBlock == 0, "Already revealed");
        require(msg.sender == c.committer, "Not committer");
        // Temporal binding: commit block < execution <= reveal block.
        require(block.number > c.commitBlock, "Time-lock: reveal in commit block");
        require(block.timestamp >= c.claimedExecutionTime, "Reveal before claimed execution");
        // The binding itself: the revealed content must hash to the committed hash.
        require(keccak256(fullTraceContent) == c.contentHash, "Hash mismatch");

        c.revealBlock = uint64(block.number);
        c.storagePointer = storagePointer;

        emit TraceRevealed(traceId, storagePointer, block.number);
    }

    function _pushTrace(address vault, bytes32 traceHash, bytes calldata metadata)
        private
        returns (uint256 traceId)
    {
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

    function getCommitment(uint256 traceId)
        external
        view
        override
        returns (
            bytes32 contentHash,
            address committer,
            address vault,
            uint256 commitBlock,
            uint64 claimedExecutionTime,
            bool revealed,
            uint256 revealBlock,
            string memory storagePointer
        )
    {
        Commitment storage c = _commitments[traceId];
        require(c.committer != address(0), "No commitment");
        return (
            c.contentHash,
            c.committer,
            _traces[traceId].vault,
            c.commitBlock,
            c.claimedExecutionTime,
            c.revealBlock != 0,
            c.revealBlock,
            c.storagePointer
        );
    }

    function getTraces(address agent, uint256 from, uint256 to)
        external
        view
        override
        returns (bytes32[] memory hashes)
    {
        uint256[] storage ids = _agentTraces[agent];
        if (ids.length == 0 || from > to) return new bytes32[](0);

        // An out-of-range start has no results — return empty. (Previously this
        // clamped `from = ids.length`, which then made `to - from` underflow and
        // revert with a panic on any query past the end. audit 2026-06-14)
        if (from >= ids.length) return new bytes32[](0);
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
