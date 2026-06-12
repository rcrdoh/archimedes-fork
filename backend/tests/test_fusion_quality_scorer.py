"""Tests for the FusionQualityScorer multi-dimensional fusion-scoring framework.

Hermetic: numpy only, no network/DB/Redis/Anthropic/Arc RPC. Exercises each of
the six fusion dimensions, the score_all aggregation, generate_fusion_report
threshold behavior, and degenerate-input handling (N<2, zero-variance,
length-mismatch) which must never raise.

Owner: Önder (math lane).
"""

from __future__ import annotations

import math

import numpy as np
from archimedes.services.fusion_evaluator import (
    FusionQualityScorer,
    generate_fusion_report,
    score_correlation_stability,
    score_diversification_benefit,
    score_economic_sense,
    score_parameter_stability,
    score_tail_hedge,
    score_turnover_interaction,
)


# ─── Diversification benefit ─────────────────────────────────────────


def test_diversification_low_for_perfectly_correlated_pair():
    """Two identical (perfectly correlated) strategies → minimal diversification.

    N_eff collapses toward 1, so N_eff/N → 1/2 for N=2 (the single-factor floor).
    """
    s = list(np.random.default_rng(0).normal(0.001, 0.01, 300))
    score = score_diversification_benefit({"a": s, "b": list(s)})
    # Single dominant factor → N_eff ≈ 1 → score ≈ 1/N = 0.5 for N=2.
    assert np.isclose(score, 0.5, atol=0.05), f"perfectly correlated pair should collapse to 1/N, got {score}"


def test_diversification_high_for_independent_strategies():
    """Independent strategies span independent risk directions → high score."""
    rng = np.random.default_rng(1)
    m = {f"s{i}": list(rng.normal(0.0, 0.01, 600)) for i in range(6)}
    score = score_diversification_benefit(m)
    assert score > 0.8, f"independent strategies should diversify well, got {score}"


def test_diversification_independent_beats_correlated():
    """A diversified set must score strictly above a redundant (correlated) one."""
    rng = np.random.default_rng(2)
    base = rng.normal(0.0, 0.01, 400)
    # Correlated set: each is base + tiny idiosyncratic noise.
    corr_set = {f"c{i}": list(base + rng.normal(0, 0.0005, 400)) for i in range(4)}
    indep_set = {f"i{i}": list(rng.normal(0.0, 0.01, 400)) for i in range(4)}
    assert score_diversification_benefit(indep_set) > score_diversification_benefit(corr_set)


# ─── Correlation stability ───────────────────────────────────────────


def test_correlation_stability_high_for_stationary_series():
    """Stationary jointly-correlated series → stable correlation across halves."""
    rng = np.random.default_rng(3)
    common = rng.normal(0.0, 0.01, 800)
    a = common + rng.normal(0, 0.003, 800)
    b = common + rng.normal(0, 0.003, 800)
    score = score_correlation_stability({"a": list(a), "b": list(b)})
    assert not math.isnan(score)
    assert score > 0.7, f"stationary pair should be correlation-stable, got {score}"


def test_correlation_stability_low_for_regime_shifting_series():
    """A correlation that flips sign between halves → low stability score."""
    rng = np.random.default_rng(4)
    n = 400
    common_early = rng.normal(0.0, 0.01, n)
    common_late = rng.normal(0.0, 0.01, n)
    # First half: positively correlated; second half: anti-correlated.
    a = np.concatenate([common_early, common_late])
    b = np.concatenate([common_early, -common_late])
    score = score_correlation_stability({"a": list(a), "b": list(b)})
    stable = score_correlation_stability(
        {"x": list(np.concatenate([common_early, common_late])), "y": list(np.concatenate([common_early, common_late]))}
    )
    assert score < stable, "regime-shifting pair must be less stable than a stationary pair"


# ─── Tail hedge ──────────────────────────────────────────────────────


def test_tail_hedge_reduces_cvar_for_negatively_correlated_pair():
    """Negatively-correlated strategies hedge each other's tails → high score."""
    rng = np.random.default_rng(5)
    shock = rng.normal(0.0, 0.02, 600)
    a = shock + rng.normal(0.0005, 0.005, 600)
    b = -shock + rng.normal(0.0005, 0.005, 600)  # opposite tail exposure
    score = score_tail_hedge({"a": list(a), "b": list(b)})
    assert not math.isnan(score)
    assert score > 0.3, f"negatively-correlated pair should hedge tails, got {score}"


def test_tail_hedge_low_for_identical_strategies():
    """Identical strategies share the same tail → little/no hedging benefit."""
    s = list(np.random.default_rng(6).normal(0.0, 0.02, 400))
    score = score_tail_hedge({"a": s, "b": list(s)})
    # Equal-weight of two identical series == the series itself → CVaR unchanged.
    assert score == 0.0 or score < 0.05


# ─── Turnover interaction ────────────────────────────────────────────


def test_turnover_high_for_aligned_signals():
    """Strategies that almost always agree on direction → high agreement score."""
    signals = {
        "a": [1.0, 1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0],
        "b": [1.0, 1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0],
    }
    assert score_turnover_interaction(signals) == 1.0


def test_turnover_low_for_opposing_signals():
    """Always-opposing strategies → maximal churn → score 0."""
    signals = {
        "a": [1.0, 1.0, 1.0, 1.0, -1.0, -1.0],
        "b": [-1.0, -1.0, -1.0, -1.0, 1.0, 1.0],
    }
    assert score_turnover_interaction(signals) == 0.0


# ─── Parameter stability ─────────────────────────────────────────────


def test_parameter_stability_high_for_flat_response():
    """Near-constant metric under perturbation → robust (score → 1)."""
    metrics = [1.50, 1.49, 1.51, 1.50, 1.50]
    score = score_parameter_stability(metrics)
    assert score > 0.95, f"flat response should be robust, got {score}"


def test_parameter_stability_low_for_volatile_response():
    """Wildly swinging metric under perturbation → fragile (low score)."""
    metrics = [2.0, 0.1, 1.8, 0.2, 1.9, 0.05]
    score = score_parameter_stability(metrics)
    assert score < 0.5, f"volatile response should be fragile, got {score}"


# ─── Economic sense (regime diversity) ───────────────────────────────


def test_economic_sense_full_diversity():
    """All-distinct regime tags → diversity 1.0."""
    assert score_economic_sense(["bull", "bear", "neutral"]) == 1.0


def test_economic_sense_no_diversity():
    """All-identical regime tags → diversity 1/N."""
    assert score_economic_sense(["bull", "bull", "bull", "bull"]) == 0.25


def test_economic_sense_normalizes_and_ignores_blanks():
    """Tags are case/space-normalized; blanks ignored."""
    # "Bull", " bull " collapse to one regime; "" is dropped → 1 unique / 3 total.
    assert score_economic_sense(["Bull", " bull ", "BULL", ""]) == 1.0 / 3.0


# ─── score_all aggregation ───────────────────────────────────────────


def test_score_all_aggregates_present_dimensions():
    """score_all returns all computed dimensions plus a finite fusion_quality."""
    rng = np.random.default_rng(7)
    m = {f"s{i}": list(rng.normal(0.0005, 0.01, 500)) for i in range(4)}
    scorer = FusionQualityScorer()
    scores = scorer.score_all(
        m,
        perturbation_metrics=[1.5, 1.48, 1.52, 1.5],
        regime_tags=["bull", "bear", "neutral", "bull"],
    )
    assert "fusion_quality" in scores
    assert 0.0 <= scores["fusion_quality"] <= 1.0
    for dim in (
        "correlation_stability",
        "diversification_benefit",
        "tail_hedge",
        "turnover_interaction",
        "parameter_stability",
        "economic_sense",
    ):
        assert dim in scores


def test_score_all_skips_missing_dimensions_without_crash():
    """Omitting perturbation + regime inputs drops those dims; aggregate stays finite."""
    rng = np.random.default_rng(8)
    m = {f"s{i}": list(rng.normal(0.0, 0.01, 400)) for i in range(3)}
    scores = FusionQualityScorer().score_all(m)
    assert "parameter_stability" not in scores
    assert "economic_sense" not in scores
    assert np.isfinite(scores["fusion_quality"])


def test_score_all_nan_when_no_data():
    """No usable inputs → fusion_quality is NaN, no exception."""
    scores = FusionQualityScorer().score_all(None)
    assert math.isnan(scores["fusion_quality"])


# ─── generate_fusion_report threshold behavior ───────────────────────


def test_report_recommends_above_threshold():
    scores = {"diversification_benefit": 0.9, "tail_hedge": 0.8, "fusion_quality": 0.85}
    report = generate_fusion_report(scores, threshold=0.7)
    assert report["recommended"] is True
    assert report["fusion_quality"] == 0.85
    assert "diversification_benefit" in report["dimension_breakdown"]
    assert isinstance(report["rationale"], str) and report["rationale"]


def test_report_rejects_below_threshold():
    scores = {"diversification_benefit": 0.4, "tail_hedge": 0.3, "fusion_quality": 0.35}
    report = generate_fusion_report(scores, threshold=0.7)
    assert report["recommended"] is False
    assert "Do not fuse" in report["rationale"]


def test_report_handles_nan_fusion_quality():
    report = generate_fusion_report({"fusion_quality": float("nan")}, threshold=0.7)
    assert report["recommended"] is False
    assert math.isnan(report["fusion_quality"])
    assert "Insufficient data" in report["rationale"]


# ─── Degenerate inputs never raise ───────────────────────────────────


def test_single_strategy_input_does_not_crash():
    """N<2 in every dimension → NaN, never an exception."""
    one = {"only": list(np.random.default_rng(9).normal(0.0, 0.01, 200))}
    assert math.isnan(score_correlation_stability(one))
    assert math.isnan(score_diversification_benefit(one))
    assert math.isnan(score_tail_hedge(one))
    assert math.isnan(score_turnover_interaction(one))
    scores = FusionQualityScorer().score_all(one)
    # Single-strategy returns matrix → all return-driven dims NaN → aggregate NaN.
    assert math.isnan(scores["fusion_quality"])


def test_length_mismatch_truncates_to_min():
    """Series of unequal length are truncated to the shortest, not crashed."""
    m = {"a": list(np.random.default_rng(10).normal(0.0, 0.01, 500)), "b": [0.01, -0.02, 0.03, 0.0, 0.01]}
    # Should run without error and yield a finite-or-nan float (not raise).
    score = score_diversification_benefit(m)
    assert isinstance(score, float)


def test_zero_variance_series_handled():
    """A constant series alongside a live one is dropped; degrades gracefully."""
    flat = [0.001] * 200
    live = list(np.random.default_rng(11).normal(0.0, 0.01, 200))
    # Only one non-constant row survives → NaN, no crash.
    assert math.isnan(score_diversification_benefit({"flat": flat, "live": live}))


def test_parameter_stability_degenerate_inputs():
    """Empty → NaN; single observation → neutral 0.5; never raises."""
    assert math.isnan(score_parameter_stability([]))
    assert score_parameter_stability([1.5]) == 0.5
    # Mean ~0 → CV undefined → neutral 0.5.
    assert score_parameter_stability([1.0, -1.0]) == 0.5


def test_economic_sense_empty_is_nan():
    assert math.isnan(score_economic_sense([]))
    assert math.isnan(score_economic_sense(["", "  "]))
