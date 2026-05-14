"""Strategy data models — shared across all components."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class StrategyStatus(str, Enum):
    """Lifecycle state of a strategy."""

    CANDIDATE = "candidate"  # Extracted from paper, not yet validated
    VALIDATED = "validated"  # Passed backtesting validation gate
    LIVE = "live"  # Active in at least one portfolio
    RETIRED = "retired"  # Removed from active use


class PositionSizing(str, Enum):
    EQUAL_WEIGHT = "equal_weight"
    RISK_PARITY = "risk_parity"
    KELLY = "kelly"
    INVERSE_VOL = "inverse_vol"


class RebalanceFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass(frozen=True)
class SignalDefinition:
    """A single entry/exit signal used by a strategy.

    Kept intentionally simple for the hackathon — a human-readable
    description + the key parameters. Post-hackathon this becomes
    executable code.
    """

    name: str  # e.g. "50/200 MA crossover"
    direction: str  # "entry" | "exit"
    description: str  # Human-readable explanation
    parameters: dict[str, float] = field(default_factory=dict)  # e.g. {"fast_period": 50}


@dataclass
class Strategy:
    """A trading strategy extracted from an academic paper.

    Produced by: Dan (curated library + LLM extraction)
    Consumed by: Önder (backtest evaluation, portfolio construction),
                 Chuan (strategy DB, API), Daniel (strategy explorer UI)
    """

    id: str  # Deterministic hash of paper + methodology
    paper_arxiv_id: str  # e.g. "2509.11420"
    paper_title: str
    paper_authors: list[str] = field(default_factory=list)
    methodology_summary: str = ""  # 2-3 sentence plain English
    asset_universe: list[str] = field(default_factory=list)  # Ticker symbols
    signals: list[SignalDefinition] = field(default_factory=list)
    position_sizing: PositionSizing = PositionSizing.EQUAL_WEIGHT
    rebalance_frequency: RebalanceFrequency = RebalanceFrequency.WEEKLY
    risk_constraints: dict[str, float] = field(
        default_factory=dict
    )  # e.g. {"max_drawdown": 0.20, "max_leverage": 1.0}
    status: StrategyStatus = StrategyStatus.CANDIDATE
    extraction_reasoning: str = ""  # Full LLM reasoning for extraction
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status in (StrategyStatus.VALIDATED, StrategyStatus.LIVE)
