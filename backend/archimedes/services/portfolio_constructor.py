"""Regime- and consensus-throttled portfolio construction.

Implements ``IPortfolioConstructor``. The job of this module is to take the
runner's raw aggregated target weights and *throttle* exposure by two
orthogonal signals:

1. The exogenous market regime (``RegimeClassification``) — what the *market*
   is doing (VIX / momentum / spreads).
2. The endogenous ensemble consensus (``EnsembleConsensus``) — how decisive the
   *strategy ensemble* itself is (the fraction of flat signals).

Both shrink risk-asset exposure and move the freed mass into the USDC safe
asset. The two are kept distinct on purpose (issue #659): one is exogenous, the
other endogenous; multiplying them gives a single position scale in [0, 1].

Sizing basis — regime-conditional Kelly sizing:
  - Lo (2002), "The Statistics of Sharpe Ratios", Financial Analysts Journal.
  - López de Prado (2018), *Advances in Financial Machine Learning*, §11
    (Dangers of Backtesting / bet sizing). Risk is scaled down, not levered up,
    when conviction (regime confidence, ensemble agreement) is weak.
"""

from __future__ import annotations

from archimedes.interfaces.math import IPortfolioConstructor
from archimedes.models.backtest import BacktestResult
from archimedes.models.portfolio import (
    Portfolio,
    RiskProfile,
    TargetAllocation,
)
from archimedes.models.regime import EnsembleConsensus, Regime, RegimeClassification
from archimedes.models.strategy import Strategy

# ── Named constants (NO magic numbers) ──────────────────────────────
# Sizing basis: regime-conditional Kelly sizing — Lo (2002),
# López de Prado (2018) §11. Risk exposure is throttled down when the
# market regime or the ensemble's conviction is weak.

SAFE_ASSET = "USDC"

# Per-regime exposure multiplier on risk assets. RISK_ON = full sizing;
# CRISIS = near-flat (flight to safety).
REGIME_MULTIPLIER: dict[Regime, float] = {
    Regime.RISK_ON: 1.0,
    Regime.TRANSITION: 0.7,
    Regime.RISK_OFF: 0.4,
    Regime.CRISIS: 0.1,
}
# Conservative default when no regime classification is available (snapshot
# fetch failed or lacked VIX/MA signals — see agent_runner._classify_market_regime).
REGIME_MULTIPLIER_NONE = 0.7

# Confidence floor: even at confidence 0 the regime multiplier is not fully
# erased — low confidence halves the regime's effect rather than zeroing it.
# scale_within_regime = _CONF_BASE + _CONF_SLOPE * confidence.
_CONF_BASE = 0.5
_CONF_SLOPE = 0.5

# Ensemble-consensus throttle, driven by flat_pct (fraction of flat signals):
#   flat_pct < _FLAT_LOW            → 1.0  (decisive ensemble, no penalty)
#   _FLAT_LOW ≤ flat_pct ≤ _FLAT_HIGH → linear 1.0 → _CONSENSUS_FLOOR
#   flat_pct > _FLAT_HIGH           → _CONSENSUS_FLOOR (uncertain ensemble)
_FLAT_LOW = 0.30
_FLAT_HIGH = 0.60
_CONSENSUS_FLOOR = 0.6
_FLAT_SPAN = _FLAT_HIGH - _FLAT_LOW  # 0.30
_CONSENSUS_DROP = 1.0 - _CONSENSUS_FLOOR  # 0.4


class PortfolioConstructor(IPortfolioConstructor):
    """Throttles aggregated target weights by market regime + ensemble consensus."""

    def compute_position_scale(
        self,
        regime: RegimeClassification | None,
        ensemble_consensus: EnsembleConsensus | None,
    ) -> float:
        """Combine regime + ensemble consensus into a single risk-asset scale.

        PURE. Returns a multiplier in [0.0, 1.0] applied to every non-USDC
        weight; the freed mass moves to USDC.

        regime_mult:
          - regime is None → ``REGIME_MULTIPLIER_NONE`` (conservative default).
          - else ``REGIME_MULTIPLIER[regime] * (0.5 + 0.5 * confidence)`` — low
            confidence reduces sizing *within* a regime.
        consensus_mult (from flat_pct):
          - None → 1.0 (no penalty).
          - < 0.30 → 1.0; 0.30–0.60 → linear 1.0→0.6; > 0.60 → 0.6.
        """
        if regime is None:
            regime_mult = REGIME_MULTIPLIER_NONE
        else:
            confidence_factor = _CONF_BASE + _CONF_SLOPE * regime.confidence
            regime_mult = REGIME_MULTIPLIER[regime.regime] * confidence_factor

        if ensemble_consensus is None:
            consensus_mult = 1.0
        else:
            flat_pct = ensemble_consensus.flat_pct
            if flat_pct < _FLAT_LOW:
                consensus_mult = 1.0
            elif flat_pct > _FLAT_HIGH:
                consensus_mult = _CONSENSUS_FLOOR
            else:
                consensus_mult = 1.0 - (flat_pct - _FLAT_LOW) / _FLAT_SPAN * _CONSENSUS_DROP

        return max(0.0, min(1.0, regime_mult * consensus_mult))

    def construct(
        self,
        risk_profile: RiskProfile,  # noqa: ARG002 — IPortfolioConstructor signature; base_weights path doesn't re-derive by profile
        strategies: list[Strategy],
        backtest_results: dict[str, BacktestResult],
        regime: RegimeClassification | None,
        current_portfolio: Portfolio | None = None,  # noqa: ARG002 — Protocol signature; sizing is stateless wrt current holdings
        ensemble_consensus: EnsembleConsensus | None = None,
        *,
        base_weights: dict[str, float] | None = None,
    ) -> list[TargetAllocation]:
        """Scale raw target weights by the regime/consensus position scale.

        The returned weights are authoritative; the on-chain ``token_address``
        for each symbol is resolved by the caller (the runner attaches
        addresses via ``_weights_to_targets``), so allocations are emitted with
        ``token_address=""`` and ``strategy_ids=[]``.
        """
        raw_weights = base_weights if base_weights is not None else self._fallback_weights(strategies, backtest_results)

        scale = self.compute_position_scale(regime, ensemble_consensus)

        # Shrink every non-USDC weight by `scale`; the freed mass moves to USDC.
        scaled: dict[str, float] = {}
        freed_mass = 0.0
        usdc_weight = 0.0
        for symbol, weight in raw_weights.items():
            if symbol == SAFE_ASSET:
                usdc_weight += weight
                continue
            new_weight = weight * scale
            scaled[symbol] = new_weight
            freed_mass += weight - new_weight

        scaled[SAFE_ASSET] = usdc_weight + freed_mass

        # Renormalize so weights sum to 1.0 (guard divide-by-zero).
        total = sum(scaled.values())
        if total > 0:
            scaled = {sym: w / total for sym, w in scaled.items()}

        return [
            TargetAllocation(symbol=symbol, token_address="", weight=weight, strategy_ids=[])
            for symbol, weight in scaled.items()
        ]

    def score_strategy(
        self,
        strategy: Strategy,  # noqa: ARG002 — IPortfolioConstructor signature; score derives from the backtest result
        result: BacktestResult,
        risk_profile: RiskProfile,  # noqa: ARG002 — Protocol signature; DSR/Sharpe scoring is profile-agnostic
    ) -> float:
        """Score a strategy for ranking. Higher = better fit.

        Prefers the Deflated Sharpe Ratio (selection-bias-corrected) when the
        backtest carries it; otherwise falls back to the raw Sharpe.
        """
        if result.deflated_sharpe_ratio is not None:
            return result.deflated_sharpe_ratio
        return result.sharpe_ratio

    # ── Fallback weight derivation (no production caller uses this path) ──

    def _fallback_weights(
        self,
        strategies: list[Strategy],
        backtest_results: dict[str, BacktestResult],
    ) -> dict[str, float]:
        """Minimal score-ranked, normalized weights when ``base_weights`` is absent.

        Deliberately simple: rank strategies by ``score_strategy`` over their
        backtest result and normalize the positive scores into per-strategy
        weights keyed by ``strategy.id``. No production call site exercises this
        — it exists so ``construct`` never crashes when called without
        ``base_weights``.
        """
        scores: dict[str, float] = {}
        for strat in strategies:
            result = backtest_results.get(strat.id)
            if result is None:
                continue
            score = self.score_strategy(strat, result, RiskProfile.MODERATE)
            if score > 0:
                scores[strat.id] = score

        total = sum(scores.values())
        if total <= 0:
            # Nothing rankable → park everything in the safe asset.
            return {SAFE_ASSET: 1.0}
        return {sid: score / total for sid, score in scores.items()}
