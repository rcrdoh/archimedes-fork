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
    benjamini_hochberg_fdr,  # noqa: F401 - re-exported for test_rigor_evaluator
    bonferroni_correction,  # noqa: F401 - re-exported for test_rigor_evaluator
    classify_regimes,  # noqa: F401 - re-exported for test_rigor_regime
    compute_average_pairwise_correlation,  # noqa: F401 - re-exported for fusion_evaluator/selection_bias_routes
    compute_cpcv_oos_sharpe,
    compute_dsr,
    compute_in_sample_sharpe,  # noqa: F401 - re-exported for fusion_evaluator
    compute_oos_sharpe,
    compute_pbo,  # used by compute_library_pbo below + re-exported (fusion/generation/test_pbo_parity)
    compute_sharpe_ci,  # noqa: F401 - re-exported for strategy_provider
    monte_carlo_dsr_pvalue,  # noqa: F401 - re-exported for test_rigor_evaluator
    regime_conditional_dsr,  # noqa: F401 - re-exported for test_rigor_regime
    regime_conditional_sharpe,  # noqa: F401 - re-exported for test_rigor_regime
    regime_robustness_score,  # noqa: F401 - re-exported for test_rigor_regime
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


# ─── Library-level PBO (criterion-4 input, #546) ──────────────────────


def align_returns_store(
    returns_store: dict[str, dict[str, list]],
) -> dict[str, list[float]]:
    """Inner-join dated return series on ISO dates → an aligned PBO matrix.

    Mirrors ``analytics-engine/scripts/compute_library_pbo.py::build_aligned_matrix``
    so the backend gate and the offline diagnostic compute the library PBO from
    the *same* alignment. The library's strategies trade different calendars
    (^N225 vs SPY vs joined pair windows); CSCV requires that row *i* of the
    returns matrix means the same trading day for every strategy, so we keep
    only the dates present in *every* series before handing off to
    ``compute_pbo`` (which itself only truncates to the shortest length).

    Args:
        returns_store: ``{strategy_stem: {"dates": [...], "daily_returns": [...]}}``
            — one entry per library strategy, each carrying a 1:1 dated series
            (the shape of ``analytics-engine/strategies/daily_returns/<stem>.json``).
            The caller loads it; this module stays I/O-free.

    Returns:
        ``{strategy_stem: returns_on_joint_dates}`` — date-aligned, ready for
        ``compute_pbo``. Returns ``{}`` when fewer than two usable series are
        supplied or the dated intersection is empty (the caller fail-closes on
        the empty matrix — see ``compute_library_pbo``).
    """
    series = {stem: rec for stem, rec in returns_store.items() if rec.get("dates") and rec.get("daily_returns")}
    if len(series) < 2:
        return {}

    date_sets = [set(rec["dates"]) for rec in series.values()]
    joint = sorted(set.intersection(*date_sets))
    if not joint:
        return {}

    matrix: dict[str, list[float]] = {}
    for stem, rec in series.items():
        # strict=True (matching the offline build_aligned_matrix) fails loud on a
        # malformed record whose dates/daily_returns lengths disagree, rather than
        # silently truncating and risking a misaligned row / KeyError on join.
        by_date = dict(zip(rec["dates"], rec["daily_returns"], strict=True))
        matrix[stem] = [float(by_date[d]) for d in joint]
    return matrix


def compute_library_pbo(
    returns_store: dict[str, dict[str, list]],
    s_partitions: int = 16,
) -> float | None:
    """Single library-level CSCV PBO over the whole selection set (#546).

    This is the criterion-4 input for ``run_rigor_gate``: PBO is a property of
    the *selection set*, not of an individual strategy (Bailey et al. 2014), so
    the principled gate input is one library-wide value, not a per-cohort score.
    Date-aligns the store via ``align_returns_store`` then runs the same
    parity-tested ``compute_pbo`` the cohort path uses.

    **Refresh policy (gate-affecting — documented in docs/specs/library-pbo.md).**
    CSCV PBO is a property of the selection set: adding, removing, or re-running
    any library strategy changes it. The caller MUST recompute (call this
    function afresh) whenever the selection set changes — i.e. on every library
    add, removal, or daily-returns-store regeneration — and MUST NOT freeze the
    value into a per-strategy fixture. The store is add-only + idempotent
    (``gen_daily_returns_store.py``), so "selection set changed" reduces to "a
    new ``daily_returns/<stem>.json`` exists"; recomputing on store growth is
    the cadence.

    Args:
        returns_store: ``{strategy_stem: {"dates": [...], "daily_returns": [...]}}``.
        s_partitions: Number of equal time-partitions S (even ≥ 2; default 16,
            the paper's recommended value).

    Returns:
        The single library PBO ∈ [0, 1], or ``None`` when it cannot be computed
        (fewer than two aligned series, empty date intersection, a joint window
        shorter than ``s_partitions``, or a degenerate ``compute_pbo`` result).
        ``None`` is the fail-closed signal: the gate treats a missing/non-finite
        library PBO as criterion-4 FAIL rather than silently passing. A
        non-finite value (should never arise from the rounded ``compute_pbo``
        output, but guarded for safety) also returns ``None``.
    """
    matrix = align_returns_store(returns_store)
    if len(matrix) < 2:
        return None

    # Fail closed on a too-short joint window. compute_pbo returns an all-0.0
    # sentinel (a spurious criterion-4 PASS, PBO < 0.5) when rows_per_block =
    # T // s_partitions < 1 — i.e. fewer joint dates than partitions. That 0.0
    # is non-finite-clean but meaningless, so guard it here: an under-length
    # window is non-computable, which must FAIL criterion 4, not pass it.
    shortest = min(len(r) for r in matrix.values())
    if shortest // s_partitions < 1:
        return None

    scores = compute_pbo(matrix, s_partitions=s_partitions)
    if not scores:
        return None

    # compute_pbo attaches the same library-level value to every member; take any.
    pbo = next(iter(scores.values()))
    if pbo is None or not math.isfinite(pbo):
        return None
    return float(pbo)


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
        pbo_source: str = "cohort",
    ) -> None:
        self.strategy_id = strategy_id
        self.deflated_sharpe = deflated_sharpe
        self.dsr_p_value = dsr_p_value
        self.num_trials = num_trials
        self.pbo_score = pbo_score
        # Which selection set produced the criterion-4 PBO: "library" when the
        # full-library CSCV PBO was supplied (the principled Bailey et al. input,
        # #546), "cohort" when it fell back to the per-cohort dict score. Surfaced
        # in gate_details so the verdict is honest about its provenance.
        self.pbo_source = pbo_source
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
        # as an automatic fail. pbo_score is sourced either from the full-library
        # CSCV PBO (#546, the principled input) or — fallback — an external cohort
        # dict; oos/IS Sharpe can carry NaN if upstream returns contain NaN.
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

        # Criterion 4 input provenance (#546): "library" = full-library CSCV PBO
        # (the principled Bailey et al. selection-set input), "cohort" = the
        # per-cohort dict score. Disclosed so the verdict states which set fed it.
        if self.pbo_score is not None and math.isfinite(self.pbo_score) and self.pbo_score < 0.5:
            details["pbo"] = f"PASS (PBO={self.pbo_score:.4f}, source={self.pbo_source})"
        elif self.pbo_score is not None and math.isfinite(self.pbo_score):
            details["pbo"] = f"FAIL (PBO={self.pbo_score:.4f}, need < 0.5, source={self.pbo_source})"
        else:
            details["pbo"] = f"MISSING (source={self.pbo_source})"

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
    library_pbo: float | None = None,
) -> RigorGateResult:
    """Run all four selection-bias checks on a strategy.

    Main entry point called by the orchestrator and API routes.

    Args:
        library_pbo: The single full-library CSCV PBO (Bailey et al. 2014) for
            the *current selection set* — the principled criterion-4 input
            (#546). PBO is a property of the whole library, not of one strategy,
            so when this is supplied it is used for criterion 4 in preference to
            the per-cohort ``pbo_scores`` lookup. Compute it from the
            daily-returns store via ``compute_library_pbo`` and recompute on
            every selection-set change (see that function's refresh-policy note).
            Fail-closed: ``None`` (or a non-finite value) makes criterion 4 FAIL
            rather than silently pass — exactly as a missing cohort score does.
            When ``None``, the gate falls back to ``pbo_scores.get(strategy_id)``
            and the verdict is labelled ``source=cohort``.
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

    # 2. PBO (criterion 4 in the gate ordering) — prefer the full-library CSCV
    #    PBO when supplied (#546). PBO is a property of the selection set, not of
    #    one strategy (Bailey et al. 2014), so the library-wide value is the
    #    principled input; the per-cohort dict is the fallback when no library
    #    PBO is passed. Fail-closed semantics live in RigorGateResult.passes_all:
    #    a None/NaN pbo_score fails criterion 4 regardless of source.
    if library_pbo is not None:
        pbo_score = library_pbo
        pbo_source = "library"
    else:
        pbo_score = pbo_scores.get(strategy_id) if pbo_scores else None
        pbo_source = "cohort"

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
        pbo_source=pbo_source,
    )

    logger.info(
        "Rigor gate [%s]: %s (DSR p=%s, PBO=%s [%s], OOS=%s, CPCV+=%s, LA=%s)",
        strategy_id,
        "PASS" if result.passes_all else "FAIL",
        dsr_p_value,
        pbo_score,
        pbo_source,
        oos_sharpe,
        cpcv["positive_fraction"] if cpcv else None,
        la_passed,
    )

    return result
