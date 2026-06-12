"""Finite-sample and autocorrelation corrections for the Sharpe ratio.

This module implements the statistical corrections derived in

    Lo, A. W. (2002). "The Statistics of Sharpe Ratios."
    *Financial Analysts Journal*, 58(4), 36--52.

The naive annualized Sharpe ratio scales the per-period Sharpe by
``sqrt(q)`` (e.g. ``sqrt(12)`` for monthly-to-annual). That scaling is only
correct when returns are independently and identically distributed (IID).
Lo (2002) shows two things that matter for rigorous strategy evaluation:

1. The estimated Sharpe ratio carries finite-sample estimation error whose
   standard error, *under the IID assumption*, is given by his equation (6):
   ``sqrt((1 + 0.5 * SR**2) / n)``.
2. When returns are serially correlated, the ``sqrt(q)`` time-aggregation rule
   is wrong. The correct multiplier is ``eta(q)`` (Lo's Proposition 2), which
   accounts for the autocovariance structure. Positive autocorrelation makes
   the naive annualized Sharpe *overstate* the true annualized Sharpe; negative
   autocorrelation makes it understate it.

A genuine heteroskedasticity- and autocorrelation-consistent (HAC) standard
error of the per-period Sharpe is also provided via a GMM sandwich estimator
with a Bartlett kernel plus the delta method (Lo 2002, Section "The General
Case / GMM").

Pure ``numpy`` / ``scipy`` only -- no pandas, no I/O, no network, no DB.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "autocorr_adjusted_annualized_sharpe",
    "iid_sharpe_stderr",
    "newey_west_sharpe_stderr",
    "sharpe_ratio",
]


def _as_excess(returns: np.ndarray | list[float], rf: float) -> np.ndarray:
    """Coerce ``returns`` to a 1-D float array of excess returns ``r - rf``.

    Parameters
    ----------
    returns : array_like
        Per-period (not annualized) returns.
    rf : float
        Per-period risk-free rate, subtracted elementwise.

    Returns
    -------
    numpy.ndarray
        1-D float64 array of excess returns. NaNs/Infs are dropped so the
        callers operate on finite data only.
    """
    arr = np.asarray(returns, dtype=np.float64).ravel()
    arr = arr[np.isfinite(arr)]
    return arr - rf


def sharpe_ratio(returns: np.ndarray | list[float], rf: float = 0.0) -> float:
    """Per-period Sharpe ratio of excess returns.

    Computes ``mean(r - rf) / std(r - rf, ddof=1)`` where ``r`` are the
    per-period returns. This is the un-annualized ("raw") Sharpe ratio that
    every other function in this module builds on.

    Parameters
    ----------
    returns : array_like
        Per-period returns. Non-finite entries are dropped.
    rf : float, optional
        Per-period risk-free rate (default ``0.0``).

    Returns
    -------
    float
        The per-period Sharpe ratio, or ``nan`` if fewer than two finite
        observations remain or the sample standard deviation is zero.

    Notes
    -----
    The sample standard deviation uses ``ddof=1`` (unbiased, Bessel-corrected),
    matching the convention in Lo (2002). The ``nan`` convention for
    degenerate inputs (``n < 2`` or zero variance) keeps the function total and
    lets callers decide how to surface "undefined Sharpe" rather than raising.
    """
    excess = _as_excess(returns, rf)
    n = excess.size
    if n < 2:
        return float("nan")
    sd = float(np.std(excess, ddof=1))
    if sd == 0.0 or not np.isfinite(sd):
        return float("nan")
    return float(np.mean(excess) / sd)


def iid_sharpe_stderr(sharpe: float, n: int) -> float:
    """Asymptotic standard error of the Sharpe ratio under IID returns.

    Implements Lo (2002), equation (6):

    .. math::

        \\mathrm{SE}(\\widehat{SR}) = \\sqrt{\\frac{1 + \\tfrac{1}{2}\\,SR^2}{n}}

    Parameters
    ----------
    sharpe : float
        The (per-period) Sharpe ratio estimate.
    n : int
        Number of observations used to estimate ``sharpe``.

    Returns
    -------
    float
        The IID asymptotic standard error, or ``nan`` if ``n < 1`` or
        ``sharpe`` is not finite.

    Notes
    -----
    This is the variance of the Sharpe estimator under the assumption that
    returns are IID normal (more precisely, the leading-order GMM result when
    the autocovariances vanish). It is the *wrong* SE when returns are serially
    correlated -- use :func:`newey_west_sharpe_stderr` in that case.
    """
    if n < 1 or not np.isfinite(sharpe):
        return float("nan")
    return float(np.sqrt((1.0 + 0.5 * sharpe * sharpe) / n))


def _autocorrelations(x: np.ndarray, max_lag: int) -> list[float]:
    """Sample autocorrelations ``rho_1 .. rho_max_lag`` of a 1-D series.

    Uses the standard biased (divide-by-``n``) autocovariance normalization,
    which is the convention underlying Lo's time-aggregation result.

    Parameters
    ----------
    x : numpy.ndarray
        1-D series (already de-meanable; mean is removed internally).
    max_lag : int
        Highest lag to compute.

    Returns
    -------
    list of float
        ``[rho_1, ..., rho_max_lag]``. Lags beyond the available sample, or any
        computed on a zero-variance series, are returned as ``0.0``.
    """
    n = x.size
    if n < 2 or max_lag < 1:
        return [0.0] * max(max_lag, 0)
    xc = x - x.mean()
    denom = float(np.dot(xc, xc))
    rhos: list[float] = []
    for k in range(1, max_lag + 1):
        if k >= n or denom == 0.0:
            rhos.append(0.0)
            continue
        cov_k = float(np.dot(xc[:-k], xc[k:]))
        rhos.append(cov_k / denom)
    return rhos


def autocorr_adjusted_annualized_sharpe(
    returns: np.ndarray | list[float],
    q: int,
    rf: float = 0.0,
) -> dict:
    """Autocorrelation-corrected annualized Sharpe ratio (Lo 2002).

    Under IID returns the annualized Sharpe is ``sqrt(q) * SR``. Lo (2002,
    Proposition 2) shows that with serial correlation the correct time-
    aggregation multiplier is

    .. math::

        \\eta(q) = \\frac{q}{\\sqrt{\\,q + 2 \\sum_{k=1}^{q-1} (q - k)\\,\\rho_k\\,}}

    where :math:`\\rho_k` is the lag-``k`` autocorrelation of the per-period
    excess returns. The autocorrelation-adjusted annualized Sharpe is then
    ``eta(q) * SR``.

    Parameters
    ----------
    returns : array_like
        Per-period excess-able returns (``rf`` is subtracted internally).
    q : int
        Aggregation factor (number of periods per annualization unit, e.g.
        ``12`` for monthly returns, ``252`` for daily).
    rf : float, optional
        Per-period risk-free rate (default ``0.0``).

    Returns
    -------
    dict
        Dictionary with keys:

        ``per_period_sharpe`` : float
            The un-annualized Sharpe (see :func:`sharpe_ratio`).
        ``naive_annualized`` : float
            ``sqrt(q) * per_period_sharpe`` (the IID rule).
        ``autocorr_adjusted_annualized`` : float
            ``eta * per_period_sharpe``.
        ``eta`` : float
            The Lo (2002) multiplier ``eta(q)``.
        ``q`` : int
            Echo of the aggregation factor.
        ``autocorrelations`` : list of float
            ``[rho_1, ..., rho_{q-1}]`` of the per-period excess returns.
        ``adjustment_valid`` : bool
            ``True`` when the denominator ``q + 2*sum((q-k)*rho_k) > 0``.
            When it is ``<= 0`` (which can happen with strong negative
            autocorrelation in finite samples and would make ``eta``
            ill-defined), the function falls back to ``eta = sqrt(q)`` and sets
            this flag ``False``.

    Notes
    -----
    Positive serial correlation drives ``eta < sqrt(q)`` so the adjusted Sharpe
    is *strictly below* the naive one -- Lo's central point that naive
    annualization overstates risk-adjusted performance for trending/illiquid
    strategies. Negative serial correlation drives ``eta > sqrt(q)``.
    """
    excess = _as_excess(returns, rf)
    sr = sharpe_ratio(excess, rf=0.0)
    q_int = int(q)

    if q_int < 1:
        q_int = 1

    rhos = _autocorrelations(excess, max_lag=q_int - 1)

    # denominator = q + 2 * sum_{k=1}^{q-1} (q - k) * rho_k
    cross = sum((q_int - (k + 1)) * rhos[k] for k in range(len(rhos)))
    denom = q_int + 2.0 * cross

    if denom > 0.0:
        eta = q_int / np.sqrt(denom)
        adjustment_valid = True
    else:
        # Ill-defined eta (negative/zero variance of the q-period sum in
        # finite samples) -- fall back to the IID sqrt(q) multiplier.
        eta = float(np.sqrt(q_int))
        adjustment_valid = False

    naive = float(np.sqrt(q_int) * sr) if np.isfinite(sr) else float("nan")
    adjusted = float(eta * sr) if np.isfinite(sr) else float("nan")

    return {
        "per_period_sharpe": float(sr),
        "naive_annualized": naive,
        "autocorr_adjusted_annualized": adjusted,
        "eta": float(eta),
        "q": q_int,
        "autocorrelations": [float(r) for r in rhos],
        "adjustment_valid": bool(adjustment_valid),
    }


def _default_nw_lags(n: int) -> int:
    """Newey-West default lag truncation ``floor(4 * (n/100)**(2/9))``, min 0."""
    if n < 1:
        return 0
    return max(0, int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))))


def newey_west_sharpe_stderr(
    returns: np.ndarray | list[float],
    rf: float = 0.0,
    lags: int | None = None,
) -> float:
    """HAC (Newey-West) standard error of the per-period Sharpe ratio.

    This is a genuine heteroskedasticity- and autocorrelation-consistent
    standard error, not the IID formula. Following Lo (2002, the GMM "General
    Case"), the Sharpe ratio is treated as a smooth function of two moments,
    ``theta = (mu, gamma)`` with ``mu = E[r]`` and ``gamma = E[r^2]``, so that

    .. math::

        SR = \\frac{\\mu}{\\sqrt{\\gamma - \\mu^2}} .

    The moment-condition residuals are
    ``h_t = (r_t - mu, r_t^2 - gamma)``. Their long-run covariance is estimated
    with the Bartlett-kernel HAC estimator

    .. math::

        \\widehat{\\Omega} = \\Gamma_0
            + \\sum_{j=1}^{L} \\Big(1 - \\tfrac{j}{L+1}\\Big)
              (\\Gamma_j + \\Gamma_j^{\\top}),

    where :math:`\\Gamma_j = \\tfrac{1}{n}\\sum_t h_t h_{t-j}^{\\top}` and ``L``
    is the lag truncation. The delta method then gives

    .. math::

        \\mathrm{Var}(\\widehat{SR}) =
            \\frac{1}{n}\\, \\nabla g^{\\top}\\, \\widehat{\\Omega}\\, \\nabla g,

    with ``g(theta) = mu / sqrt(gamma - mu^2)`` and gradient
    ``nabla g = (dSR/dmu, dSR/dgamma)`` evaluated at the sample moments.

    Parameters
    ----------
    returns : array_like
        Per-period returns. Non-finite entries are dropped.
    rf : float, optional
        Per-period risk-free rate, subtracted before estimation (default
        ``0.0``).
    lags : int or None, optional
        Bartlett-kernel lag truncation ``L``. If ``None`` (default), uses the
        automatic rule ``floor(4 * (n/100)**(2/9))`` (minimum 0). When
        ``lags == 0`` the estimator reduces to the heteroskedasticity-only
        (White) sandwich, which on IID data is asymptotically equivalent to the
        IID formula of :func:`iid_sharpe_stderr`.

    Returns
    -------
    float
        The HAC standard error of the per-period Sharpe ratio, or ``nan`` for
        degenerate inputs (``n < 2``, zero variance, or a non-positive
        variance estimate).

    Notes
    -----
    With ``lags >= 1`` and positive autocorrelation the HAC SE is typically
    larger than the IID SE, reflecting the loss of effective sample size; this
    is the inference-side analogue of the point-estimate correction in
    :func:`autocorr_adjusted_annualized_sharpe`.
    """
    excess = _as_excess(returns, rf)
    n = excess.size
    if n < 2:
        return float("nan")

    mu = float(np.mean(excess))
    gamma = float(np.mean(excess * excess))
    var = gamma - mu * mu
    if var <= 0.0 or not np.isfinite(var):
        return float("nan")
    sigma = np.sqrt(var)

    # Moment residuals h_t = (r_t - mu, r_t^2 - gamma), shape (n, 2).
    h = np.column_stack((excess - mu, excess * excess - gamma))

    if lags is None:
        lags = _default_nw_lags(n)
    lags = max(0, int(lags))
    lags = min(lags, n - 1)

    # Bartlett-kernel HAC long-run covariance Omega (2 x 2).
    omega = (h.T @ h) / n
    for j in range(1, lags + 1):
        weight = 1.0 - j / (lags + 1.0)
        gamma_j = (h[j:].T @ h[:-j]) / n
        omega += weight * (gamma_j + gamma_j.T)

    # Gradient of g(mu, gamma) = mu / sqrt(gamma - mu^2).
    #   dSR/dmu    = 1/sigma + mu^2 / sigma^3
    #   dSR/dgamma = -mu / (2 * sigma^3)
    sigma3 = sigma**3
    grad = np.array(
        [
            1.0 / sigma + (mu * mu) / sigma3,
            -mu / (2.0 * sigma3),
        ]
    )

    var_sr = float(grad @ omega @ grad) / n
    if var_sr < 0.0 or not np.isfinite(var_sr):
        return float("nan")
    return float(np.sqrt(var_sr))
