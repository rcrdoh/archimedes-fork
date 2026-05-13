"""Backtest result data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class BacktestResult:
    """Standardized output of backtesting a strategy.

    Produced by: Önder (backtest evaluation engine)
    Consumed by: Chuan (strategy DB, portfolio agent ranking),
                 Dan (validation gate — compare to paper claims),
                 Daniel (performance charts in UI)
    """

    strategy_id: str  # FK to Strategy.id

    # ── Core risk-adjusted metrics ──────────────────────────
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float  # As a positive fraction, e.g. 0.15 = 15%
    cagr: float  # Compound annual growth rate as fraction
    calmar_ratio: float  # CAGR / max_drawdown

    # ── Trade statistics ────────────────────────────────────
    win_rate: float  # Fraction of winning trades
    profit_factor: float  # Gross profit / gross loss
    total_trades: int
    avg_holding_period_days: float

    # ── Correlation (diversification signal) ────────────────
    correlation_to_spy: float  # -1 to 1
    correlation_to_btc: float  # -1 to 1

    # ── Time series ─────────────────────────────────────────
    equity_curve: list[float] = field(default_factory=list)  # Daily equity values
    monthly_returns: list[float] = field(default_factory=list)

    # ── Period ──────────────────────────────────────────────
    backtest_start: date | None = None
    backtest_end: date | None = None

    # ── Paper comparison ────────────────────────────────────
    paper_claimed_sharpe: float | None = None

    @property
    def sharpe_vs_paper(self) -> float | None:
        """Ratio of backtest Sharpe to paper's claimed Sharpe.

        Used by Dan's validation gate: reject if < 0.5
        """
        if self.paper_claimed_sharpe and self.paper_claimed_sharpe > 0:
            return self.sharpe_ratio / self.paper_claimed_sharpe
        return None

    @property
    def passes_validation(self) -> bool:
        """Quick check against design.md § 4.2 validation criteria."""
        return (
            self.sharpe_ratio > 0.5
            and self.max_drawdown < 0.5
            and self.cagr < 10.0  # Reject >1000% annual as unrealistic
            and self.total_trades >= 10
        )
