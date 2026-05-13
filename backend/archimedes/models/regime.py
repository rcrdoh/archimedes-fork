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
