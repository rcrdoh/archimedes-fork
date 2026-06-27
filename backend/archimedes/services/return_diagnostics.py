"""Return-series IID / random-walk diagnostics for the rigor gate.

A backtest Sharpe ratio is only meaningful if the underlying return series
behaves like the IID (or martingale-difference) sequence the Sharpe
assumes. Serial dependence — positive autocorrelation from momentum
overlays, smoothing, or stale marks — *inflates* the realised Sharpe and
fools naive selection-bias controls that treat each observation as
independent. This module ships three self-contained classical tests that
flag such violations before a strategy is admitted to the library.

All functions are pure ``numpy`` / ``scipy.stats`` — no pandas, no network,
no DB. They degrade gracefully on short series (returning ``nan`` statistics
plus ``valid=False`` and a ``reason`` rather than raising).

References
----------
Ljung, G. M. and Box, G. E. P. (1978). "On a Measure of Lack of Fit in
    Time Series Models." *Biometrika*, 65(2), 297-303.
Lo, A. W. and MacKinlay, A. C. (1988). "Stock Market Prices Do Not Follow
    Random Walks: Evidence from a Simple Specification Test." *Review of
    Financial Studies*, 1(1), 41-66.
Wald, A. and Wolfowitz, J. (1940). "On a Test Whether Two Samples are from
    the Same Population." *Annals of Mathematical Statistics*, 11(2),
    147-162.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

# Minimum usable sample sizes. Below these the asymptotic null
# distributions are unreliable, so we return the graceful invalid path.
_MIN_LJUNG_BOX = 10
_MIN_VARIANCE_RATIO = 10
_MIN_RUNS = 8

_ALPHA = 0.05


def _as_clean_array(returns: object) -> np.ndarray:
    """Coerce ``returns`` to a 1-D float array of finite values.

    Parameters
    ----------
    returns : array_like
        Sequence of periodic returns.

    Returns
    -------
    numpy.ndarray
        1-D contiguous ``float64`` array with non-finite entries removed.
    """
    arr = np.asarray(returns, dtype=np.float64).ravel()
    return arr[np.isfinite(arr)]


def _autocorrelations(returns: np.ndarray, max_lag: int) -> np.ndarray:
    r"""Sample autocorrelation function :math:`\hat\rho_k`, k = 1..max_lag.

    Uses the standard biased (divide-by-:math:`T`) autocovariance estimator,
    consistent with the Ljung-Box formulation.

    Parameters
    ----------
    returns : numpy.ndarray
        1-D return series.
    max_lag : int
        Largest lag to compute.

    Returns
    -------
    numpy.ndarray
        Array of length ``max_lag`` holding :math:`\hat\rho_1 \ldots
        \hat\rho_{max\_lag}`.
    """
    n = returns.size
    demeaned = returns - returns.mean()
    denom = np.dot(demeaned, demeaned)
    if denom == 0.0:
        # Constant series: no variation, autocorrelation undefined → 0.
        return np.zeros(max_lag, dtype=np.float64)
    rho = np.empty(max_lag, dtype=np.float64)
    for k in range(1, max_lag + 1):
        cov_k = np.dot(demeaned[: n - k], demeaned[k:])
        rho[k - 1] = cov_k / denom
    return rho


def ljung_box_test(returns: object, lags: int = 10) -> dict:
    r"""Ljung-Box portmanteau test for serial correlation.

    Tests the joint null that the first ``lags`` autocorrelations are all
    zero (the IID / no-autocorrelation hypothesis). The statistic is

    .. math::

        Q = T (T + 2) \sum_{k=1}^{h} \frac{\hat\rho_k^2}{T - k}

    which is asymptotically :math:`\chi^2` with ``h = lags`` degrees of
    freedom under the null (Ljung & Box, 1978). The :math:`\hat\rho_k` are
    computed directly here (no statsmodels dependency).

    Parameters
    ----------
    returns : array_like
        Periodic return series.
    lags : int, default 10
        Number of autocorrelation lags ``h`` to include.

    Returns
    -------
    dict
        Keys: ``statistic`` (Q), ``p_value`` (chi-square upper tail),
        ``lags``, ``autocorrelations`` (list of :math:`\hat\rho_1 \ldots
        \hat\rho_h`), ``reject_iid`` (bool at alpha=0.05), ``valid``
        (bool), and ``reason`` (str, only on the invalid path).
    """
    arr = _as_clean_array(returns)
    n = arr.size
    if lags < 1:
        return {
            "statistic": float("nan"),
            "p_value": float("nan"),
            "lags": int(lags),
            "autocorrelations": [],
            "reject_iid": False,
            "valid": False,
            "reason": "lags must be >= 1",
        }
    if n < _MIN_LJUNG_BOX or n <= lags + 1:
        return {
            "statistic": float("nan"),
            "p_value": float("nan"),
            "lags": int(lags),
            "autocorrelations": [],
            "reject_iid": False,
            "valid": False,
            "reason": (f"series too short: n={n}, need n>={max(_MIN_LJUNG_BOX, lags + 2)}"),
        }

    rho = _autocorrelations(arr, lags)
    k = np.arange(1, lags + 1)
    q_stat = float(n * (n + 2) * np.sum(rho**2 / (n - k)))
    p_value = float(stats.chi2.sf(q_stat, df=lags))
    return {
        "statistic": q_stat,
        "p_value": p_value,
        "lags": int(lags),
        "autocorrelations": rho.tolist(),
        "reject_iid": bool(p_value < _ALPHA),
        "valid": True,
    }


def variance_ratio_test(returns: object, q: int = 2) -> dict:
    r"""Lo-MacKinlay (1988) heteroskedasticity-robust variance-ratio test.

    Under the random-walk null the variance of :math:`q`-period returns is
    :math:`q` times the variance of one-period returns, so the variance
    ratio :math:`VR(q) \approx 1`. The overlapping estimator is used, in its
    algebraically-equivalent autocorrelation form:

    .. math::

        VR(q) = \frac{\sigma_q^2}{q\,\sigma_1^2}
              = 1 + 2 \sum_{k=1}^{q-1}
                \left( 1 - \frac{k}{q} \right) \hat\rho_k

    where :math:`\sigma_1^2` is the one-period variance, :math:`\sigma_q^2`
    is the overlapping :math:`q`-period variance, and :math:`\hat\rho_k` is
    the :math:`k`-th sample autocorrelation. Because financial returns are
    conditionally heteroskedastic, we report the **robust** statistic
    :math:`z^*(q)` which is valid under heteroskedasticity:

    .. math::

        z^*(q) = \frac{VR(q) - 1}{\sqrt{\theta^*(q)}}, \qquad
        \theta^*(q) = \sum_{j=1}^{q-1}
            \left( \frac{2(q-j)}{q} \right)^2 \delta_j

    with the asymptotic-variance components

    .. math::

        \delta_j = \frac{\sum_{t=j+1}^{T}
            (x_t-\hat\mu)^2 (x_{t-j}-\hat\mu)^2}
            {\left(\sum_{t=1}^{T} (x_t-\hat\mu)^2\right)^2}.

    Under the null :math:`z^*(q) \sim N(0,1)`. ``VR > 1`` indicates
    positive serial correlation / trending; ``VR < 1`` indicates
    mean reversion. (Lo & MacKinlay, 1988.)

    Parameters
    ----------
    returns : array_like
        Periodic return series :math:`x_t`.
    q : int, default 2
        Aggregation horizon (number of periods), ``q >= 2``.

    Returns
    -------
    dict
        Keys: ``variance_ratio``, ``z_statistic`` (robust :math:`z^*`),
        ``p_value`` (two-sided normal), ``q``, ``reject_random_walk``
        (bool at alpha=0.05), ``valid`` (bool), and ``reason`` (str, only
        on the invalid path).
    """
    arr = _as_clean_array(returns)
    n = arr.size
    if q < 2:
        return _vr_invalid(q, "q must be >= 2")
    if n < _MIN_VARIANCE_RATIO or n < q + 1:
        return _vr_invalid(q, f"series too short: n={n}, need n>={max(_MIN_VARIANCE_RATIO, q + 1)}")

    mu = arr.mean()
    demeaned = arr - mu
    ss = np.dot(demeaned, demeaned)  # sum of squared deviations
    if ss == 0.0:
        return _vr_invalid(q, "zero one-period variance (constant series)")

    # Overlapping variance-ratio estimator. Lo-MacKinlay's overlapping
    # sigma_q^2 / (q * sigma_1^2) is algebraically identical to the
    # autocorrelation form
    #     VR(q) = 1 + 2 * sum_{k=1}^{q-1} (1 - k/q) * rho_k,
    # where rho_k is the k-th sample autocorrelation. This form is used
    # directly here: it is numerically stable and avoids the bookkeeping of
    # the unbiasing constants while giving an unbiased VR ~ 1 under the
    # random-walk null. VR > 1 => positive serial correlation (trending);
    # VR < 1 => mean reversion.
    rho = np.array([np.dot(demeaned[:-k], demeaned[k:]) / ss for k in range(1, q)])
    weights = 1.0 - np.arange(1, q) / q
    vr = float(1.0 + 2.0 * np.dot(weights, rho))

    # Robust (heteroskedasticity-consistent) asymptotic variance theta*.
    sq = demeaned**2
    denom = ss**2  # (sum (x_t - mu)^2)^2
    theta = 0.0
    for j in range(1, q):
        # delta_j = sum_{t=j+1}^{n} sq_t * sq_{t-j} / denom
        delta_j = np.dot(sq[j:], sq[: n - j]) / denom
        weight = (2.0 * (q - j) / q) ** 2
        theta += weight * delta_j

    if theta <= 0.0:
        return _vr_invalid(q, "non-positive robust variance estimate")

    z = float((vr - 1.0) / np.sqrt(theta))
    p_value = float(2.0 * stats.norm.sf(abs(z)))
    return {
        "variance_ratio": vr,
        "z_statistic": z,
        "p_value": p_value,
        "q": int(q),
        "reject_random_walk": bool(p_value < _ALPHA),
        "valid": True,
    }


def _vr_invalid(q: int, reason: str) -> dict:
    """Build the graceful invalid-path result for the variance-ratio test."""
    return {
        "variance_ratio": float("nan"),
        "z_statistic": float("nan"),
        "p_value": float("nan"),
        "q": int(q),
        "reject_random_walk": False,
        "valid": False,
        "reason": reason,
    }


def runs_test(returns: object) -> dict:
    r"""Wald-Wolfowitz runs test for serial dependence in return signs.

    Converts the series to signs of ``(returns - median)`` and counts the
    number of runs (maximal constant-sign subsequences). Under the null of
    randomness the run count :math:`R` is asymptotically normal with

    .. math::

        E[R] = \frac{2 n_+ n_-}{n} + 1, \qquad
        \mathrm{Var}[R] = \frac{2 n_+ n_- (2 n_+ n_- - n)}{n^2 (n - 1)}

    where :math:`n_+` and :math:`n_-` are the counts of positive and
    negative signs and :math:`n = n_+ + n_-`. Too few runs indicates
    positive dependence (trending); too many indicates mean reversion /
    alternation. (Wald & Wolfowitz, 1940.)

    Zero-deviation observations (exactly at the median) are dropped before
    sign assignment so the binary partition is well defined.

    Parameters
    ----------
    returns : array_like
        Periodic return series.

    Returns
    -------
    dict
        Keys: ``n_runs``, ``expected_runs``, ``z_statistic``, ``p_value``
        (two-sided normal), ``reject_randomness`` (bool at alpha=0.05),
        ``valid`` (bool), and ``reason`` (str, only on the invalid path).
    """
    arr = _as_clean_array(returns)
    signs = np.sign(arr - np.median(arr))
    signs = signs[signs != 0.0]
    n = signs.size
    n_pos = int(np.sum(signs > 0))
    n_neg = int(np.sum(signs < 0))

    if n < _MIN_RUNS or n_pos == 0 or n_neg == 0:
        return {
            "n_runs": int(0 if n == 0 else 1),
            "expected_runs": float("nan"),
            "z_statistic": float("nan"),
            "p_value": float("nan"),
            "reject_randomness": False,
            "valid": False,
            "reason": (f"series too short or degenerate: n={n}, n_pos={n_pos}, n_neg={n_neg}"),
        }

    # A run starts at index 0 and at every sign change thereafter.
    n_runs = int(1 + np.sum(signs[1:] != signs[:-1]))

    expected = 2.0 * n_pos * n_neg / n + 1.0
    variance = 2.0 * n_pos * n_neg * (2.0 * n_pos * n_neg - n) / (n**2 * (n - 1))
    if variance <= 0.0:
        return {
            "n_runs": n_runs,
            "expected_runs": float(expected),
            "z_statistic": float("nan"),
            "p_value": float("nan"),
            "reject_randomness": False,
            "valid": False,
            "reason": "non-positive runs variance",
        }

    z = float((n_runs - expected) / np.sqrt(variance))
    p_value = float(2.0 * stats.norm.sf(abs(z)))
    return {
        "n_runs": n_runs,
        "expected_runs": float(expected),
        "z_statistic": z,
        "p_value": p_value,
        "reject_randomness": bool(p_value < _ALPHA),
        "valid": True,
    }


def diagnose(returns: object, lags: int = 10, vr_q: int = 2) -> dict:
    """Run all three IID / random-walk diagnostics and aggregate.

    Wired into ``rigor_evaluator.run_rigor_gate`` (#621) as an **advisory**
    diagnostic surfaced in ``RigorGateResult.gate_details['iid']`` — it is
    deliberately NOT a pass/fail criterion, because autocorrelated returns are
    the edge for trend/momentum strategies and must not fail the gate.

    Parameters
    ----------
    returns : array_like
        Periodic return series.
    lags : int, default 10
        Lags passed to :func:`ljung_box_test`.
    vr_q : int, default 2
        Horizon passed to :func:`variance_ratio_test`.

    Returns
    -------
    dict
        Keys ``ljung_box``, ``variance_ratio``, ``runs`` (the three
        sub-test result dicts) plus ``iid_assumption_violated`` (bool):
        ``True`` if **any** valid sub-test rejects its null at alpha=0.05.
        Invalid (skipped) sub-tests never trigger a violation.
    """
    lb = ljung_box_test(returns, lags=lags)
    vr = variance_ratio_test(returns, q=vr_q)
    runs = runs_test(returns)

    violated = bool(
        (lb.get("valid") and lb.get("reject_iid"))
        or (vr.get("valid") and vr.get("reject_random_walk"))
        or (runs.get("valid") and runs.get("reject_randomness"))
    )
    return {
        "ljung_box": lb,
        "variance_ratio": vr,
        "runs": runs,
        "iid_assumption_violated": violated,
    }
