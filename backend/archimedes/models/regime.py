"""Regime detection data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Regime(str, Enum):
    """Market regime classification — design.md § 4.3.3."""

    RISK_ON = "risk_on"  # Low VIX, positive momentum, tight spreads
    RISK_OFF = "risk_off"  # High VIX, negative momentum, widening spreads
    TRANSITION = "transition"  # Mixed signals, increasing uncertainty
    CRISIS = "crisis"  # Extreme VIX, correlation spike, flight to safety


@dataclass(frozen=True)
class RegimeSignals:
    """Raw signal values used for regime classification.

    Produced by: Marten (market data fetcher → MarketSnapshot)
    Consumed by: Önder (regime classifier)
    """

    vix_level: float  # Current VIX
    vix_rate_of_change: float  # VIX change over lookback period (fraction)
    sp500_above_ma50: bool  # S&P 500 price > 50-day MA
    sp500_above_ma200: bool  # S&P 500 price > 200-day MA
    credit_spread_ig: float | None = None  # Investment grade spread (bps)
    credit_spread_hy: float | None = None  # High yield spread (bps)
    btc_dominance: float | None = None  # BTC dominance %
    cross_asset_correlation: float | None = None  # Average pairwise correlation


@dataclass(frozen=True)
class RegimeClassification:
    """Output of the regime detection model.

    Produced by: Önder (regime detection module)
    Consumed by: Chuan (agent orchestrator — decides rebalance action),
                 Daniel (frontend — show current regime),
                 Marten (reasoning trace context)
    """

    regime: Regime
    confidence: float  # 0.0 to 1.0
    signals: RegimeSignals  # The input signals that produced this classification
    timestamp: datetime
    previous_regime: Regime | None = None  # None on first classification
    regime_changed: bool = False  # True if regime differs from previous

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")


class ConsensusLabel(str, Enum):
    """Three-bucket label for the strategy ensemble's directional consensus.

    Deliberately NOT a `Regime`. This describes how directional the *strategy
    ensemble* is right now (endogenous: derived from the very strategies that
    would be conditioned on the regime), not what the *market* is doing
    (exogenous: VIX / momentum / spreads, measured by a regime detector).
    The bucket names rhyme with the regime names by convention, but the
    semantics are distinct — see issue #659.
    """

    RISK_ON = "risk_on"  # Mostly directional signals — ensemble is confident
    TRANSITION = "transition"  # Mixed — a meaningful fraction of signals are flat
    RISK_OFF = "risk_off"  # Mostly flat signals — ensemble is uncertain/defensive


@dataclass(frozen=True)
class EnsembleConsensus:
    """How decisive the strategy ensemble is — agent consensus, not market regime.

    Built from `flat_pct` (the fraction of strategy signals that are flat). This
    is an *ensemble-uncertainty* signal: a high flat fraction means most
    strategies abstain, so the agent is collectively uncertain. It is endogenous
    — derived from the strategies themselves — and must never be persisted or
    surfaced as a market `Regime` (issue #659).

    Produced by: the strategy runner (agent_runner) once per tick.
    Consumed by: reasoning traces, rebalance logs, and the API as an explicitly
                 labelled "ensemble consensus" signal — kept distinct from the
                 exogenous market regime (which stays `None`/"unknown" until an
                 `IRegimeDetector` is wired, a separate issue).
    """

    flat_pct: float  # Fraction of signals that are flat, 0.0–1.0
    signal_count: int  # Total number of strategy signals considered
    label: ConsensusLabel  # Three-bucket directional consensus

    # Bucket thresholds — kept here so the one true mapping lives in the model,
    # not duplicated across agent_runner / strategies_routes.
    _FLAT_RISK_OFF = 0.6  # > 60% flat → defensive consensus
    _FLAT_TRANSITION = 0.3  # > 30% flat → mixed consensus

    def __post_init__(self) -> None:
        if not 0.0 <= self.flat_pct <= 1.0:
            raise ValueError(f"flat_pct must be 0-1, got {self.flat_pct}")
        if self.signal_count < 0:
            raise ValueError(f"signal_count must be >= 0, got {self.signal_count}")

    @classmethod
    def label_for(cls, flat_pct: float) -> ConsensusLabel:
        """Map a flat fraction to its three-bucket consensus label."""
        if flat_pct > cls._FLAT_RISK_OFF:
            return ConsensusLabel.RISK_OFF
        if flat_pct > cls._FLAT_TRANSITION:
            return ConsensusLabel.TRANSITION
        return ConsensusLabel.RISK_ON

    @classmethod
    def from_signal_counts(cls, flat_count: int, total_count: int) -> EnsembleConsensus:
        """Build from raw flat/total signal counts (the agent_runner call site)."""
        flat_pct = flat_count / total_count if total_count > 0 else 0.0
        return cls(flat_pct=flat_pct, signal_count=total_count, label=cls.label_for(flat_pct))
