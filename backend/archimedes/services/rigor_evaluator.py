"""Selection-bias corrections: DSR, PBO, walk-forward OOS Sharpe, look-ahead audit.

Implements the four-primitive admission gate that separates Tier-1 (Archimedes
Verified) strategies from curve-fit noise:

  1. Deflated Sharpe Ratio — Bailey & López de Prado (2014)
  2. Probability of Backtest Overfitting via CSCV — Bailey et al. (2014)
  3. Out-of-sample Sharpe — single chronological hold-out today (see
     compute_oos_sharpe); rolling Combinatorial Purged CV (compute_cpcv_oos_sharpe)
     is the principled upgrade, wired once a combinatorial OOS matrix exists
  4. Look-ahead static audit (AST-based)

All functions are pure computation: no I/O, no web framework, no on-chain
dependencies. They consume daily return arrays and produce the fields that
BacktestResult.passes_rigor_gate checks.

Owner: Önder (math lane)
Spec:  docs/specs/selection-bias-corrections-spec.md
"""

from __future__ import annotations

import ast
import logging
import math
import warnings
from itertools import combinations
from typing import Any

import numpy as np
from scipy.stats import kurtosis as sp_kurtosis
from scipy.stats import norm
from scipy.stats import skew as sp_skew

logger = logging.getLogger(__name__)

_EULER_MASCHERONI = 0.5772156649
_ANNUALIZATION = 252
_RF_ANNUAL = 0.05  # 5% annual risk-free rate (Fed funds 2024-2025 environment)
_RF_DAILY = _RF_ANNUAL / _ANNUALIZATION


# ─── 1. Deflated Sharpe Ratio ────────────────────────────────────────


def compute_dsr(
    daily_returns: list[float] | np.ndarray,
    num_trials: int,
    average_correlation: float = 0.0,
) -> tuple[float | None, float | None]:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014).

    Corrects the observed Sharpe for non-normality (skew + excess kurtosis)
    and multiple-testing inflation (selection across N candidate strategies).

    Args:
        daily_returns: Per-bar (daily) return series, un-annualized.
        num_trials: Number of strategies in the selection set (N). Pass 1
            if this is the only strategy ever evaluated — no correction
            will be applied. The orchestrator should pass
            len(strategy_library) so the correction is meaningful.
        average_correlation: The average pairwise correlation between the
            trials. Used to compute the effective number of independent
            trials (Bailey-López de Prado variance-of-trials correlation model).

    Returns:
        (deflated_sharpe_ratio, dsr_p_value)
          - deflated_sharpe_ratio: annualized Sharpe excess over the
            expected best-of-N null. Positive means the strategy clears
            the multiple-testing bar.
          - dsr_p_value: P(true SR > 0 | observed SR, N trials, T bars).
            Gate threshold is 0.95 per passes_rigor_gate.
        Both are None if data is insufficient (T < 4) or degenerate.
    """
    if num_trials < 1:
        raise ValueError("num_trials must be >= 1")

    arr = np.asarray(daily_returns, dtype=float)
    T = len(arr)
    if T < 4:
        return None, None

    # numpy std(ddof=1) can be a tiny non-zero float for identical values due
    # to floating-point cancellation; check range first to catch constant series.
    if float(np.ptp(arr)) == 0.0:
        return None, None

    sigma = float(arr.std(ddof=1))
    if sigma <= 0.0:
        return None, None

    SR_hat = (float(arr.mean()) - _RF_DAILY) / sigma  # excess return per bar, un-annualized
    gamma_3 = float(sp_skew(arr))
    # Bailey-LdP (2014) eq. 8 uses raw (Pearson) kurtosis (γ₄ = 3 for normal),
    # NOT Fisher excess kurtosis. The coefficient (γ₄ − 1)/4 in _dsr_from_stats
    # is derived for the raw-kurtosis convention; using fisher=True here would
    # shift the denominator by a constant (3/4)·ŜR² and bias every DSR.
    gamma_4 = float(sp_kurtosis(arr, fisher=False))  # raw (Pearson) kurtosis

    if math.isnan(average_correlation):
        average_correlation = 0.0
    average_correlation = max(0.0, min(1.0, average_correlation))

    dsr, p_val = _dsr_from_stats(SR_hat, T, gamma_3, gamma_4, num_trials, average_correlation)
    return dsr, p_val


def _dsr_from_stats(
    SR_hat: float,
    T: int,
    gamma_3: float,
    gamma_4: float,
    N: int,
    average_correlation: float = 0.0,
) -> tuple[float | None, float | None]:
    """Core DSR formula — exposed for direct unit-testing against spec cases.

    Args:
        SR_hat: Per-bar (un-annualized) Sharpe ratio.
        T: Number of bars in the return series.
        gamma_3: Skewness of the per-bar return series.
        gamma_4: Raw (Pearson) kurtosis of the per-bar return series — γ₄ = 3
            for normal returns. This matches Bailey-LdP (2014) eq. 8 directly;
            do NOT pass Fisher excess kurtosis here (it would bias the denom).
        N: Number of trials in the selection set.
        average_correlation: Correlation scalar for variance of trials.

    Returns:
        (deflated_sharpe_annualized, dsr_p_value) or (None, None).
    """
    if T < 4:
        return None, None

    N = max(1, N)

    # E[max_N]: Bailey-LdP (2014) approximation for the expected maximum of N
    # iid standard-normal random variables (the expected best-of-N null SR).
    if N == 1:
        E_max_N = 0.0
    else:
        # Correlated trials are not independent tests: a parameter sweep whose
        # variants move together carries fewer effective trials than its nominal
        # count. Convert N to an effective count under an equicorrelation model
        # with average pairwise correlation ρ:
        #     N_eff = N / (1 + (N − 1)·ρ)
        # the standard "effective number of independent tests" (Cheverud 2001;
        # Nyholt 2004 — the equicorrelated effective sample size). ρ=0 → N_eff=N
        # (full multiple-testing penalty); ρ=1 → N_eff=1 (all variants collapse
        # to a single test, so there is no selection bias to deflate). This
        # replaces a previous ad-hoc E[max]·sqrt(1 − ρ) factor that had no
        # published source and let deflation vanish without a principled basis.
        rho = max(0.0, min(1.0, average_correlation))
        n_eff = N / (1.0 + (N - 1) * rho) if rho > 0.0 else float(N)

        # The Bailey-LdP two-quantile E[max] approximation is only well-behaved
        # for ≥ 2 trials (norm.ppf(1 − 1/N) → −∞ as N → 1). Evaluate it at
        # max(2, N_eff) and linearly taper the result to 0 across the effective
        # range [1, 2], so a fully correlated grid (N_eff → 1) carries no penalty
        # without the ppf blow-up a literal non-integer N_eff < 2 would cause.
        n_for_emax = max(2.0, n_eff)
        phi_inv_1 = float(norm.ppf(1.0 - 1.0 / n_for_emax))
        phi_inv_2 = float(norm.ppf(1.0 - 1.0 / (n_for_emax * math.e)))
        e_max_full = (1.0 - _EULER_MASCHERONI) * phi_inv_1 + _EULER_MASCHERONI * phi_inv_2
        taper = min(1.0, max(0.0, n_eff - 1.0))
        E_max_N = e_max_full * taper

    # SR_zero: expected best-of-N under the null, scaled to per-bar variance
    # (under iid normal returns, per-bar SR has variance 1/(T-1))
    SR_zero = math.sqrt(1.0 / (T - 1)) * E_max_N

    # Variance-adjusted z-statistic (eq. 8 in Bailey-LdP 2014)
    denom_sq = 1.0 - gamma_3 * SR_hat + ((gamma_4 - 1.0) / 4.0) * SR_hat**2
    if denom_sq <= 0.0:
        return None, None

    z = (SR_hat - SR_zero) * math.sqrt(T - 1) / math.sqrt(denom_sq)
    dsr_p_value = float(norm.cdf(z))

    # Annualize the deflated SR for display (Sharpe units, not probability)
    deflated_sharpe_ratio = (SR_hat - SR_zero) * math.sqrt(_ANNUALIZATION)

    return round(deflated_sharpe_ratio, 6), round(dsr_p_value, 6)


# ─── 2. Probability of Backtest Overfitting (CSCV) ──────────────────


def compute_pbo(
    returns_matrix: dict[str, list[float]],
    s_partitions: int = 16,
) -> dict[str, float]:
    """Probability of Backtest Overfitting via CSCV (Bailey et al. 2014).

    Computes the fraction of combinatorial IS/OOS splits in which the
    in-sample-optimal strategy underperforms the OOS median. PBO is a
    library-level metric: a single value is computed across all N strategies
    and attached identically to each strategy's BacktestResult from this run.

    Args:
        returns_matrix: {strategy_id: [daily_returns]} — all strategies must
            cover the same date range. Series are truncated to the shortest
            length to align them.
        s_partitions: Number of equal time-partitions S. Must be even ≥ 2.
            Default 16 is the paper's recommended value.

    Returns:
        {strategy_id: pbo_score} — lower is better. PBO ≥ 0.5 means the
        library is expected to overfit (IS-best underperforms OOS median).
        Returns 0.0 for every strategy if N < 2 or data is insufficient.

    Known limitations (the library here is small — N ≈ 4–6 today):
      - Library-level coupling: PBO is a property of the whole selection set,
        not of one strategy, yet the same value is attached to every member.
        A strategy's PBO verdict therefore depends on which *other* strategies
        happen to be in the library — adding or removing a neighbor can flip
        it. This is inherent to CSCV, not a bug, but it means PBO should be
        read as a library-overfit signal, not a per-strategy score.
      - Coarse OOS rank: ω = rank_oos / N takes only N discrete values, so with
        N = 4 the logit λ is quantized to a handful of levels and PBO is
        granular. The estimate sharpens as the library grows.
      - Trailing-bar truncation: rows_per_block = T // S drops up to S − 1
        trailing bars (≤ 15 at the default S = 16) so every block is equal-length.
        Negligible for multi-year series; worth noting for short ones.
    """
    if len(returns_matrix) < 2:
        return dict.fromkeys(returns_matrix, 0.0)

    sorted_ids = sorted(returns_matrix.keys())
    N = len(sorted_ids)

    lengths = {sid: len(returns_matrix[sid]) for sid in sorted_ids}
    T = min(lengths.values())
    T_max = max(lengths.values())
    if T_max != T:
        # Mirror of analytics-engine pbo.py: truncating to the shortest series
        # silently drops the most recent (most forward-looking) OOS bars from
        # longer series. Surface it so the caller date-aligns rather than
        # getting an optimistic PBO from misaligned data.
        discarded = {sid: lengths[sid] - T for sid in sorted_ids if lengths[sid] > T}
        warnings.warn(
            f"compute_pbo: series length mismatch (min={T}, max={T_max}); "
            f"trailing bars discarded per id: {discarded}. Pass date-aligned "
            f"series to suppress this warning.",
            stacklevel=2,
        )

    # Build (T, N) matrix, columns in sorted_ids order
    R = np.array([returns_matrix[sid][:T] for sid in sorted_ids], dtype=float).T  # shape (T, N)

    S = s_partitions if (s_partitions % 2 == 0 and s_partitions >= 2) else 16
    rows_per_block = T // S
    if rows_per_block < 1:
        return dict.fromkeys(sorted_ids, 0.0)

    blocks = [R[i * rows_per_block : (i + 1) * rows_per_block, :] for i in range(S)]
    half = S // 2
    lambdas: list[float] = []

    for is_indices in combinations(range(S), half):
        oos_indices = [i for i in range(S) if i not in is_indices]

        IS = np.vstack([blocks[i] for i in is_indices])
        OOS = np.vstack([blocks[i] for i in oos_indices])

        is_sharpes = _sharpe_per_col(IS)
        oos_sharpes = _sharpe_per_col(OOS)

        best_is_idx = int(np.argmax(is_sharpes))

        # Ascending rank (1 = worst, N = best) of IS-best strategy in OOS
        oos_ranks = _ascending_ranks(oos_sharpes)
        rank_oos = float(oos_ranks[best_is_idx])

        omega = rank_oos / N
        omega = float(np.clip(omega, 1e-9, 1.0 - 1e-9))
        lam = math.log(omega / (1.0 - omega))
        lambdas.append(lam)

    if not lambdas:
        return dict.fromkeys(sorted_ids, 0.0)

    pbo = round(sum(1 for lam in lambdas if lam <= 0.0) / len(lambdas), 6)
    return dict.fromkeys(sorted_ids, pbo)


# ─── 3. Walk-forward OOS Sharpe ──────────────────────────────────────


def compute_oos_sharpe(
    daily_returns: list[float],
    train_fraction: float = 0.70,
) -> float | None:
    """Annualized Sharpe on the held-out OOS slice (no shuffling).

    Splits the return series chronologically: the first train_fraction of
    bars are in-sample; the remainder are the OOS test set. The OOS Sharpe
    must clear the absolute floor (> 0) and the cliff check (OOS/IS ≥ 0.5)
    in RigorGateResult.passes_all.

    NOTE — this is a single chronological hold-out, NOT a rolling walk-forward
    re-estimation. There is no per-window refit and no purge/embargo gap at the
    train/test boundary, so signal state from lookback indicators (e.g. an
    SMA-200 or TSMOM-252 window) can straddle the split. Rolling Combinatorial
    Purged CV is the principled upgrade and is implemented separately in
    ``compute_cpcv_oos_sharpe`` (wired into ``run_rigor_gate`` once the
    analytics-engine emits a combinatorial OOS matrix; reported as MISSING
    until then).

    Args:
        daily_returns: Full per-bar return series.
        train_fraction: Fraction reserved for in-sample training (0 < f < 1).

    Returns:
        Annualized OOS Sharpe, or None if the OOS slice is shorter than one
        trading month (< 21 bars) or the full series has < 10 bars.
    """
    arr = np.asarray(daily_returns, dtype=float)
    T = len(arr)
    if T < 10:
        return None

    split = int(T * train_fraction)
    oos = arr[split:]

    if len(oos) < 21:  # 1 trading month minimum (5-bar floor was statistically degenerate)
        return None

    if float(np.ptp(oos)) == 0.0:
        return None

    sigma = float(oos.std(ddof=1))
    if sigma <= 0.0:
        return None

    return round(float(((oos.mean() - _RF_DAILY) / sigma) * math.sqrt(_ANNUALIZATION)), 6)


def _annualized_sharpe_arr(arr: np.ndarray) -> float | None:
    """Annualized Sharpe of a 1-D return array, or None if degenerate."""
    if len(arr) < 2:
        return None
    if float(np.ptp(arr)) == 0.0:
        return None
    sigma = float(arr.std(ddof=1))
    if sigma <= 0.0:
        return None
    return float(((arr.mean() - _RF_DAILY) / sigma) * math.sqrt(_ANNUALIZATION))


def compute_average_pairwise_correlation(
    returns: dict[str, list[float]] | np.ndarray | list[list[float]],
) -> float:
    """Average off-diagonal Pearson correlation across a set of return series.

    Feeds the Deflated Sharpe Ratio's effective-number-of-trials correction:
    the expected best-of-N null Sharpe is computed at the effective trial count
    ``N_eff = N / (1 + (N-1)*rho_bar)`` (the equicorrelated effective number of
    independent tests) when the N trials are correlated, because correlated
    trials carry fewer *independent* bets than their nominal count. The caller
    that holds the selection set (the strategy library, or a parameter-variant
    grid) computes this and passes it into ``compute_dsr`` / ``run_rigor_gate``.

    Args:
        returns: Either ``{id: series}`` or a 2-D array/list (rows = trials,
            cols = time). Series are truncated to the shortest length.

    Returns:
        Mean pairwise correlation clamped to ``[0.0, 1.0]`` — negative
        (diversifying) correlations and NaNs collapse to ``0.0``, a conservative
        "no penalty relief" default. Returns ``0.0`` for < 2 usable series.
    """
    series = list(returns.values()) if isinstance(returns, dict) else list(returns)
    arrs = [np.asarray(s, dtype=float) for s in series]
    arrs = [a for a in arrs if a.size >= 2]
    if len(arrs) < 2:
        return 0.0

    T = min(a.size for a in arrs)
    if T < 2:
        return 0.0

    matrix = np.vstack([a[:T] for a in arrs])
    # Drop constant rows — they produce NaN correlations. Use peak-to-peak
    # (exactly 0 for identical values) rather than variance, which carries a
    # tiny float residual for a constant series.
    matrix = matrix[np.ptp(matrix, axis=1) > 0.0]
    if matrix.shape[0] < 2:
        return 0.0

    corr = np.corrcoef(matrix)
    upper = corr[np.triu_indices(corr.shape[0], k=1)]
    upper = upper[np.isfinite(upper)]
    if upper.size == 0:
        return 0.0

    return max(0.0, min(1.0, float(np.mean(upper))))


# ─── 3b. Combinatorial Purged Cross-Validation OOS Sharpe ────────────


def compute_cpcv_oos_sharpe(
    cv_returns_matrix: np.ndarray | list[list[float]] | None = None,
    n_groups: int = 6,
    test_groups: int = 2,
    test_bounds: list[np.ndarray] | list[list[int]] | None = None,
    cv_splits: list[tuple[int, ...]] | None = None,
) -> dict[str, float] | None:
    """Combinatorial Purged Cross-Validation OOS Sharpe (López de Prado, AFML ch. 12).

    Unlike naive block subsampling on a static returns array, true CPCV requires
    a matrix of out-of-sample predictions from models trained on C(N, k) splits.
    This function assembles C(N-1, k-1) continuous backtest paths from those
    splits, preventing artificial variance and evaluating path-to-path stability.

    Note on embargo: Embargoing (dropping bars after test sets) must be applied
    upstream during the generation of `cv_returns_matrix` to prevent serial
    correlation leakage into the training sets. Path assembly only combines
    the resulting OOS test blocks.

    Args:
        cv_returns_matrix: Shape (S, T) where S = C(n_groups, test_groups).
            If a 1D array of static returns is passed (e.g. from a single backtest),
            this correctly rejects the calculation, as static CPCV is mathematically
            invalid (it generates identical paths).
        n_groups: Number of contiguous partitions (N). Must be >= 2.
        test_groups: Blocks held out per split (k), 1 <= k < N.
        test_bounds: Explicit list of N arrays containing the exact time indices for
            each block to prevent look-ahead bias from misaligned uniform splits.
        cv_splits: Explicit list of S tuples mapping each matrix row to the test
            blocks it held out, preventing lexicographical misalignment.

    Returns:
        Dict with metrics, or None if invalid matrix or static returns provided.
    """
    if cv_returns_matrix is None or len(cv_returns_matrix) == 0:
        return None

    arr = np.asarray(cv_returns_matrix, dtype=float)
    if arr.ndim != 2:
        return None

    S, T = arr.shape
    if n_groups < 2 or not (1 <= test_groups < n_groups):
        return None
    if n_groups * 5 > T:  # need >= ~5 bars per block to form a Sharpe
        return None

    splits = cv_splits if cv_splits is not None else list(combinations(range(n_groups), test_groups))

    if len(splits) != S:
        return None

    if test_bounds is not None:
        bounds = [np.asarray(b, dtype=int) for b in test_bounds]
        if len(bounds) != n_groups:
            return None
    else:
        bounds = np.array_split(np.arange(T), n_groups)

    n_paths = math.comb(n_groups - 1, test_groups - 1)

    paths = np.zeros((n_paths, T))

    for i in range(n_groups):
        splits_with_i = [s_idx for s_idx, combo in enumerate(splits) if i in combo]
        if len(splits_with_i) != n_paths:
            return None  # cv_splits ordering doesn't match expected block count
        paths[:, bounds[i]] = arr[np.ix_(splits_with_i, bounds[i])]

    oos_sharpes: list[float] = []
    for p in range(n_paths):
        s = _annualized_sharpe_arr(paths[p])
        if s is not None and math.isfinite(s):
            oos_sharpes.append(s)

    if not oos_sharpes:
        return None

    mean_oos = float(np.mean(oos_sharpes))
    positive_fraction = float(sum(s > 0.0 for s in oos_sharpes) / len(oos_sharpes))

    return {
        "mean_oos_sharpe": round(mean_oos, 6),
        "std_oos_sharpe": round(float(np.std(oos_sharpes, ddof=1)) if len(oos_sharpes) > 1 else 0.0, 6),
        "positive_fraction": round(positive_fraction, 6),
        "mean_is_sharpe": 0.0,
        "oos_is_ratio": 0.0,
        "n_paths": len(oos_sharpes),
    }


# ─── 4. Kelly Criterion position sizing ─────────────────────────────


def compute_kelly_fraction(
    daily_returns: list[float],
    rf_annual: float = 0.05,
    fractional: float = 0.5,
) -> float | None:
    """Fractional Kelly position size for a single-asset strategy.

    Implements the continuous-time Kelly formula:

        f* = (μ_ann - rf_ann) / σ_ann²

    where μ_ann and σ_ann² are the annualized mean return and variance.
    A fractional Kelly (default 0.5×) is applied to reduce drawdown
    volatility — the theoretical full-Kelly bet is too aggressive for
    practical use and is highly sensitive to estimation error.

    Args:
        daily_returns: Per-bar (daily) return series, un-annualized.
        rf_annual: Annual risk-free rate (default 5%).
        fractional: Kelly multiplier — 0.5 = half-Kelly (recommended),
            1.0 = full Kelly (academic reference only).

    Returns:
        Fractional Kelly weight ∈ (0, 1], clipped to [0, 1] to prevent
        leverage beyond 100%. Returns None if data is insufficient or
        degenerate (< 4 bars, zero variance, negative excess return).
    """
    arr = np.asarray(daily_returns, dtype=float)
    T = len(arr)
    if T < 4:
        return None

    if float(np.ptp(arr)) == 0.0:
        return None

    sigma_daily = float(arr.std(ddof=1))
    if sigma_daily <= 0.0:
        return None

    mu_ann = float(arr.mean()) * _ANNUALIZATION
    sigma_sq_ann = (sigma_daily**2) * _ANNUALIZATION

    excess_return = mu_ann - rf_annual
    if excess_return <= 0.0:
        return 0.0

    f_full = excess_return / sigma_sq_ann
    f_fractional = fractional * f_full

    return round(float(np.clip(f_fractional, 0.0, 1.0)), 6)


# ─── Private helpers ─────────────────────────────────────────────────


def compute_sharpe_ci(
    sharpe_annual: float,
    n_obs_daily: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Lo (2002) confidence interval for annualized Sharpe from daily IID returns.

    Returns (lower, upper) at the requested confidence level.
    """
    if n_obs_daily <= 0:
        raise ValueError(f"n_obs_daily must be positive, got {n_obs_daily}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    sr_daily = sharpe_annual / math.sqrt(_ANNUALIZATION)
    se = math.sqrt((1.0 + 0.5 * sr_daily**2) * _ANNUALIZATION / n_obs_daily)
    z = norm.ppf((1.0 + confidence) / 2.0)
    return (sharpe_annual - z * se, sharpe_annual + z * se)


def _sharpe_per_col(R: np.ndarray) -> np.ndarray:
    """Annualized Sharpe for each column (strategy) of a return matrix."""
    if R.shape[0] < 2:
        return np.zeros(R.shape[1])
    mu = R.mean(axis=0)
    sigma = R.std(axis=0, ddof=1)
    safe_sigma = np.where(sigma > 0, sigma, np.inf)
    return ((mu - _RF_DAILY) / safe_sigma) * math.sqrt(_ANNUALIZATION)


def _ascending_ranks(values: np.ndarray) -> np.ndarray:
    """1-based ranks, ascending order (rank N = highest value)."""
    n = len(values)
    order = np.argsort(values)
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)
    return ranks


# ─── 5. Look-ahead static audit (AST-based) ──────────────────────────

_LOOK_AHEAD_FUNCTIONS = {
    "future",
    "forecast",
    "predict",
    "peek",
    "lookahead",
    "look_ahead",
}


def look_ahead_audit(strategy_code: str) -> tuple[bool, list[str]]:
    """Static-analysis check for look-ahead bias in strategy code.

    Parses the strategy source with AST and checks for:
    1. Forward data access patterns (e.g., self.data.close[+N])
    2. Calls to functions with look-ahead-suggestive names
    3. Direct indexing into data feeds beyond current bar
    4. Negative shifts (e.g., pandas df.shift(-1)) which leak future data.

    Args:
        strategy_code: Python source code of the strategy.

    Returns:
        (passed, warnings) — passed=True if no look-ahead detected.
    """
    warnings: list[str] = []

    try:
        tree = ast.parse(strategy_code)
    except SyntaxError as e:
        return False, [f"Cannot parse strategy code: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = _get_func_name(node.func)
            if func_name and func_name.lower() in _LOOK_AHEAD_FUNCTIONS:
                warnings.append(f"Line {node.lineno}: call to '{func_name}' may indicate look-ahead bias")

            # Check for pandas negative shifts, e.g., shift(-1)
            if func_name == "shift":

                def _is_negative(val_node: ast.AST) -> bool | int | float:
                    if isinstance(val_node, ast.UnaryOp) and isinstance(val_node.op, ast.USub):
                        if isinstance(val_node.operand, ast.Constant) and isinstance(
                            val_node.operand.value, (int, float)
                        ):
                            return val_node.operand.value
                    elif (
                        isinstance(val_node, ast.Constant)
                        and isinstance(val_node.value, (int, float))
                        and val_node.value < 0
                    ):
                        return abs(val_node.value)
                    return False

                # The first positional argument is 'periods'
                if len(node.args) > 0:
                    val = _is_negative(node.args[0])
                    if val is not False:
                        warnings.append(f"Line {node.lineno}: negative shift(-{val}) references future data")
                # Alternatively, check keyword arguments for 'periods'
                for kw in node.keywords:
                    if kw.arg == "periods":
                        val = _is_negative(kw.value)
                        if val is not False:
                            warnings.append(f"Line {node.lineno}: negative shift(-{val}) references future data")

        if isinstance(node, ast.Subscript):
            slice_val = node.slice
            if isinstance(slice_val, ast.UnaryOp) and isinstance(slice_val.op, ast.USub):
                # Negative indices are safe in backtrader ([-N] = N bars ago) but
                # would reference the last row of future data in a pandas DataFrame
                # (df.iloc[-1], df["col"][-1]).  Flag so reviewers can verify the
                # calling context before promotion to Tier-1.
                warnings.append(
                    f"Line {node.lineno}: negative index — verify this is backtrader "
                    f"(bars-ago) not pandas (last-row) access."
                )
            elif isinstance(slice_val, ast.Constant) and isinstance(slice_val.value, int) and slice_val.value > 0:
                warnings.append(
                    f"Line {node.lineno}: positive data index [{slice_val.value}] may reference future bars"
                )

    return len(warnings) == 0, warnings


def _get_func_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


# ─── 6. Rigor Gate — composite check ─────────────────────────────────


class RigorGateResult:
    """Result of running all four selection-bias checks on a strategy."""

    def __init__(
        self,
        strategy_id: str,
        deflated_sharpe: float | None = None,
        dsr_p_value: float | None = None,
        num_trials: int = 1,
        pbo_score: float | None = None,
        oos_sharpe: float | None = None,
        look_ahead_passed: bool = False,
        in_sample_sharpe: float | None = None,
        paper_claimed_sharpe: float | None = None,
        cpcv_mean_oos_sharpe: float | None = None,
        cpcv_positive_fraction: float | None = None,
    ) -> None:
        self.strategy_id = strategy_id
        self.deflated_sharpe = deflated_sharpe
        self.dsr_p_value = dsr_p_value
        self.num_trials = num_trials
        self.pbo_score = pbo_score
        self.oos_sharpe = oos_sharpe
        self.look_ahead_passed = look_ahead_passed
        self.in_sample_sharpe = in_sample_sharpe
        self.paper_claimed_sharpe = paper_claimed_sharpe
        # Combinatorial Purged CV results (None when the series is too short to
        # partition). When present, the gate additionally requires that the
        # strategy's edge holds OOS across a majority of CPCV paths.
        self.cpcv_mean_oos_sharpe = cpcv_mean_oos_sharpe
        self.cpcv_positive_fraction = cpcv_positive_fraction

    @property
    def passes_all(self) -> bool:
        if self.dsr_p_value is None:
            return False
        if self.dsr_p_value < 0.95:
            return False
        if self.pbo_score is None:
            return False
        if self.pbo_score >= 0.5:
            return False
        if self.oos_sharpe is None:
            return False
        if self.oos_sharpe <= 0.0:  # absolute OOS floor: negative OOS cannot pass
            return False
        if self.in_sample_sharpe and self.in_sample_sharpe > 0 and self.oos_sharpe / self.in_sample_sharpe < 0.5:
            return False
        # Combinatorial Purged CV: when computed, the edge must hold OOS across a
        # majority of held-out paths (not just the single 70/30 tail above).
        if self.cpcv_positive_fraction is not None and self.cpcv_positive_fraction < 0.5:
            return False
        return self.look_ahead_passed

    @property
    def gate_details(self) -> dict[str, str]:
        details: dict[str, str] = {}

        if self.dsr_p_value is not None and self.dsr_p_value >= 0.95:
            details["dsr"] = f"PASS (p={self.dsr_p_value:.4f})"
        elif self.dsr_p_value is not None:
            details["dsr"] = f"FAIL (p={self.dsr_p_value:.4f}, need ≥ 0.95)"
        else:
            details["dsr"] = "MISSING"
        # Disclose the Sharpe convention behind the DSR (#547). The backend gate
        # computes excess-return Sharpe; served library fixtures carry their own
        # per-entry "dsr_convention" ("raw" for frozen legacy, "excess" for new).
        details["dsr_convention"] = "excess"

        if self.pbo_score is not None and self.pbo_score < 0.5:
            details["pbo"] = f"PASS (PBO={self.pbo_score:.4f})"
        elif self.pbo_score is not None:
            details["pbo"] = f"FAIL (PBO={self.pbo_score:.4f}, need < 0.5)"
        else:
            details["pbo"] = "MISSING"

        if self.oos_sharpe is not None and self.in_sample_sharpe and self.in_sample_sharpe > 0:
            ratio = self.oos_sharpe / self.in_sample_sharpe
            if ratio >= 0.5:
                details["oos_sharpe"] = f"PASS (OOS/IS={ratio:.2f})"
            else:
                details["oos_sharpe"] = f"FAIL (OOS/IS={ratio:.2f}, need ≥ 0.50)"
        elif self.oos_sharpe is not None:
            details["oos_sharpe"] = f"SET (OOS={self.oos_sharpe:.4f}, no IS reference)"
        else:
            details["oos_sharpe"] = "MISSING"

        if self.cpcv_positive_fraction is not None:
            if self.cpcv_positive_fraction >= 0.5:
                details["cpcv"] = (
                    f"PASS (OOS+ {self.cpcv_positive_fraction:.0%} of paths, "
                    f"mean OOS SR={self.cpcv_mean_oos_sharpe:.2f})"
                )
            else:
                details["cpcv"] = f"FAIL (OOS+ only {self.cpcv_positive_fraction:.0%} of paths, need ≥ 50%)"
        else:
            details["cpcv"] = "MISSING"

        details["look_ahead"] = "PASS" if self.look_ahead_passed else "FAIL"

        return details


def run_rigor_gate(
    strategy_id: str,
    daily_returns: list[float],
    num_trials: int = 1,
    pbo_scores: dict[str, float] | None = None,
    strategy_code: str | None = None,
    in_sample_sharpe: float | None = None,
    paper_claimed_sharpe: float | None = None,
    look_ahead_audit_passed: bool | None = None,
    average_correlation: float = 0.0,
    cv_returns_matrix: np.ndarray | list[list[float]] | None = None,
) -> RigorGateResult:
    """Run all four selection-bias checks on a strategy.

    Main entry point called by the orchestrator and API routes.

    Args:
        average_correlation: Mean pairwise correlation among the ``num_trials``
            trials in the selection set, used by the DSR effective-N correction.
            The caller holds the library/variant returns and computes it via
            ``compute_average_pairwise_correlation``; ``0.0`` (the default)
            applies no relief — conservative for an unknown correlation.
        cv_returns_matrix: A 2-D ``(S, T)`` matrix of per-split out-of-sample
            returns (rows = ``C(n_groups, test_groups)`` combinatorial splits)
            for the CPCV path-stability check. CPCV is mathematically invalid on
            a single static 1-D series, so when no combinatorial paths are
            supplied this stays ``None`` and the CPCV gate is honestly reported
            as ``MISSING`` rather than silently passing.
    """
    if num_trials == 1:
        logger.debug(
            "Rigor gate [%s]: num_trials=1 — no multiple-testing correction. "
            "Pass num_trials=len(strategy_library) for meaningful DSR.",
            strategy_id,
        )

    # 1. DSR — effective-N correction relaxes the multiple-testing penalty when
    #    the trials are correlated (fewer independent bets than the nominal N).
    deflated_sharpe, dsr_p_value = compute_dsr(daily_returns, num_trials, average_correlation)

    # 2. PBO — use pre-computed library-level score
    pbo_score = pbo_scores.get(strategy_id) if pbo_scores else None

    # 3. Walk-forward OOS Sharpe (single holdout) + Combinatorial Purged CV.
    #    CPCV runs only when a real 2-D combinatorial OOS matrix is supplied.
    oos_sharpe = compute_oos_sharpe(daily_returns)
    cpcv = compute_cpcv_oos_sharpe(cv_returns_matrix)

    # 4. Look-ahead audit
    if strategy_code is not None:
        la_passed, la_warnings = look_ahead_audit(strategy_code)
        if la_warnings:
            for w in la_warnings:
                logger.info("Look-ahead audit [%s]: %s", strategy_id, w)
    else:
        la_passed = False

    if look_ahead_audit_passed is not None:
        la_passed = look_ahead_audit_passed

    # Derive in-sample Sharpe from IS slice (first 70%) only — not the full series.
    # Using the full series blends IS+OOS and makes the OOS/IS ratio trivially easy to pass.
    if in_sample_sharpe is None and len(daily_returns) >= 4:
        arr = np.asarray(daily_returns, dtype=float)
        split = int(len(arr) * 0.70)
        is_arr = arr[:split]
        if len(is_arr) >= 2:
            sigma_is = float(is_arr.std(ddof=1))
            if sigma_is > 0:
                in_sample_sharpe = ((float(is_arr.mean()) - _RF_DAILY) / sigma_is) * math.sqrt(_ANNUALIZATION)

    result = RigorGateResult(
        strategy_id=strategy_id,
        deflated_sharpe=deflated_sharpe,
        dsr_p_value=dsr_p_value,
        num_trials=num_trials,
        pbo_score=pbo_score,
        oos_sharpe=oos_sharpe,
        look_ahead_passed=la_passed,
        in_sample_sharpe=in_sample_sharpe,
        paper_claimed_sharpe=paper_claimed_sharpe,
        cpcv_mean_oos_sharpe=cpcv["mean_oos_sharpe"] if cpcv else None,
        cpcv_positive_fraction=cpcv["positive_fraction"] if cpcv else None,
    )

    logger.info(
        "Rigor gate [%s]: %s (DSR p=%s, PBO=%s, OOS=%s, CPCV+=%s, LA=%s)",
        strategy_id,
        "PASS" if result.passes_all else "FAIL",
        dsr_p_value,
        pbo_score,
        oos_sharpe,
        cpcv["positive_fraction"] if cpcv else None,
        la_passed,
    )

    return result


# ─── 6b. Regime-conditional rigor analysis ───────────────────────────


def classify_regimes(
    market_returns: list[float] | np.ndarray,
    vol_window: int = 21,
    n_regimes: int = 2,
) -> np.ndarray:
    """Label each day by volatility regime using rolling realized volatility.

    A strategy's edge may be regime-dependent — strong in calm markets and
    fragile in stressed ones (or vice versa). This labels each bar by the
    *market benchmark's* recent volatility so that ``regime_conditional_*``
    can slice the strategy's own returns by the regime the market was in.

    Method (a deliberately simple vol-quantile proxy):
      1. Compute the rolling standard deviation of ``market_returns`` over a
         trailing ``vol_window``.
      2. **Shift the rolling-vol series by one bar** so the label assigned to
         day *t* uses only volatility realized through day *t − 1*. This avoids
         look-ahead: the regime label for a bar never peeks at that bar's own
         return (which the strategy is being evaluated on for the same day).
      3. Split the (shifted) rolling-vol values into ``n_regimes`` buckets by
         quantile — for ``n_regimes=2``, label 0 = "calm" (rolling-vol at or
         below the median) and label 1 = "stressed" (above the median).
      4. The first ``vol_window`` bars lack a full trailing window (and the
         extra shift consumes one more), so they get label ``-1`` =
         "unclassified" and are excluded from every downstream regime stat.

    This is intentionally a coarse realized-vol regime proxy, NOT a fitted
    regime model. A proper Markov-switching / HMM treatment (Ang & Bekaert
    2002, "International Asset Allocation With Regime Shifts", Review of
    Financial Studies 15(4): 1137-1187 — which motivates conditioning asset
    behavior on latent volatility regimes) is out of scope here; we surface a
    transparent, reproducible vol bucketing instead of an opaque fitted state.

    Args:
        market_returns: Per-bar benchmark return series (the regime driver).
        vol_window: Trailing window (bars) for realized volatility. Default 21
            (~one trading month).
        n_regimes: Number of volatility buckets (>= 1). Labels are
            ``0 .. n_regimes-1`` in ascending volatility order.

    Returns:
        Integer ``np.ndarray`` of length ``len(market_returns)``. Entries are
        ``-1`` for unclassified leading bars, else the regime id in
        ``0 .. n_regimes-1``. Returns an all-``-1`` array (no crash) when the
        series is too short to form a single full window or ``n_regimes < 1``.
    """
    arr = np.asarray(market_returns, dtype=float)
    T = len(arr)
    labels = np.full(T, -1, dtype=int)

    if T == 0 or n_regimes < 1 or vol_window < 1:
        return labels

    # Rolling std (ddof=1) over a trailing window; entries before a full window
    # exist remain NaN. Build via a simple stride-free loop for numpy-only clarity.
    roll_vol = np.full(T, np.nan, dtype=float)
    for i in range(vol_window - 1, T):
        window = arr[i - vol_window + 1 : i + 1]
        if window.size >= 2:
            roll_vol[i] = float(window.std(ddof=1))

    # Shift by one bar so day t's label uses vol realized through t-1 (no look-ahead).
    shifted = np.full(T, np.nan, dtype=float)
    shifted[1:] = roll_vol[:-1]

    valid_mask = np.isfinite(shifted)
    valid_vals = shifted[valid_mask]
    if valid_vals.size == 0:
        return labels

    if n_regimes == 1:
        labels[valid_mask] = 0
        return labels

    # Quantile cut-points partition the valid rolling-vol values into n_regimes
    # buckets of (approximately) equal mass. np.digitize maps each value to a
    # bucket in 0 .. n_regimes-1. A degenerate (constant-vol) series yields
    # identical edges; digitize then collapses everything into a single bucket
    # without crashing.
    quantiles = np.quantile(valid_vals, np.linspace(0.0, 1.0, n_regimes + 1)[1:-1])
    bucket = np.digitize(valid_vals, quantiles, right=False)
    bucket = np.clip(bucket, 0, n_regimes - 1).astype(int)
    labels[valid_mask] = bucket
    return labels


def regime_conditional_sharpe(
    strategy_returns: list[float] | np.ndarray,
    regime_labels: list[int] | np.ndarray,
) -> dict[int, dict]:
    """Per-regime annualized Sharpe (and mean/vol/count) of a strategy.

    Slices the strategy's own daily returns by the market regime each day fell
    in (per ``classify_regimes``) and reports the strategy's annualized Sharpe,
    annualized mean return, annualized vol, and day-count within each regime.

    Args:
        strategy_returns: Per-bar strategy return series.
        regime_labels: Integer regime labels aligned to the same bars (``-1``
            for unclassified). Truncated to the shorter of the two lengths.

    Returns:
        ``{regime_id: {"sharpe", "ann_return", "ann_vol", "n_days"}}`` for each
        regime id present (excluding ``-1``). ``sharpe`` is ``None`` for any
        regime with < 2 days or zero variance. Empty dict if no classified days.
    """
    s = np.asarray(strategy_returns, dtype=float)
    r = np.asarray(regime_labels, dtype=int)
    n = min(len(s), len(r))
    if n == 0:
        return {}
    s = s[:n]
    r = r[:n]

    out: dict[int, dict] = {}
    for regime_id in sorted({int(x) for x in r if int(x) != -1}):
        sub = s[r == regime_id]
        n_days = int(sub.size)
        if n_days < 2 or float(np.ptp(sub)) == 0.0:
            out[regime_id] = {
                "sharpe": None,
                "ann_return": round(float(sub.mean()) * _ANNUALIZATION, 6) if n_days >= 1 else None,
                "ann_vol": 0.0 if n_days >= 1 else None,
                "n_days": n_days,
            }
            continue
        sigma = float(sub.std(ddof=1))
        sharpe = _annualized_sharpe_arr(sub)
        out[regime_id] = {
            "sharpe": round(sharpe, 6) if sharpe is not None else None,
            "ann_return": round(float(sub.mean()) * _ANNUALIZATION, 6),
            "ann_vol": round(sigma * math.sqrt(_ANNUALIZATION), 6),
            "n_days": n_days,
        }
    return out


def regime_robustness_score(
    strategy_returns: list[float] | np.ndarray,
    regime_labels: list[int] | np.ndarray,
) -> dict:
    """Regime-fragility score — does the edge survive across volatility regimes?

    A strategy that earns its Sharpe in only one regime (e.g. only in calm
    markets) is fragile: the moment the market shifts, the edge evaporates.
    This surfaces that fragility *transparently* rather than burying it behind
    a single aggregate Sharpe, consistent with the repo's honest-framing
    principle (paper-claim deltas and per-regime numbers are shown, not hidden).

    Motivation: Ang & Bekaert (2002), "International Asset Allocation With
    Regime Shifts", Review of Financial Studies 15(4): 1137-1187 — asset
    behavior (and therefore a strategy's edge) is regime-dependent, so a single
    full-sample Sharpe can mask regime-specific failure.

    Args:
        strategy_returns: Per-bar strategy return series.
        regime_labels: Integer regime labels aligned to the same bars.

    Returns:
        Dict with keys:
          ``per_regime``        — the ``regime_conditional_sharpe`` dict.
          ``min_regime_sharpe`` — lowest per-regime Sharpe (None if none computable).
          ``max_regime_sharpe`` — highest per-regime Sharpe (None if none computable).
          ``sharpe_dispersion`` — ``max - min`` (None if < 2 computable regimes).
          ``consistency``       — a ``[0, 1]`` score; high = the edge holds across
            regimes. Convention: when ``max > 0`` it is
            ``min(1, max(0, min_sharpe / max_sharpe))`` (so a regime with
            negative or near-zero Sharpe drives consistency toward 0). When
            ``max <= 0`` (the strategy is non-positive in *every* regime) there
            is no regime in which it works, so consistency is ``0.0``.
          ``robust``            — ``bool``: the strict honest gate
            ``min_regime_sharpe > 0`` (positive Sharpe in *every* classified
            regime). ``False`` when no regimes are computable.
    """
    per_regime = regime_conditional_sharpe(strategy_returns, regime_labels)
    sharpes = [v["sharpe"] for v in per_regime.values() if v.get("sharpe") is not None]

    if not sharpes:
        return {
            "per_regime": per_regime,
            "min_regime_sharpe": None,
            "max_regime_sharpe": None,
            "sharpe_dispersion": None,
            "consistency": 0.0,
            "robust": False,
        }

    min_sharpe = float(min(sharpes))
    max_sharpe = float(max(sharpes))
    dispersion = round(max_sharpe - min_sharpe, 6) if len(sharpes) >= 2 else None

    if max_sharpe > 0.0:
        consistency = min(1.0, max(0.0, min_sharpe / max_sharpe))
    else:
        # Non-positive in every regime: there is no regime in which the edge
        # works, so there is no consistency to credit.
        consistency = 0.0

    return {
        "per_regime": per_regime,
        "min_regime_sharpe": round(min_sharpe, 6),
        "max_regime_sharpe": round(max_sharpe, 6),
        "sharpe_dispersion": dispersion,
        "consistency": round(float(consistency), 6),
        "robust": bool(min_sharpe > 0.0),
    }


def regime_conditional_dsr(
    strategy_returns: list[float] | np.ndarray,
    regime_labels: list[int] | np.ndarray,
    num_trials: int = 1,
) -> dict[int, dict]:
    """Per-regime Deflated Sharpe Ratio — does the DSR evidence hold within each regime?

    Runs the existing ``compute_dsr`` on the strategy's return subset *within*
    each market regime, so the deflated-Sharpe evidence can be inspected regime
    by regime rather than only on the blended full sample. Reuses ``compute_dsr``
    directly, so the same minimum-length guard (T < 4 → ``None``) applies per
    regime subset — a regime with too few bars reports ``None`` DSR honestly
    instead of fabricating significance from a handful of points.

    Args:
        strategy_returns: Per-bar strategy return series.
        regime_labels: Integer regime labels aligned to the same bars.
        num_trials: Number of trials in the selection set, passed through to
            ``compute_dsr`` for the multiple-testing correction (default 1).

    Returns:
        ``{regime_id: {"deflated_sharpe", "dsr_p_value", "n_days"}}`` for each
        regime id present (excluding ``-1``). ``deflated_sharpe`` and
        ``dsr_p_value`` are ``None`` when the regime subset is too short or
        degenerate. Empty dict if no classified days.
    """
    s = np.asarray(strategy_returns, dtype=float)
    r = np.asarray(regime_labels, dtype=int)
    n = min(len(s), len(r))
    if n == 0:
        return {}
    s = s[:n]
    r = r[:n]

    out: dict[int, dict] = {}
    for regime_id in sorted({int(x) for x in r if int(x) != -1}):
        sub = s[r == regime_id]
        dsr, p_val = compute_dsr(sub, num_trials)
        out[regime_id] = {
            "deflated_sharpe": dsr,
            "dsr_p_value": p_val,
            "n_days": int(sub.size),
        }
    return out


# ─── 7. Monte Carlo DSR significance via circular block bootstrap ─────


def _circular_block_bootstrap(
    arr: np.ndarray,
    block_size: int,
    n_trials: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Circular block bootstrap sample generator.

    For each of the *n_trials* bootstrap replications, tiles
    ``ceil(T / block_size)`` randomly-chosen blocks of length *block_size*
    (wrapping circularly at the boundary), then truncates to the original
    length T.

    Reference: Politis, D.N. & Romano, J.P. (1992). "A circular block-
    resampling procedure for stationary data." In *Exploring the Limits of
    Bootstrap* (pp. 263-270). Wiley, New York.

    Args:
        arr: 1-D array of length T — the original return series.
        block_size: Length of each contiguous block. Should be roughly
            proportional to sqrt(T) for short-range-dependent series
            (Politis & Romano 1992 recommend b = O(T^{1/3}) to O(T^{1/2})).
        n_trials: Number of bootstrap replications.
        rng: A seeded ``np.random.Generator`` (from ``np.random.default_rng``).

    Returns:
        Float array of shape (n_trials, T).
    """
    T = len(arr)
    n_blocks = math.ceil(T / block_size)
    # Draw random start positions for each block in each trial (circular)
    starts = rng.integers(0, T, size=(n_trials, n_blocks))  # shape (n_trials, n_blocks)

    # Build index array for a single block: [start, start+1, ..., start+block_size-1] mod T
    offsets = np.arange(block_size)  # shape (block_size,)
    # indices[t, b, o] = (starts[t, b] + o) % T
    indices = (starts[:, :, np.newaxis] + offsets[np.newaxis, np.newaxis, :]) % T  # (n_trials, n_blocks, block_size)

    # Flatten blocks per trial, then truncate to T
    flat_indices = indices.reshape(n_trials, n_blocks * block_size)[:, :T]  # (n_trials, T)
    return arr[flat_indices]  # (n_trials, T)


def monte_carlo_dsr_pvalue(
    returns: list[float],
    dsr_threshold: float,
    n_trials: int = 1000,
    block_size: int = 20,
    seed: int = 42,
) -> dict[str, float]:
    """Block-bootstrap significance test for a Sharpe ratio under a null.

    Tests the one-sided hypothesis H0: true (annualized) Sharpe ≤ *dsr_threshold*
    against H1: Sharpe > *dsr_threshold*, using a circular block bootstrap
    (Politis & Romano 1992) that preserves the short-range serial dependence in
    daily returns.

    Why a NULL-imposed bootstrap (not naive resampling of the raw series):
    resampling the observed series directly produces a bootstrap Sharpe
    distribution centred on the *observed* Sharpe, so ``P(bootstrap ≥ observed)``
    is ≈ 0.5 regardless of how strong the strategy is — useless as a
    significance test. Instead we shift the series to satisfy the null exactly
    and ask how often that null world reproduces a Sharpe as large as observed.
    This is the standard bootstrap-hypothesis-test construction (Davison &
    Hinkley 1997, §4.2; Ledoit & Wolf 2008 apply the same null-imposition idea
    to robust Sharpe-ratio inference).

    Algorithm:
      1. Compute the observed annualized Sharpe of *returns*.
      2. Build a null series with the SAME variance and autocovariance but a
         mean set so its annualized Sharpe equals *dsr_threshold* exactly:
         ``r_null = r - mean(r) + rf_daily + threshold_daily``, where
         ``threshold_daily = dsr_threshold / sqrt(252) * sigma``. (With
         ``dsr_threshold = 0`` this is the classic zero-excess-return null.)
      3. Draw *n_trials* circular-block-bootstrap replicates of ``r_null`` and
         compute each replicate's annualized Sharpe.
      4. Empirical one-sided p-value = fraction of NULL bootstrap Sharpes ≥ the
         observed Sharpe. A low p-value (< 0.05) means a world whose true Sharpe
         is exactly *dsr_threshold* would rarely produce a Sharpe this high by
         chance given the data's own dependence structure.

    Reference for block bootstrap: Politis, D.N. & Romano, J.P. (1992).
    "A circular block-resampling procedure for stationary data." In *Exploring
    the Limits of Bootstrap* (pp. 263-270). Wiley, New York. Null-imposition
    for hypothesis testing: Davison & Hinkley (1997), *Bootstrap Methods and
    their Application*, §4.2.

    Args:
        returns: Daily (per-bar) return series, un-annualized.
        dsr_threshold: The annualized Sharpe the null is pinned to (e.g. 0.0 to
            test "any positive skill", or a higher hurdle). Now USED — it defines
            the null world, not just metadata.
        n_trials: Number of bootstrap replications (default 1 000).
        block_size: Block length for circular block bootstrap (default 20 bars ≈
            one trading month). Rule of thumb: block_size ≈ T^{1/3} to T^{1/2}.
        seed: Random seed for reproducibility (default 42).

    Returns:
        Dict with keys:
          ``pvalue`` — one-sided fraction of NULL bootstrap Sharpes ≥ observed.
          ``observed_sharpe`` — the annualized Sharpe of the input series.
          ``bootstrap_sharpe_mean`` — mean of the null bootstrap Sharpe dist
            (should sit near *dsr_threshold* by construction).
          ``bootstrap_sharpe_std`` — std of the null bootstrap Sharpe dist.
          ``n_trials`` — number of bootstrap replications actually run.
          ``passes_at_5pct`` — True iff pvalue < 0.05 (one-sided, 5% level).
        All float values are NaN if the return series is degenerate (< 4 bars or
        zero variance).
    """
    _nan_result: dict[str, float] = {
        "pvalue": float("nan"),
        "observed_sharpe": float("nan"),
        "bootstrap_sharpe_mean": float("nan"),
        "bootstrap_sharpe_std": float("nan"),
        "n_trials": float(n_trials),
        "passes_at_5pct": float(False),
    }

    arr = np.asarray(returns, dtype=float)
    T = len(arr)
    if T < 4 or float(np.ptp(arr)) == 0.0:
        return _nan_result

    sigma = float(arr.std(ddof=1))
    if sigma <= 0.0:
        return _nan_result

    # Observed annualized Sharpe
    observed_sharpe = float(((arr.mean() - _RF_DAILY) / sigma) * math.sqrt(_ANNUALIZATION))

    # ── Impose the null: shift the series so its annualized Sharpe == dsr_threshold,
    # preserving variance and (block-)autocovariance. threshold expressed back in
    # daily-excess terms is (dsr_threshold / sqrt(252)) * sigma.
    threshold_daily_excess = (dsr_threshold / math.sqrt(_ANNUALIZATION)) * sigma
    null_arr = arr - arr.mean() + _RF_DAILY + threshold_daily_excess

    rng = np.random.default_rng(seed)
    bs_samples = _circular_block_bootstrap(null_arr, block_size=block_size, n_trials=n_trials, rng=rng)
    # shape: (n_trials, T)

    bs_means = bs_samples.mean(axis=1)
    bs_stds = bs_samples.std(axis=1, ddof=1)
    # Avoid division by zero
    safe_stds = np.where(bs_stds > 0, bs_stds, np.inf)
    bs_sharpes = ((bs_means - _RF_DAILY) / safe_stds) * math.sqrt(_ANNUALIZATION)

    # One-sided empirical p-value under H0: P(null Sharpe >= observed Sharpe)
    pvalue = float(np.mean(bs_sharpes >= observed_sharpe))
    bs_mean = float(np.mean(bs_sharpes[np.isfinite(bs_sharpes)]))
    bs_std = float(np.std(bs_sharpes[np.isfinite(bs_sharpes)], ddof=1)) if np.isfinite(bs_sharpes).sum() > 1 else 0.0

    return {
        "pvalue": round(pvalue, 6),
        "observed_sharpe": round(observed_sharpe, 6),
        "bootstrap_sharpe_mean": round(bs_mean, 6),
        "bootstrap_sharpe_std": round(bs_std, 6),
        "n_trials": float(n_trials),
        "passes_at_5pct": float(pvalue < 0.05),
    }


# ─── 8. Multiple-testing corrections ─────────────────────────────────


def benjamini_hochberg_fdr(
    pvalues: list[float],
    fdr_level: float = 0.05,
) -> dict[str, Any]:
    """Benjamini-Hochberg False Discovery Rate correction.

    Controls the expected proportion of false discoveries among the rejected
    hypotheses at level *fdr_level*. BH is uniformly more powerful than
    Bonferroni for independent or positively dependent tests, which makes it
    the preferred correction when evaluating a library of strategies (where
    strategies sharing the same universe tend to have positive return
    correlations).

    Algorithm (Benjamini & Hochberg 1995, Theorem 1):
      1. Sort p-values ascending: p_(1) ≤ p_(2) ≤ … ≤ p_(m).
      2. BH critical value for rank k: q_k = (k / m) × α.
      3. Find the largest k* such that p_(k*) ≤ q_(k*).
      4. Reject all hypotheses with rank ≤ k* (i.e. all p ≤ p_(k*)).
      5. BH-adjusted p-values: p̃_k = min(1, p_k × m / k), enforced to be
         monotone non-decreasing in rank order (step-down adjustment).

    Reference: Benjamini, Y. & Hochberg, Y. (1995). "Controlling the false
    discovery rate: a practical and powerful approach to multiple testing."
    *Journal of the Royal Statistical Society. Series B*, 57(1), 289-300.

    Application to backtesting: Bailey, D.H., Borwein, J., López de Prado, M.,
    & Zhu, Q. (2014). "The Probability of Backtest Overfitting." *Journal of
    Computational Finance*, 20(4), 39-70.

    Args:
        pvalues: List of m p-values (one per strategy / hypothesis).
        fdr_level: Target FDR (α). Default 0.05.

    Returns:
        Dict with keys:
          ``rejected``         — list[bool] of length m in the original input order.
          ``bh_critical_values`` — list[float] of BH thresholds q_k in original order.
          ``n_rejected``       — number of hypotheses rejected.
          ``adjusted_pvalues`` — BH-adjusted p-values in the original input order.
    """
    m = len(pvalues)
    if m == 0:
        return {"rejected": [], "bh_critical_values": [], "n_rejected": 0, "adjusted_pvalues": []}

    arr = np.asarray(pvalues, dtype=float)
    # Sort ascending, track original positions
    sort_order = np.argsort(arr)
    sorted_p = arr[sort_order]

    ranks = np.arange(1, m + 1, dtype=float)
    bh_crit = (ranks / m) * fdr_level

    # Largest k where sorted_p[k-1] <= bh_crit[k-1]
    below_threshold = sorted_p <= bh_crit
    if np.any(below_threshold):
        k_star = int(np.where(below_threshold)[0][-1])  # 0-based index of last True
    else:
        k_star = -1  # nothing rejected

    reject_sorted = np.zeros(m, dtype=bool)
    if k_star >= 0:
        reject_sorted[: k_star + 1] = True

    # BH-adjusted p-values in sorted order: p̃_k = min(1, p_k × m / k)
    # Enforce monotone non-decreasing via cummin from the last rank
    adjusted_sorted = np.minimum(1.0, sorted_p * (m / ranks))
    # Step-down monotonicity: p̃_k ≤ p̃_{k+1} in sorted order (adjust from top)
    for i in range(m - 2, -1, -1):
        adjusted_sorted[i] = min(adjusted_sorted[i], adjusted_sorted[i + 1])

    # Map back to original input order
    inv_order = np.empty(m, dtype=int)
    inv_order[sort_order] = np.arange(m)

    rejected_orig = reject_sorted[inv_order].tolist()
    bh_crit_orig = bh_crit[inv_order].tolist()
    adjusted_orig = adjusted_sorted[inv_order].tolist()

    return {
        "rejected": rejected_orig,
        "bh_critical_values": [round(v, 8) for v in bh_crit_orig],
        "n_rejected": int(np.sum(reject_sorted)),
        "adjusted_pvalues": [round(v, 8) for v in adjusted_orig],
    }


def bonferroni_correction(
    pvalues: list[float],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Bonferroni multiple-testing correction.

    The most conservative family-wise error rate (FWER) control: multiply each
    p-value by the total number of tests m, then compare to α. Equivalent to
    testing each hypothesis at level α/m — the FWER is then controlled at α
    under arbitrary dependence structure.

    Bonferroni is overly conservative when tests are positively correlated
    (the typical case in a strategy library), which is why Benjamini-Hochberg
    FDR is preferred for discovery. Bonferroni is appropriate when even a
    *single* false positive is unacceptable — e.g. live capital allocation to
    a new strategy that has never traded.

    Reference (textbook): Bonferroni, C.E. (1936). "Teoria statistica delle
    classi e calcolo delle probabilità." *Pubblicazioni del R Istituto Superiore
    di Scienze Economiche e Commerciali di Firenze*, 8, 3-62.
    Application to backtesting: Bailey et al. (2014), "The Probability of
    Backtest Overfitting." *Journal of Computational Finance*, 20(4), 39-70.

    Args:
        pvalues: List of m p-values.
        alpha: Family-wise error rate target (default 0.05).

    Returns:
        Dict with keys:
          ``rejected``        — list[bool] in the original input order.
          ``adjusted_pvalues`` — Bonferroni-adjusted p-values (min(1, p × m)).
          ``n_rejected``      — number of hypotheses rejected.
    """
    m = len(pvalues)
    if m == 0:
        return {"rejected": [], "adjusted_pvalues": [], "n_rejected": 0}

    arr = np.asarray(pvalues, dtype=float)
    adjusted = np.minimum(1.0, arr * m)
    rejected = (adjusted <= alpha).tolist()

    return {
        "rejected": rejected,
        "adjusted_pvalues": [round(float(v), 8) for v in adjusted],
        "n_rejected": int(np.sum(rejected)),
    }
