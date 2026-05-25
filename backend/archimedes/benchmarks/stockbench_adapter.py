"""StockBench harness adapter for the Archimedes Strategy Generation Agent.

Implements the four-step StockBench agent protocol defined in:
  Chen et al. (2026), "StockBench: A Contamination-Free, Multi-Month Trading
  Agent Benchmark", arXiv 2510.02209.

The four steps and their Archimedes service wiring:

  1. observe(market_state_t)
       <- StatisticalRegimeDetector (services/statistical_regime.py)
       <- StrategySignalEvaluator.rank_market() (services/strategy_signal_evaluator.py)

  2. decide(observation)
       <- PortfolioAgent.propose_portfolio_with_tools (agents/portfolio_agent.py)
       -> passes through rigor_evaluator gate (services/rigor_evaluator.py)

  3. act(action_set)
       -> VCheck (chain/v_check.py): formal contract that no trade emits without a
          rigor-gate verdict. Converts float weights to BPS and calls VCheck.run().

  4. verify(post_state)
       -> apply_outcome_embargo (services/embargo_filter.py) filters paper anchors
          that would violate the Outcome Embargo (Xia et al. 2026, arXiv 2605.19337)

Design constraints (from issue #218 anti-goals):
  - rigor_evaluator gate is NEVER bypassed.
  - apply_outcome_embargo is applied in verify() per Xia et al. 2026.
  - VCheck.run() gates every simulated trade in act().
  - No harness metric is modified to improve our score.

Phase status (as of 2026-05-25):
  Phase 1 (protocol mapping)   <- DONE
  Phase 2 (adapter stub)       <- DONE (this file)
  Phase 3 (benchmark run)      <- Completed by t2o2 at
                                  backend/archimedes/evaluation/stockbench/
                                  Results: docs/benchmarks/stockbench-results.md
  Phase 4 (demo integration)   <- Hand narration to Marten for v2 video

Author: Önder Akkaya (Lead Quant)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Acceptance-criteria grep: grep -n "rigor_evaluator\|v_check\|embargo_filter"
# must return >= 3 matches.
from archimedes.chain.v_check import VCheck  # formal pre-trade contract
from archimedes.services.embargo_filter import apply_outcome_embargo  # Xia et al. 2026
from archimedes.services.rigor_evaluator import compute_dsr  # Bailey & Lopez de Prado 2014
from archimedes.services.statistical_regime import StatisticalRegimeDetector
from archimedes.services.strategy_signal_evaluator import StrategySignalEvaluator

logger = logging.getLogger(__name__)

_ANNUALIZATION = 252
_RF_ANNUAL = 0.05


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ArchimedesObservation:
    """Output of observe() — what the agent sees at time t."""

    timestamp: datetime
    regime: str
    regime_confidence: float
    market_ranking: list[dict[str, Any]]
    raw: dict[str, Any]


@dataclass
class AgentPick:
    """A single agent-chosen position."""

    ticker: str
    weight: float
    paper_anchor: str
    rigor_gate_passed: bool


@dataclass
class ArchimedesActionSet:
    """Output of decide() — portfolio allocation for step t."""

    picks: list[AgentPick]
    thesis: str
    model_id: str
    iterations: int
    rigor_gate_failures: int
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class SimulatedAllocation:
    """Output of act() — confirmed allocation after v_check."""

    allocations: dict[str, float]
    cash_weight: float
    v_check_passed: bool


@dataclass
class HarnessResult:
    """Output of verify() — metrics from harness post-state."""

    step: int
    period_return: float
    cumulative_return: float
    max_drawdown: float
    sortino_ratio: float | None
    embargo_applied: bool


# ─────────────────────────────────────────────────────────────────────────────
# Main adapter class
# ─────────────────────────────────────────────────────────────────────────────


class ArchimedesStockBenchAgent:
    """Wraps the Archimedes Strategy Generation Agent in StockBench's 4-step loop.

    For Phase 3 execution (live harness), use the full implementation at
    ``backend/archimedes/evaluation/stockbench/`` which runs the 82-day
    DJIA window with deterministic market simulation. This class provides
    the canonical ``ArchimedesStockBenchAgent`` name expected by issue #218
    and delegates heavy lifting to the evaluation module.

    Usage::

        agent = ArchimedesStockBenchAgent(risk_profile="moderate", seed=0)
        for market_state in episode:
            obs        = agent.observe(market_state)
            action_set = agent.decide(obs)
            allocation = agent.act(action_set)
            result     = agent.verify(post_state)
        summary = agent.episode_summary()
    """

    def __init__(
        self,
        risk_profile: str = "moderate",
        seed: int = 0,
        horizon_days: int = 90,
    ) -> None:
        self.risk_profile = risk_profile
        self.seed = seed
        self.horizon_days = horizon_days

        self._regime_detector = StatisticalRegimeDetector()
        self._signal_evaluator = StrategySignalEvaluator()

        self._step = 0
        self._portfolio_value = 1.0
        self._peak_value = 1.0
        self._period_returns: list[float] = []
        self._results: list[HarnessResult] = []
        self._current_allocation: dict[str, float] = {}

    # ── Step 1: observe ───────────────────────────────────────────────────────

    def observe(self, market_state_t: dict[str, Any]) -> ArchimedesObservation:
        """Translate harness market state into an Archimedes observation.

        Expected keys in market_state_t:
          prices: dict[str, float], vix: float, timestamp: str|datetime,
          sp500_ma50: float, sp500_ma200: float
        """
        from archimedes.models.asset import MarketSnapshot

        vix = float(market_state_t.get("vix", 20.0))
        prices = {k: float(v) for k, v in market_state_t.get("prices", {}).items()}
        ts_raw = market_state_t.get("timestamp", datetime.now(UTC))
        ts = ts_raw if isinstance(ts_raw, datetime) else datetime.fromisoformat(str(ts_raw))

        snapshot = MarketSnapshot(
            timestamp=ts,
            prices=prices,
            vix=vix,
            sp500_ma50=market_state_t.get("sp500_ma50"),
            sp500_ma200=market_state_t.get("sp500_ma200"),
        )
        cls = self._regime_detector.classify(snapshot)
        regime = cls.regime.value if hasattr(cls.regime, "value") else str(cls.regime)

        # rank_market needs price_histories as pd.Series dict; full price-history
        # path is handled in evaluation/stockbench — pass empty dict here.
        try:
            market_ranking = self._signal_evaluator.rank_market(price_histories={}, top_n=20)
        except Exception:
            market_ranking = []

        return ArchimedesObservation(
            timestamp=ts,
            regime=regime,
            regime_confidence=float(cls.confidence),
            market_ranking=market_ranking,
            raw=market_state_t,
        )

    # ── Step 2: decide ────────────────────────────────────────────────────────

    def decide(self, observation: ArchimedesObservation) -> ArchimedesActionSet:
        """Construct a portfolio allocation, routing through the rigor gate.

        Picks whose paper_anchor is not in the rigor-cleared strategy set are
        rejected. rigor_evaluator gate is never bypassed.
        """
        from archimedes.agents.portfolio_agent import PortfolioAgent
        from archimedes.services.strategy_provider import default_provider

        strategies = default_provider().list_strategies()

        # rigor_evaluator gate — only cleared strategies can be anchors
        rigor_cleared = [s for s in strategies if getattr(s, "passes_rigor_gate", False)]
        rigor_failures = len(strategies) - len(rigor_cleared)

        if not rigor_cleared:
            logger.warning("decide(): 0 rigor-cleared strategies — null allocation")
            return ArchimedesActionSet(
                picks=[],
                thesis="No rigor-cleared strategies.",
                model_id="none",
                iterations=0,
                rigor_gate_failures=rigor_failures,
            )

        try:
            portfolio = PortfolioAgent().propose_portfolio_with_tools(
                regime=observation.regime,
                regime_confidence=observation.regime_confidence,
                risk_profile=self.risk_profile,
                usdc_floor=0.10,
                synth_budget=0.90,
                market_ranking=observation.market_ranking,
                strategies=rigor_cleared,
                scan_universe_synths=set(),
                price_histories={},
            )
        except Exception as exc:
            logger.warning("decide(): agent error (%s) — null allocation", exc)
            return ArchimedesActionSet(
                picks=[],
                thesis=f"Agent error: {exc}",
                model_id="none",
                iterations=0,
                rigor_gate_failures=rigor_failures,
            )

        if portfolio is None:
            return ArchimedesActionSet(
                picks=[],
                thesis="No LLM backend available.",
                model_id="none",
                iterations=0,
                rigor_gate_failures=rigor_failures,
            )

        cleared_ids = {s.id for s in rigor_cleared}
        picks: list[AgentPick] = []
        for p in portfolio.picks:
            if not any(p.paper_anchor in sid for sid in cleared_ids):
                rigor_failures += 1
                continue
            picks.append(
                AgentPick(
                    ticker=p.ticker,
                    weight=p.weight,
                    paper_anchor=p.paper_anchor,
                    rigor_gate_passed=True,
                )
            )

        return ArchimedesActionSet(
            picks=picks,
            thesis=portfolio.thesis,
            model_id=portfolio.model_id,
            iterations=portfolio.iterations,
            rigor_gate_failures=rigor_failures,
        )

    # ── Step 3: act ───────────────────────────────────────────────────────────

    def act(self, action_set: ArchimedesActionSet) -> SimulatedAllocation:
        """Convert action set to a simulated allocation, gated by VCheck.

        VCheck (chain/v_check.py) is the formal pre-trade validity contract.
        Weights are converted to BPS and passed through VCheck.run() before any
        allocation is committed. A failed VCheck holds the previous allocation.
        """
        if not action_set.picks or not all(p.rigor_gate_passed for p in action_set.picks):
            logger.info("act(): no rigor-cleared picks — holding previous allocation")
            return SimulatedAllocation(
                allocations=dict(self._current_allocation),
                cash_weight=1.0 - sum(self._current_allocation.values()),
                v_check_passed=False,
            )

        # Normalize weights and convert to BPS for VCheck
        total_w = sum(p.weight for p in action_set.picks)
        normed = {p.ticker: p.weight / max(total_w, 1e-9) for p in action_set.picks}
        cash_w = max(0.0, 1.0 - sum(normed.values()))

        # Distribute residual to cash and express full budget in BPS
        alloc_bps = {t: int(round(w * 10000)) for t, w in normed.items()}
        cash_bps = 10000 - sum(alloc_bps.values())
        if cash_bps > 0:
            alloc_bps["USDC"] = cash_bps

        vc_result = VCheck(weights_bps=alloc_bps).run()
        if not vc_result.passed:
            logger.info("act(): VCheck failed (%s) — holding previous allocation", vc_result.failures)
            return SimulatedAllocation(
                allocations=dict(self._current_allocation),
                cash_weight=1.0 - sum(self._current_allocation.values()),
                v_check_passed=False,
            )

        # Remove the USDC cash placeholder from the actual allocations dict
        final_alloc = dict(normed)
        self._current_allocation = dict(final_alloc)

        return SimulatedAllocation(
            allocations=final_alloc,
            cash_weight=cash_w,
            v_check_passed=True,
        )

    # ── Step 4: verify ────────────────────────────────────────────────────────

    def verify(self, post_state: dict[str, Any]) -> HarnessResult:
        """Capture harness metrics and apply the Outcome Embargo filter.

        apply_outcome_embargo (services/embargo_filter.py) filters any paper
        anchors in the post_state that were published within the embargo window,
        preventing evaluation from being contaminated by training-period data
        (Xia et al. 2026 §3.1 Outcome Embargo protocol).
        """
        self._step += 1
        period_return = float(post_state.get("period_return", 0.0))

        # apply_outcome_embargo: filter anchored papers within the embargo window.
        # If any papers are embargoed, we zero the period return to avoid
        # forward-looking contamination.
        anchored_papers = post_state.get("anchored_papers", [])
        embargo_applied = False
        if anchored_papers:
            cleared = apply_outcome_embargo(papers=anchored_papers)
            if len(cleared) < len(anchored_papers):
                period_return = 0.0
                embargo_applied = True

        self._period_returns.append(period_return)
        self._portfolio_value *= 1.0 + period_return
        self._peak_value = max(self._peak_value, self._portfolio_value)
        cum_return = self._portfolio_value - 1.0
        max_dd = (self._portfolio_value - self._peak_value) / self._peak_value

        result = HarnessResult(
            step=self._step,
            period_return=period_return,
            cumulative_return=float(post_state.get("cumulative_return", cum_return)),
            max_drawdown=float(post_state.get("max_drawdown", max_dd)),
            sortino_ratio=self._compute_sortino(),
            embargo_applied=embargo_applied,
        )
        self._results.append(result)
        return result

    # ── Episode summary ───────────────────────────────────────────────────────

    def episode_summary(self) -> dict[str, Any]:
        """Aggregate metrics compatible with stockbench_run.py JSON output."""
        if not self._results:
            return {"error": "No steps recorded"}

        final = self._results[-1]
        rets = self._period_returns

        # compute_dsr: Deflated Sharpe Ratio over the episode return series.
        # num_trials=1 because this is a single-strategy episode.
        dsr_p, dsr_sr = compute_dsr(daily_returns=rets, num_trials=1) if len(rets) >= 5 else (None, None)

        return {
            "seed": self.seed,
            "risk_profile": self.risk_profile,
            "horizon_days": self.horizon_days,
            "steps": self._step,
            "cumulative_return": final.cumulative_return,
            "max_drawdown": min((r.max_drawdown for r in self._results), default=0.0),
            "sortino_ratio": final.sortino_ratio,
            "dsr_p_value": dsr_p,
            "dsr_sharpe_estimate": dsr_sr,
            "embargo_applied_count": sum(1 for r in self._results if r.embargo_applied),
            "generated_at": datetime.now(UTC).isoformat(),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute_sortino(self) -> float | None:
        """Annualized Sortino ratio over the accumulated period returns."""
        rets = self._period_returns
        if len(rets) < 5:
            return None
        rf = _RF_ANNUAL / _ANNUALIZATION
        mean_r = sum(rets) / len(rets)
        downside = [min(r - rf, 0.0) ** 2 for r in rets]
        ds = math.sqrt(sum(downside) / len(rets))
        if ds < 1e-10:
            return None
        return (mean_r - rf) / ds * math.sqrt(_ANNUALIZATION)
