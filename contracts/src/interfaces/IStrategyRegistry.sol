// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

/// @title IStrategyRegistry
/// @notice On-chain anchoring of Tier-1 strategy registrations.
///         Stores keccak256 hashes — full strategy metadata lives off-chain.
///         Anyone can verify a strategy by recomputing its hash and comparing.
/// @dev Owner: Chuan (implements). Consumer: strategy_publisher.py fires on
///      Tier-1 promotion (rigor gate pass). Front-end reads for verification UI.
interface IStrategyRegistry {
    // ── Events ───────────────────────────────────────────────
    event StrategyRegistered(
        bytes32 indexed strategyId,
        address indexed registrar,
        bytes32 methodologyHash,
        bytes32 paperCorpusHash,
        uint256 timestamp
    );

    // ── Write ────────────────────────────────────────────────
    /// @notice Register a Tier-1 strategy on-chain.
    ///         Only callable by owner (the platform agent).
    /// @param strategyId keccak256 of the strategy's canonical content
    /// @param methodologyHash keccak256 of the methodology / DSL spec
    /// @param paperCorpusHash keccak256 of the concatenated source-paper hashes
    /// @param regimeTag keccak256 of the regime classification tag (bull/bear/transition/neutral)
    /// @param metadataURI Off-chain URI for the full strategy passport JSON
    function registerStrategy(
        bytes32 strategyId,
        bytes32 methodologyHash,
        bytes32 paperCorpusHash,
        bytes32 regimeTag,
        string calldata metadataURI
    ) external;

    // ── Read ─────────────────────────────────────────────────
    /// @notice Check if a strategy is registered on-chain.
    /// @param strategyId The strategy content hash
    /// @return registered True if the strategy has been anchored
    function isRegistered(bytes32 strategyId) external view returns (bool);

    /// @notice Get full registration details for a strategy.
    /// @param strategyId The strategy content hash
    /// @return registrar Address that registered the strategy
    /// @return methodologyHash Hash of the methodology spec
    /// @return paperCorpusHash Hash of the source paper corpus
    /// @return regimeTag Hash of the regime classification
    /// @return timestamp Block timestamp of registration
    /// @return metadataURI Off-chain URI for the full passport
    function getStrategy(bytes32 strategyId)
        external
        view
        returns (
            address registrar,
            bytes32 methodologyHash,
            bytes32 paperCorpusHash,
            bytes32 regimeTag,
            uint256 timestamp,
            string memory metadataURI
        );

    /// @notice Get the total number of registered strategies.
    function strategyCount() external view returns (uint256);

    /// @notice Get a strategy ID by index (for enumeration).
    function strategyByIndex(uint256 index) external view returns (bytes32);
}
