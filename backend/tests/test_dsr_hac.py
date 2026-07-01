"""HAC (Newey–West) serial-correlation-robust Deflated Sharpe Ratio (#621 follow-up).

The classical Deflated Sharpe Ratio (Bailey & López de Prado 2014, *J. Portfolio
Management* 40(5)) uses the IID asymptotic variance of the Sharpe estimator. When
returns are serially dependent that standard error is invalid (Lo 2002, "The
Statistics of Sharpe Ratios", *FAJ* 58(4)): positive autocorrelation understates
it and inflates significance. The gate now uses the Newey & West (1987,
*Econometrica* 55(3)) heteroskedasticity- and autocorrelation-consistent (HAC)
long-run variance of the Sharpe *influence function*

    IF_t = z_t − (ŜR/2)(z_t² − 1),   z_t = (x_t − μ)/σ,

whose IID variance equals the Bailey-LdP term exactly, so the HAC form nests it.

These tests pin:
  1. nesting — HAC ≈ IID on serially independent returns;
  2. direction — positive autocorrelation widens the SE and lowers the DSR
     p-value (gate gets stricter); negative autocorrelation does the reverse;
  3. the Newey–West (1994) automatic bandwidth and the Bartlett-kernel PSD guarantee;
  4. edge cases and the run_rigor_gate integration surface.

Hermetic: no network, no database, no on-chain dependencies.
"""

from __future__ import annotations

import numpy as np
from archimedes.services._rigor_helpers import (
    _nw_auto_bandwidth,
    _sharpe_influence_lrv,
    compute_dsr,
    compute_dsr_hac_and_iid,
)
from archimedes.services.rigor_evaluator import run_rigor_gate

_RF_DAILY = 0.05 / 252


def _ar1(n: int, phi: float, mu: float, sigma: float, seed: int) -> np.ndarray:
    """AR(1) return series r_t = mu + phi·(r_{t-1} − mu) + eps_t, eps ~ N(0, sigma²).

    phi = 0 yields white noise (serially independent); phi > 0 is positively
    autocorrelated (persistent), phi < 0 is mean-reverting.
    """
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, sigma, size=n)
    r = np.empty(n)
    r[0] = mu + eps[0]
    for t in range(1, n):
        r[t] = mu + phi * (r[t - 1] - mu) + eps[t]
    return r


# ─── 1. Nesting: HAC reduces to the IID variance on independent returns ──


def test_hac_nests_iid_on_independent_returns():
    """White noise → autocovariance terms ≈ 0 → HAC p-value ≈ IID p-value."""
    r = _ar1(2000, phi=0.0, mu=0.0008, sigma=0.01, seed=7)
    _, p_iid = compute_dsr(r, num_trials=1)
    _, p_hac = compute_dsr(r, num_trials=1, hac_lags="auto")
    assert p_iid is not None and p_hac is not None
    assert abs(p_hac - p_iid) < 0.03


def test_lrv_at_zero_lag_matches_iid_variance():
    """At L=0 the HAC LRV is the empirical influence-function variance with no
    autocovariance terms; it must match the moment-based IID denom_sq to O(1/T)."""
    r = _ar1(2000, phi=0.0, mu=0.0008, sigma=0.01, seed=11)
    _, p_iid = compute_dsr(r, num_trials=1)
    _, p_l0 = compute_dsr(r, num_trials=1, hac_lags=0)
    assert p_iid is not None and p_l0 is not None
    assert abs(p_l0 - p_iid) < 0.02


# ─── 2. Direction: serial correlation moves the SE the right way ─────────


def test_positive_autocorrelation_tightens_gate():
    """Positive autocorrelation inflates the Newey–West long-run variance above
    the L=0 (IID) value — the core mechanism — so the SE widens, z shrinks, and
    the DSR p-value falls. Asserted at the variance level (seed-robust, free of
    the Φ(·)≈1 saturation ceiling) with the p-value direction as the corollary.
    """
    arr = _ar1(2000, phi=0.4, mu=0.0004, sigma=0.01, seed=3)
    sigma = float(arr.std(ddof=1))
    mean = float(arr.mean())
    sr = (mean - _RF_DAILY) / sigma
    g0 = _sharpe_influence_lrv(arr, sr, mean, sigma, 0)  # no autocovariance terms
    lrv = _sharpe_influence_lrv(arr, sr, mean, sigma, "auto")  # NW HAC
    assert g0 is not None and lrv is not None
    assert lrv > g0  # variance inflated → wider SE → stricter gate
    _, p_iid = compute_dsr(arr, num_trials=1)
    _, p_hac = compute_dsr(arr, num_trials=1, hac_lags="auto")
    assert p_hac < p_iid  # corollary: a positive-Sharpe series has z>0, so larger SE lowers Φ(z)


def test_negative_autocorrelation_loosens_gate():
    """Mean-reverting returns carry more independent information than T IID
    draws → long-run variance below the IID value → narrower SE → higher
    p-value. Asserted at the variance level, with the p-value as the corollary.
    """
    arr = _ar1(2000, phi=-0.4, mu=0.0007, sigma=0.01, seed=5)
    sigma = float(arr.std(ddof=1))
    mean = float(arr.mean())
    sr = (mean - _RF_DAILY) / sigma
    g0 = _sharpe_influence_lrv(arr, sr, mean, sigma, 0)
    lrv = _sharpe_influence_lrv(arr, sr, mean, sigma, "auto")
    assert g0 is not None and lrv is not None
    assert lrv < g0  # negative serial dependence deflates the long-run variance
    _, p_iid = compute_dsr(arr, num_trials=1)
    _, p_hac = compute_dsr(arr, num_trials=1, hac_lags="auto")
    assert p_hac > p_iid


# ─── 3. Newey–West (1994) bandwidth + Bartlett PSD guarantee ─────────────


def test_nw_auto_bandwidth():
    assert _nw_auto_bandwidth(252) == 4  # one trading year of daily bars
    assert _nw_auto_bandwidth(100) == 4
    assert _nw_auto_bandwidth(10) >= 1  # floored at 1
    assert _nw_auto_bandwidth(5000) >= _nw_auto_bandwidth(252)  # weakly increasing


def test_hac_lrv_is_positive_under_strong_autocorrelation():
    """The Bartlett kernel guarantees a non-negative long-run variance even at
    phi=0.8 (Newey & West 1987)."""
    arr = _ar1(500, phi=0.8, mu=0.0, sigma=0.01, seed=1)
    sigma = float(arr.std(ddof=1))
    mean = float(arr.mean())
    sr = (mean - _RF_DAILY) / sigma
    lrv = _sharpe_influence_lrv(arr, sr, mean, sigma, "auto")
    assert lrv is not None and lrv > 0.0


# ─── 4. Edge cases ───────────────────────────────────────────────────────


def test_lrv_none_for_short_series():
    assert _sharpe_influence_lrv(np.array([0.01, 0.02, 0.0]), 0.5, 0.01, 0.01, "auto") is None


def test_lrv_none_for_zero_sigma():
    assert _sharpe_influence_lrv(np.array([0.01] * 50), 0.5, 0.01, 0.0, "auto") is None


def test_hac_bandwidth_capped_at_t_minus_1():
    """An absurd fixed-lag request is capped, not an index error."""
    r = _ar1(50, phi=0.2, mu=0.0008, sigma=0.01, seed=9)
    _, p = compute_dsr(r, num_trials=1, hac_lags=10_000)
    assert p is not None


def test_hac_returns_none_for_constant_series():
    assert compute_dsr([0.01] * 50, num_trials=1, hac_lags="auto") == (None, None)


def test_hac_lags_none_is_exact_iid_default():
    """hac_lags=None must reproduce the pre-existing Bailey-LdP behaviour byte
    for byte (the default path is unchanged)."""
    r = _ar1(800, phi=0.3, mu=0.0008, sigma=0.01, seed=4)
    assert compute_dsr(r, num_trials=5) == compute_dsr(r, num_trials=5, hac_lags=None)


# ─── 5. Single-pass helper (shared-moment optimization) ──────────────────


def test_compute_dsr_hac_and_iid_matches_separate_calls():
    """The single-pass helper is bit-for-bit equal to two compute_dsr calls — it
    only shares the moment/LRV computation, it does not change any number."""
    r = _ar1(800, phi=0.3, mu=0.0008, sigma=0.01, seed=6)
    dsr_hac, p_hac, dsr_iid, p_iid = compute_dsr_hac_and_iid(r, num_trials=5, hac_lags="auto")
    assert (dsr_hac, p_hac) == compute_dsr(r, num_trials=5, average_correlation=0.0, hac_lags="auto")
    assert (dsr_iid, p_iid) == compute_dsr(r, num_trials=5, average_correlation=0.0)


def test_compute_dsr_hac_and_iid_none_for_short_series():
    assert compute_dsr_hac_and_iid([0.01, 0.02, 0.0], num_trials=5) == (None, None, None, None)


# ─── 6. run_rigor_gate integration surface ───────────────────────────────


def test_gate_uses_hac_and_surfaces_iid_delta():
    r = _ar1(800, phi=0.3, mu=0.0008, sigma=0.01, seed=2)
    result = run_rigor_gate("test-strat", list(r), num_trials=5)
    assert result.dsr_se_method == "hac"
    assert result.dsr_p_value_iid is not None
    details = result.gate_details
    assert "HAC" in details["dsr_se"]
    assert "IID-SE" in details["dsr_se"]  # the IID→HAC delta is disclosed


def test_gate_iid_advisory_mentions_hac_correction():
    """The IID advisory now states the SE is corrected via HAC, not merely flagged."""
    r = _ar1(800, phi=0.5, mu=0.0008, sigma=0.01, seed=8)
    details = run_rigor_gate("test-strat", list(r), num_trials=5).gate_details
    assert details["iid"].startswith("ADVISORY")
    if "autocorrelation detected" in details["iid"]:
        assert "HAC" in details["iid"]
