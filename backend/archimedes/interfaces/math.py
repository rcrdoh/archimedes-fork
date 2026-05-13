"""Math interfaces — Önder implements these.

These are pure computation modules with NO web framework, NO database,
and NO on-chain dependencies. They take typed inputs and return typed outputs.
Chuan's backend orchestrator calls them.
"""

from __future__ import annotations

from typing import Protocol

from archimedes.models.asset import MarketSnapshot
from archimedes.models.backtest import BacktestResult
from archimedes.models.portfolio import (
    Portfolio,
    RiskProfile,
    TargetAllocation,
)
from archimedes.models.regime import RegimeClassification
from archimedes.models.strategy import Strategy


class IRegimeDetector(Protocol):
    """Classifies the current market regime from a snapshot.

    Owner: Önder
    Input: MarketSnapshot (prices + VIX + MA + credit spreads)
    Output: RegimeClassification (regime + confidence + signals)

    Design reference: design.md § 4.3.3
    """

    def classify(self, snapshot: MarketSnapshot) -> RegimeClassification:
        """Classify the current market regime.

        Rules (from design.md):
          RISK_ON:    low VIX (<20), price > MA50, price > MA200, tight spreads
          RISK_OFF:   high VIX (>25), price < MA50, widening spreads
          TRANSITION: mixed signals, 20 < VIX < 25
          CRISIS:     extreme VIX (>35), correlation spike

        Must require 2+ confirming signals before changing regime.
        """
        ...

    def get_current_regime(self) -> RegimeClassification | None:
        """Return the most recent classification, or None if never classified."""
        ...


class IPortfolioConstructor(Protocol):
    """Constructs a target portfolio from strategies + regime + risk profile.

    Owner: Önder
    Input: risk profile, available strategies with backtest results, current regime
    Output: list of TargetAllocation (symbol + weight)

    Design reference: design.md § 4.3.2
    """

    def construct(
        self,
        risk_profile: RiskProfile,
        strategies: list[Strategy],
        backtest_results: dict[str, BacktestResult],  # strategy_id → result
        regime: RegimeClassification,
        current_portfolio: Portfolio | None = None,
    ) -> list[TargetAllocation]:
        """Construct target allocations for a vault.

        Algorithm (from design.md § 4.3.2):
          1. Filter strategies by risk profile compatibility
          2. Rank by risk-adjusted return (Sharpe * (1 - correlation_to_portfolio))
          3. Select top N strategies (N = 3-8 depending on profile)
          4. Optimize weights:
             - Minimize portfolio variance subject to target return
             - Max 30% in any single strategy
             - USYC floor per risk profile
             - Max sector/asset concentration
          5. Map strategy weights to token allocations

        Returns list of TargetAllocation with weights summing to 1.0.
        """
        ...

    def score_strategy(
        self,
        strategy: Strategy,
        result: BacktestResult,
        risk_profile: RiskProfile,
    ) -> float:
        """Score a single strategy for a given risk profile.

        Higher = better fit. Used for ranking in construct().
        """
        ...


class IBacktestEvaluator(Protocol):
    """Evaluates a strategy against historical data.

    Owner: Önder
    Input: Strategy definition + historical price data
    Output: BacktestResult with all standard metrics

    Design reference: design.md § 4.2
    """

    def evaluate(
        self,
        strategy: Strategy,
        price_data: dict[str, list[float]],  # symbol → daily prices
        start_date: str | None = None,  # ISO format, e.g. "2020-01-01"
        end_date: str | None = None,
    ) -> BacktestResult:
        """Run a full backtest and return standardized metrics.

        Requirements (from design.md § 4.2):
          - Walk-forward validation: train on 70%, test on 30%, no peeking
          - Transaction costs: 10bps per trade
          - Slippage model: volume-based
          - No survivorship bias
        """
        ...

    def compare_to_paper(
        self,
        result: BacktestResult,
    ) -> bool:
        """Check if backtest results are consistent with paper claims.

        Flag if backtest Sharpe < 50% of paper's claimed Sharpe.
        """
        ...
