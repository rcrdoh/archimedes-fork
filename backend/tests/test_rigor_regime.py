"""Hermetic tests for regime-conditional rigor analysis.

Covers classify_regimes, regime_conditional_sharpe, regime_robustness_score,
and regime_conditional_dsr. Numpy-only, deterministic via default_rng(SEED).
No .env / Redis / DB / network dependence.
"""

from __future__ import annotations

import numpy as np
from archimedes.services.rigor_evaluator import (
    classify_regimes,
    regime_conditional_dsr,
    regime_conditional_sharpe,
    regime_robustness_score,
)

SEED = 20260612
_VOL_WINDOW = 21


def _regime_shift_series(n_half: int = 250, seed: int = SEED) -> np.ndarray:
    """First half low-vol, second half high-vol — a clear regime shift."""
    rng = np.random.default_rng(seed)
    calm = rng.normal(loc=0.0005, scale=0.004, size=n_half)
    stressed = rng.normal(loc=-0.0003, scale=0.025, size=n_half)
    return np.concatenate([calm, stressed])


# ─── classify_regimes ────────────────────────────────────────────────


def test_classify_regimes_output_length_matches_input():
    market = _regime_shift_series()
    labels = classify_regimes(market, vol_window=_VOL_WINDOW, n_regimes=2)
    assert labels.shape == (market.shape[0],)


def test_classify_regimes_leading_bars_unclassified():
    market = _regime_shift_series()
    labels = classify_regimes(market, vol_window=_VOL_WINDOW, n_regimes=2)
    # The first vol_window bars lack a full trailing window → label -1.
    assert np.all(labels[:_VOL_WINDOW] == -1)


def test_classify_regimes_high_vol_period_gets_stressed_label():
    market = _regime_shift_series(n_half=250)
    labels = classify_regimes(market, vol_window=_VOL_WINDOW, n_regimes=2)
    # Deep into the high-vol second half, labels should be predominantly 1 (stressed).
    second_half_tail = labels[400:]
    classified = second_half_tail[second_half_tail != -1]
    assert classified.size > 0
    assert np.mean(classified == 1) > 0.8


def test_classify_regimes_calm_period_gets_calm_label():
    market = _regime_shift_series(n_half=250)
    labels = classify_regimes(market, vol_window=_VOL_WINDOW, n_regimes=2)
    # Deep into the low-vol first half (past the warmup), labels should be 0 (calm).
    first_half_mid = labels[100:230]
    classified = first_half_mid[first_half_mid != -1]
    assert classified.size > 0
    assert np.mean(classified == 0) > 0.8


def test_classify_regimes_n_regimes_2_label_set():
    market = _regime_shift_series()
    labels = classify_regimes(market, vol_window=_VOL_WINDOW, n_regimes=2)
    assert set(np.unique(labels)).issubset({-1, 0, 1})
    # All three should actually appear given the regime shift.
    assert set(np.unique(labels)) == {-1, 0, 1}


def test_classify_regimes_constant_vol_degenerate_no_crash():
    # A perfectly linear-trend series has constant per-window std → degenerate
    # quantile edges. Should not crash; collapses into a single bucket.
    market = np.full(200, 0.001)
    labels = classify_regimes(market, vol_window=_VOL_WINDOW, n_regimes=2)
    assert labels.shape == (200,)
    classified = labels[labels != -1]
    # Zero-variance windows → roll_vol == 0 everywhere; one bucket (0).
    assert set(np.unique(classified)).issubset({0, 1})


def test_classify_regimes_empty_input_returns_empty():
    labels = classify_regimes([], vol_window=_VOL_WINDOW, n_regimes=2)
    assert labels.shape == (0,)


def test_classify_regimes_too_short_all_unclassified():
    market = np.array([0.001, -0.002, 0.0015])  # shorter than vol_window
    labels = classify_regimes(market, vol_window=_VOL_WINDOW, n_regimes=2)
    assert np.all(labels == -1)


# ─── regime_conditional_sharpe ───────────────────────────────────────


def test_regime_conditional_sharpe_higher_in_strong_regime():
    rng = np.random.default_rng(SEED)
    labels = np.array([0] * 100 + [1] * 100, dtype=int)
    strat = np.concatenate(
        [
            rng.normal(loc=0.002, scale=0.005, size=100),  # strong in regime 0
            rng.normal(loc=-0.0005, scale=0.005, size=100),  # weak in regime 1
        ]
    )
    out = regime_conditional_sharpe(strat, labels)
    assert 0 in out and 1 in out
    assert out[0]["sharpe"] is not None
    assert out[1]["sharpe"] is not None
    assert out[0]["sharpe"] > out[1]["sharpe"]


def test_regime_conditional_sharpe_short_regime_none_sharpe():
    strat = np.array([0.001, 0.002, -0.001, 0.0015, 0.0])
    labels = np.array([0, 0, 0, 0, 1], dtype=int)  # regime 1 has 1 day
    out = regime_conditional_sharpe(strat, labels)
    assert out[1]["sharpe"] is None
    assert out[1]["n_days"] == 1


def test_regime_conditional_sharpe_counts_sum_correctly():
    strat = np.array([0.001, -0.002, 0.003, -0.001, 0.002, 0.0005])
    labels = np.array([0, 0, 1, 1, 1, -1], dtype=int)
    out = regime_conditional_sharpe(strat, labels)
    total_classified = sum(v["n_days"] for v in out.values())
    assert total_classified == int(np.sum(labels != -1))
    assert out[0]["n_days"] == 2
    assert out[1]["n_days"] == 3


def test_regime_conditional_sharpe_truncates_to_min_length():
    strat = np.array([0.001, 0.002, -0.001, 0.0015])
    labels = np.array([0, 0, 1, 1, 1, 1], dtype=int)  # longer than strat
    out = regime_conditional_sharpe(strat, labels)
    total = sum(v["n_days"] for v in out.values())
    assert total == 4  # truncated to len(strat)


def test_regime_conditional_sharpe_all_unclassified_empty():
    strat = np.array([0.001, 0.002, -0.001])
    labels = np.array([-1, -1, -1], dtype=int)
    assert regime_conditional_sharpe(strat, labels) == {}


# ─── regime_robustness_score ─────────────────────────────────────────


def test_regime_robustness_single_regime_strategy_not_robust():
    rng = np.random.default_rng(SEED)
    labels = np.array([0] * 100 + [1] * 100, dtype=int)
    strat = np.concatenate(
        [
            rng.normal(loc=0.003, scale=0.005, size=100),  # strong in 0
            rng.normal(loc=-0.002, scale=0.006, size=100),  # negative in 1
        ]
    )
    score = regime_robustness_score(strat, labels)
    assert score["robust"] is False
    assert score["min_regime_sharpe"] < 0
    assert score["consistency"] == 0.0  # min/max with negative min → clamped to 0


def test_regime_robustness_all_positive_strategy_robust():
    rng = np.random.default_rng(SEED + 1)
    labels = np.array([0] * 120 + [1] * 120, dtype=int)
    strat = np.concatenate(
        [
            rng.normal(loc=0.0018, scale=0.005, size=120),  # positive in 0
            rng.normal(loc=0.0016, scale=0.005, size=120),  # positive in 1
        ]
    )
    score = regime_robustness_score(strat, labels)
    assert score["robust"] is True
    assert score["min_regime_sharpe"] > 0
    assert 0.0 <= score["consistency"] <= 1.0
    assert score["consistency"] > 0.5  # comparable Sharpes → high consistency


def test_regime_robustness_dispersion_computed():
    rng = np.random.default_rng(SEED + 2)
    labels = np.array([0] * 100 + [1] * 100, dtype=int)
    strat = np.concatenate(
        [
            rng.normal(loc=0.003, scale=0.005, size=100),
            rng.normal(loc=0.0005, scale=0.005, size=100),
        ]
    )
    score = regime_robustness_score(strat, labels)
    expected = score["max_regime_sharpe"] - score["min_regime_sharpe"]
    assert abs(score["sharpe_dispersion"] - round(expected, 6)) < 1e-6
    assert score["sharpe_dispersion"] >= 0


def test_regime_robustness_no_computable_regimes_sensible():
    # All unclassified → no per-regime sharpes computable.
    strat = np.array([0.001, 0.002, -0.001])
    labels = np.array([-1, -1, -1], dtype=int)
    score = regime_robustness_score(strat, labels)
    assert score["robust"] is False
    assert score["consistency"] == 0.0
    assert score["min_regime_sharpe"] is None
    assert score["sharpe_dispersion"] is None


# ─── regime_conditional_dsr ──────────────────────────────────────────


def test_regime_conditional_dsr_returns_per_regime_dict():
    rng = np.random.default_rng(SEED)
    labels = np.array([0] * 100 + [1] * 100, dtype=int)
    strat = np.concatenate(
        [
            rng.normal(loc=0.002, scale=0.005, size=100),
            rng.normal(loc=0.0008, scale=0.005, size=100),
        ]
    )
    out = regime_conditional_dsr(strat, labels, num_trials=5)
    assert set(out.keys()) == {0, 1}
    for v in out.values():
        assert "deflated_sharpe" in v
        assert "dsr_p_value" in v
        assert "n_days" in v
    assert out[0]["n_days"] == 100


def test_regime_conditional_dsr_too_short_regime_none():
    # Regime 1 has only 2 days → below compute_dsr's T < 4 guard → None.
    strat = np.array([0.001, -0.002, 0.003, -0.001, 0.002, 0.0005])
    labels = np.array([0, 0, 0, 0, 1, 1], dtype=int)
    out = regime_conditional_dsr(strat, labels)
    assert out[1]["deflated_sharpe"] is None
    assert out[1]["dsr_p_value"] is None
    assert out[1]["n_days"] == 2


def test_regime_conditional_dsr_empty_input():
    assert regime_conditional_dsr([], []) == {}
