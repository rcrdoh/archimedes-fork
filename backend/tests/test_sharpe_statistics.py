"""Tests for Lo (2002) Sharpe-ratio corrections.

Hermetic, pure-math tests -- no mocks, no I/O, no DB. Random data uses a seeded
``numpy.random.default_rng`` so results are deterministic across runs.

Reference: Lo, A. W. (2002). "The Statistics of Sharpe Ratios." FAJ 58(4).
"""

from __future__ import annotations

import math

import numpy as np
from archimedes.services.sharpe_statistics import (
    autocorr_adjusted_annualized_sharpe,
    iid_sharpe_stderr,
    newey_west_sharpe_stderr,
    sharpe_ratio,
)


def _ar1(n: int, phi: float, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """Generate a zero-mean AR(1) series x_t = phi*x_{t-1} + eps_t."""
    eps = rng.normal(0.0, sigma, size=n)
    x = np.empty(n)
    x[0] = eps[0]
    for t in range(1, n):
        x[t] = phi * x[t - 1] + eps[t]
    return x


# --------------------------------------------------------------------------- #
# sharpe_ratio
# --------------------------------------------------------------------------- #
def test_sharpe_ratio_hand_computed() -> None:
    r = np.array([0.01, 0.02, 0.03, 0.04])
    # mean = 0.025; std(ddof=1) of arithmetic sequence step 0.01 over 4 pts:
    expected = np.mean(r) / np.std(r, ddof=1)
    assert math.isclose(sharpe_ratio(r), expected, rel_tol=1e-12)


def test_sharpe_ratio_with_rf() -> None:
    r = np.array([0.05, 0.05, 0.10, 0.00])
    rf = 0.01
    excess = r - rf
    expected = np.mean(excess) / np.std(excess, ddof=1)
    assert math.isclose(sharpe_ratio(r, rf=rf), expected, rel_tol=1e-12)


def test_sharpe_ratio_degenerate_inputs() -> None:
    assert math.isnan(sharpe_ratio([]))
    assert math.isnan(sharpe_ratio([0.01]))  # single obs
    assert math.isnan(sharpe_ratio([0.02, 0.02, 0.02]))  # zero variance


# --------------------------------------------------------------------------- #
# iid_sharpe_stderr  (Lo eq. 6)
# --------------------------------------------------------------------------- #
def test_iid_sharpe_stderr_closed_form() -> None:
    sr, n = 0.5, 100
    expected = math.sqrt((1.0 + 0.5 * sr**2) / n)
    assert math.isclose(iid_sharpe_stderr(sr, n), expected, rel_tol=1e-12)


def test_iid_sharpe_stderr_zero_sharpe() -> None:
    # SR=0 -> sqrt(1/n)
    assert math.isclose(iid_sharpe_stderr(0.0, 144), 1.0 / 12.0, rel_tol=1e-12)


def test_iid_sharpe_stderr_degenerate() -> None:
    assert math.isnan(iid_sharpe_stderr(0.5, 0))
    assert math.isnan(iid_sharpe_stderr(float("nan"), 50))


# --------------------------------------------------------------------------- #
# autocorr_adjusted_annualized_sharpe  (Lo Proposition 2)
# --------------------------------------------------------------------------- #
def test_iid_returns_eta_approx_sqrt_q() -> None:
    rng = np.random.default_rng(42)
    r = rng.normal(0.001, 0.02, size=5000)
    q = 12
    out = autocorr_adjusted_annualized_sharpe(r, q)
    assert out["adjustment_valid"] is True
    # For IID returns autocorrelations vanish -> eta -> sqrt(q).
    assert math.isclose(out["eta"], math.sqrt(q), rel_tol=0.05)
    assert math.isclose(
        out["autocorr_adjusted_annualized"],
        out["naive_annualized"],
        rel_tol=0.05,
    )


def test_positive_autocorr_adjusted_strictly_below_naive() -> None:
    # Lo's central point: positive serial correlation -> naive overstates.
    rng = np.random.default_rng(7)
    r = 0.001 + _ar1(4000, phi=0.4, sigma=0.02, rng=rng)
    out = autocorr_adjusted_annualized_sharpe(r, q=12)
    assert out["adjustment_valid"] is True
    assert out["eta"] < math.sqrt(out["q"])
    assert out["autocorr_adjusted_annualized"] < out["naive_annualized"]
    # lag-1 autocorr should be clearly positive
    assert out["autocorrelations"][0] > 0.2


def test_negative_autocorr_adjusted_above_naive() -> None:
    rng = np.random.default_rng(11)
    r = 0.001 + _ar1(4000, phi=-0.4, sigma=0.02, rng=rng)
    out = autocorr_adjusted_annualized_sharpe(r, q=12)
    assert out["adjustment_valid"] is True
    assert out["eta"] > math.sqrt(out["q"])
    assert out["autocorr_adjusted_annualized"] > out["naive_annualized"]
    assert out["autocorrelations"][0] < -0.2


def test_adjustment_valid_flag_is_boolean_and_reachable() -> None:
    # Strong negative lag-1 autocorrelation in a tiny sample can push the
    # denominator <= 0, exercising the fallback branch.
    alt = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0], dtype=float) * 0.05 + 0.001
    out = autocorr_adjusted_annualized_sharpe(alt, q=4)
    assert isinstance(out["adjustment_valid"], bool)
    if not out["adjustment_valid"]:
        # fallback uses eta = sqrt(q)
        assert math.isclose(out["eta"], math.sqrt(out["q"]), rel_tol=1e-12)


def test_autocorr_dict_shape_and_keys() -> None:
    rng = np.random.default_rng(3)
    r = rng.normal(0.0, 0.01, size=300)
    q = 6
    out = autocorr_adjusted_annualized_sharpe(r, q)
    assert set(out) == {
        "per_period_sharpe",
        "naive_annualized",
        "autocorr_adjusted_annualized",
        "eta",
        "q",
        "autocorrelations",
        "adjustment_valid",
    }
    assert out["q"] == q
    assert len(out["autocorrelations"]) == q - 1


def test_autocorr_degenerate_inputs_dont_crash() -> None:
    for bad in ([], [0.01], [0.02, 0.02, 0.02]):
        out = autocorr_adjusted_annualized_sharpe(bad, q=12)
        assert math.isnan(out["per_period_sharpe"])
        assert isinstance(out["adjustment_valid"], bool)


# --------------------------------------------------------------------------- #
# newey_west_sharpe_stderr  (HAC, Bartlett kernel)
# --------------------------------------------------------------------------- #
def test_newey_west_positive_finite() -> None:
    rng = np.random.default_rng(1)
    r = rng.normal(0.001, 0.02, size=500)
    se = newey_west_sharpe_stderr(r)
    assert math.isfinite(se)
    assert se > 0.0


def test_newey_west_lags0_matches_iid_on_iid_data() -> None:
    # With lags=0 (heteroskedasticity-only) on IID-ish normal data the HAC SE
    # should be close to the IID closed-form SE.
    rng = np.random.default_rng(123)
    r = rng.normal(0.0008, 0.015, size=4000)
    nw = newey_west_sharpe_stderr(r, lags=0)
    iid = iid_sharpe_stderr(sharpe_ratio(r), n=r.size)
    assert math.isfinite(nw)
    assert math.isclose(nw, iid, rel_tol=0.10)


def test_newey_west_positive_autocorr_inflates_se() -> None:
    # HAC SE with lags should exceed the IID SE under positive autocorrelation.
    rng = np.random.default_rng(99)
    r = 0.001 + _ar1(3000, phi=0.5, sigma=0.02, rng=rng)
    nw = newey_west_sharpe_stderr(r, lags=10)
    iid = iid_sharpe_stderr(sharpe_ratio(r), n=r.size)
    assert nw > iid


def test_newey_west_degenerate_inputs_dont_crash() -> None:
    assert math.isnan(newey_west_sharpe_stderr([]))
    assert math.isnan(newey_west_sharpe_stderr([0.01]))  # single obs
    assert math.isnan(newey_west_sharpe_stderr([0.02, 0.02, 0.02]))  # zero var
