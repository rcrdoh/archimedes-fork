"""Selection-bias corrections: DSR, PBO, walk-forward OOS Sharpe, look-ahead audit.

Implements the four-primitive admission gate that separates Tier-1 (Archimedes
Verified) strategies from curve-fit noise:

  1. Deflated Sharpe Ratio — Bailey & López de Prado (2014)
  2. Probability of Backtest Overfitting via CSCV — Bailey et al. (2014)
  3. Out-of-sample Sharpe — single chronological hold-out today (see
     compute_oos_sharpe); rolling Combinatorial Purged CV (compute_cpcv_oos_sharpe)
     is the principled upgrade, wired once a combinatorial OOS matrix exists
  4. Look-ahead static audit (AST-based)

Pure computation and orchestration: no I/O, no web framework, no on-chain
dependencies. Arithmetic helpers extracted to _rigor_helpers module for clarity.

Owner: Önder (math lane)
Spec:  docs/specs/selection-bias-corrections-spec.md
"""

from __future__ import annotations

import ast
import logging
import math

import numpy as np

from archimedes.services._rigor_helpers import (
    _ANNUALIZATION,
    _RF_DAILY,
    benjamini_hochberg_fdr,
    bonferroni_correction,
    classify_regimes,
    compute_average_pairwise_correlation,
    compute_cpcv_oos_sharpe,
    compute_dsr,
    compute_in_sample_sharpe,
    compute_kelly_fraction,
    compute_oos_sharpe,
    compute_pbo,
    compute_sharpe_ci,
    monte_carlo_dsr_pvalue,
    regime_conditional_dsr,
    regime_conditional_sharpe,
    regime_robustness_score,
)

logger = logging.getLogger(__name__)


# ─── Look-ahead static audit (AST-based) ──────────────────────────────

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
        # NaN-hardening: every IEEE-754 comparison against NaN is False, so a NaN
        # metric (not None — None is guarded) would silently skip its fail branch
        # and let an under-credentialed strategy pass. Treat any non-finite metric
        # as an automatic fail. pbo_score is sourced from an external dict; oos/IS
        # Sharpe can carry NaN if upstream returns contain NaN.
        if self.dsr_p_value is None or not math.isfinite(self.dsr_p_value):
            return False
        if self.dsr_p_value < 0.95:
            return False
        if self.pbo_score is None or not math.isfinite(self.pbo_score):
            return False
        if self.pbo_score >= 0.5:
            return False
        if self.oos_sharpe is None or not math.isfinite(self.oos_sharpe):
            return False
        if self.oos_sharpe <= 0.0:  # absolute OOS floor: negative OOS cannot pass
            return False
        if (
            self.in_sample_sharpe is not None
            and math.isfinite(self.in_sample_sharpe)
            and self.in_sample_sharpe > 0
            and self.oos_sharpe / self.in_sample_sharpe < 0.5
        ):
            return False
        # Combinatorial Purged CV: when computed, the edge must hold OOS across a
        # majority of held-out paths (not just the single 70/30 tail above).
        if self.cpcv_positive_fraction is not None and (
            not math.isfinite(self.cpcv_positive_fraction) or self.cpcv_positive_fraction < 0.5
        ):
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
