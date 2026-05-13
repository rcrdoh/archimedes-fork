"""Reasoning trace data models — design.md § 4.4."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class DecisionType(str, Enum):
    """Type of agent decision that produced the trace."""

    PORTFOLIO_CONSTRUCTION = "construction"  # Initial portfolio build
    REBALANCE = "rebalance"  # Rebalance execution
    STRATEGY_ROTATION = "rotation"  # Strategy swapped in/out
    REGIME_CHANGE = "regime_change"  # Regime classification changed
    SKIP = "skip"  # Agent evaluated but decided not to act


@dataclass
class ReasoningTrace:
    """A structured record of an agent decision.

    Every agent action produces one of these. The hash is anchored on-chain
    via ReasoningTraceRegistry; the full trace is stored off-chain in Postgres.

    Produced by: Chuan (agent orchestrator generates after each decision)
    Consumed by: Marten (publishes hash to ReasoningTraceRegistry contract),
                 Daniel (reasoning trace viewer in UI),
                 Dan (traces reference strategies for provenance)
    """

    id: str  # UUID
    vault_address: str  # Which vault this decision applies to
    decision_type: DecisionType
    trigger: str  # What caused this decision (same as RebalanceDecision.trigger)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Context at decision time
    market_context: dict = field(default_factory=dict)  # Regime, key prices, VIX, etc.
    portfolio_before: dict = field(default_factory=dict)  # Holdings before action
    portfolio_after: dict = field(default_factory=dict)  # Holdings after action

    # The reasoning
    reasoning: str = ""  # LLM-generated explanation of the decision
    confidence: float = 0.0  # 0-1, agent's confidence in the decision
    expected_outcome: str = ""  # What the agent expects to happen

    # Actions taken
    trades_executed: list[dict] = field(default_factory=list)  # Serialized TradeOrders
    strategies_referenced: list[str] = field(default_factory=list)  # Strategy IDs

    # On-chain anchoring
    trace_hash: str = ""  # SHA-256 of the canonical trace content
    arc_tx_hash: str | None = None  # Arc transaction that recorded this hash

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 hash of the trace content.

        This hash is what gets published to ReasoningTraceRegistry on-chain.
        Anyone can verify a trace by recomputing the hash and comparing.
        """
        canonical = json.dumps(
            {
                "id": self.id,
                "vault_address": self.vault_address,
                "decision_type": self.decision_type.value,
                "trigger": self.trigger,
                "timestamp": self.timestamp.isoformat(),
                "market_context": self.market_context,
                "portfolio_before": self.portfolio_before,
                "portfolio_after": self.portfolio_after,
                "reasoning": self.reasoning,
                "confidence": self.confidence,
                "trades_executed": self.trades_executed,
                "strategies_referenced": self.strategies_referenced,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.trace_hash = hashlib.sha256(canonical.encode()).hexdigest()
        return self.trace_hash

    @property
    def is_anchored(self) -> bool:
        """Whether this trace has been published on-chain."""
        return self.arc_tx_hash is not None
