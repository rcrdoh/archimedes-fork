"""Hermetic tests for the return-series IID / random-walk diagnostics.

Pure math: numpy ``default_rng`` with fixed seeds, no DB / network / env.
Synthetic series are sized and seeded so the asymptotic tests are decisive
and non-flaky.
"""

from __future__ import annotations

import numpy as np
from archimedes.services.return_diagnostics import (
    diagnose,
    ljung_box_test,
    runs_test,
    variance_ratio_test,
)


def _white_noise(n: int = 2000, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 0.01, size=n)


def _ar1(n: int = 2000, phi: float = 0.5, seed: int = 11) -> np.ndarray:
    """AR(1): x_t = phi * x_{t-1} + eps_t — positive serial correlation."""
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, 0.01, size=n)
    x = np.empty(n, dtype=np.float64)
    x[0] = eps[0]
    for t in range(1, n):
        x[t] = phi * x[t - 1] + eps[t]
    return x


def _trending(n: int = 2000, phi: float = 0.7, seed: int = 17) -> np.ndarray:
    """Strongly persistent series → VR > 1."""
    return _ar1(n=n, phi=phi, seed=seed)


def _mean_reverting(n: int = 2000, phi: float = -0.5, seed: int = 23) -> np.ndarray:
    """AR(1) with negative phi — alternating / mean-reverting → VR < 1."""
    return _ar1(n=n, phi=phi, seed=seed)


# --------------------------------------------------------------------------
# Ljung-Box
# --------------------------------------------------------------------------


def test_ljung_box_white_noise_does_not_reject():
    res = ljung_box_test(_white_noise(), lags=10)
    assert res["valid"] is True
    assert res["reject_iid"] is False
    assert res["p_value"] > 0.05
    assert len(res["autocorrelations"]) == 10


def test_ljung_box_ar1_rejects():
    res = ljung_box_test(_ar1(), lags=10)
    assert res["valid"] is True
    assert res["reject_iid"] is True
    assert res["p_value"] < 0.01
    # Lag-1 autocorrelation should be clearly positive for phi=0.5.
    assert res["autocorrelations"][0] > 0.3


def test_ljung_box_short_series_graceful():
    res = ljung_box_test([0.01, -0.02, 0.0], lags=10)
    assert res["valid"] is False
    assert "reason" in res
    assert np.isnan(res["statistic"])
    assert res["reject_iid"] is False


def test_ljung_box_invalid_lags():
    res = ljung_box_test(_white_noise(), lags=0)
    assert res["valid"] is False
    assert "lags" in res["reason"]


# --------------------------------------------------------------------------
# Variance ratio
# --------------------------------------------------------------------------


def test_variance_ratio_white_noise_near_one():
    res = variance_ratio_test(_white_noise(), q=2)
    assert res["valid"] is True
    assert res["reject_random_walk"] is False
    assert abs(res["variance_ratio"] - 1.0) < 0.1
    assert res["p_value"] > 0.05


def test_variance_ratio_ar1_significant():
    res = variance_ratio_test(_ar1(), q=2)
    assert res["valid"] is True
    assert res["reject_random_walk"] is True
    assert abs(res["z_statistic"]) > 2.0


def test_variance_ratio_trending_gt_one():
    res = variance_ratio_test(_trending(), q=4)
    assert res["valid"] is True
    assert res["variance_ratio"] > 1.0
    assert res["reject_random_walk"] is True


def test_variance_ratio_mean_reverting_lt_one():
    res = variance_ratio_test(_mean_reverting(), q=2)
    assert res["valid"] is True
    assert res["variance_ratio"] < 1.0
    assert res["reject_random_walk"] is True


def test_variance_ratio_invalid_q():
    res = variance_ratio_test(_white_noise(), q=1)
    assert res["valid"] is False
    assert "q" in res["reason"]


def test_variance_ratio_short_series_graceful():
    res = variance_ratio_test([0.01, -0.01, 0.02], q=2)
    assert res["valid"] is False
    assert np.isnan(res["variance_ratio"])
    assert res["reject_random_walk"] is False


# --------------------------------------------------------------------------
# Runs test
# --------------------------------------------------------------------------


def test_runs_white_noise_does_not_reject():
    res = runs_test(_white_noise())
    assert res["valid"] is True
    assert res["reject_randomness"] is False
    assert res["p_value"] > 0.05


def test_runs_alternating_sequence_flagged():
    # Deterministic +1/-1 alternation: maximal number of runs → very
    # significant positive z (far more runs than expected).
    alt = np.array([1.0, -1.0] * 50)
    res = runs_test(alt)
    assert res["valid"] is True
    assert res["reject_randomness"] is True
    assert res["z_statistic"] > 2.0
    assert res["n_runs"] == 100


def test_runs_trending_too_few_runs():
    # Long persistent series has fewer sign-runs than random → negative z.
    res = runs_test(_trending(phi=0.85, seed=31))
    assert res["valid"] is True
    assert res["reject_randomness"] is True
    assert res["z_statistic"] < 0.0


def test_runs_short_series_graceful():
    res = runs_test([0.01, -0.02])
    assert res["valid"] is False
    assert np.isnan(res["z_statistic"])
    assert res["reject_randomness"] is False


# --------------------------------------------------------------------------
# diagnose aggregation
# --------------------------------------------------------------------------


def test_diagnose_white_noise_not_violated():
    res = diagnose(_white_noise())
    assert res["iid_assumption_violated"] is False
    assert res["ljung_box"]["valid"] is True
    assert res["variance_ratio"]["valid"] is True
    assert res["runs"]["valid"] is True


def test_diagnose_ar1_violated():
    res = diagnose(_ar1())
    assert res["iid_assumption_violated"] is True


def test_diagnose_keys_present():
    res = diagnose(_white_noise())
    assert set(res.keys()) == {
        "ljung_box",
        "variance_ratio",
        "runs",
        "iid_assumption_violated",
    }


def test_diagnose_short_series_not_violated():
    # All sub-tests invalid → no spurious violation flag.
    res = diagnose([0.01, -0.02, 0.0])
    assert res["iid_assumption_violated"] is False
    assert res["ljung_box"]["valid"] is False
    assert res["variance_ratio"]["valid"] is False
    assert res["runs"]["valid"] is False
