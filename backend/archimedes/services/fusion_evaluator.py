"""Fusion evaluator — spec → interpreter → backtest → rigor gate → library upsert.

Orchestrates the full pipeline for fusion-generated strategies:
1. Validate the strategy_spec from the fusion proposal
2. Interpret it into a backtrader.Strategy subclass
3. Run a backtest
4. Apply the rigor gate (DSR, PBO, OOS Sharpe, look-ahead audit)
5. Persist the result in the strategy library
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from archimedes.services.dsl_to_backtrader import interpret_spec, interpret_variant
from archimedes.services.rigor_evaluator import (
    compute_average_pairwise_correlation,
    compute_dsr,
    compute_in_sample_sharpe,
    compute_oos_sharpe,
    compute_pbo,
)
from archimedes.services.strategy_dsl import (
    DSLError,
    StrategySpec,
    validate_strategy_spec,
)

logger = logging.getLogger(__name__)

# ── Result types ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class BacktestMetrics:
    """Metrics from a DSL-interpreted strategy backtest."""

    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    cagr: float
    calmar_ratio: float
    win_rate: float
    total_trades: int
    avg_holding_period_days: float
    equity_curve: list[float]
    monthly_returns: list[float]
    backtest_start: date | None
    backtest_end: date | None
    # Provenance of the price series the metrics were computed on. "synthetic"
    # means random.gauss noise (dev/test only); "csv:<name>" / "provided" mean
    # real OHLCV. Rigor metrics from a "synthetic" run are NOT admissible.
    data_source: str = "synthetic"


@dataclass(frozen=True)
class RigorVerdict:
    """Result of applying the rigor gate to fusion output."""

    passing: bool
    dsr: float | None
    dsr_p_value: float | None
    pbo_score: float | None
    oos_sharpe: float | None
    # True for every spec that reaches this evaluator: validate_strategy_spec
    # rejects look_ahead_safe=False before a backtest ever runs, so this is
    # always True in practice. It is NOT the result of an independent
    # AST-based audit (cf. rigor_evaluator.look_ahead_audit, which runs only
    # against cited curated source) — it is the LLM's own self-declared
    # look_ahead_safe flag, enforced as a closed-DSL admission gate. Kept as
    # a bool because it participates in the `passing` computation; see
    # `look_ahead_label` for the honest user-facing string (audit 06-14, Q6).
    look_ahead_clean: bool
    num_trials: int
    # In-sample (training-slice) Sharpe, surfaced so the OOS/IS cliff that the
    # gate enforces is visible on the passport, not just used internally.
    in_sample_sharpe: float | None = None
    # Provenance carried through from the backtest. ``admissible`` is the
    # honest gate: a strategy can only be certified Tier-1 if it both passes
    # the statistics AND those statistics were computed on real market data.
    data_source: str = "synthetic"
    admissible: bool = False
    # Honest user-facing label for the look-ahead check (audit 06-14, Q6).
    # Distinct from `look_ahead_clean` (the gating bool, always True here):
    # this string makes clear that "clean" means "the closed DSL's
    # self-attested look_ahead_safe flag was True", NOT "an independent
    # AST audit of the generated code ran and found no look-ahead bias" —
    # the latter is what `rigor_evaluator.look_ahead_audit` does for cited
    # curated source, and it is NOT run against fusion/DSL output. Mirrors
    # the "MISSING"-style honest labels in
    # `selection_bias_routes.RigorGateDetail.look_ahead`.
    look_ahead_label: str = "N/A (closed-DSL, self-attested, not source-audited)"


@dataclass(frozen=True)
class FusionEvalResult:
    """Complete result from the fusion evaluator pipeline."""

    spec: StrategySpec
    backtest: BacktestMetrics | None
    rigor: RigorVerdict | None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None and self.backtest is not None

    @property
    def admissible(self) -> bool:
        """True only if rigor passed AND on real (non-synthetic) market data."""
        return self.rigor is not None and self.rigor.admissible


# ── Backtest runner ───────────────────────────────────────────────────

_DEFAULT_CASH = 100_000.0
_DEFAULT_TX_BPS = 10

# The only price-data provenance that is NOT admissible for Tier-1 rigor
# certification. Everything else (real CSV, an explicitly provided feed) is
# trusted to be real market data — the caller owns that contract.
_SYNTHETIC_SOURCE = "synthetic"


def _data_source_label(data_feed: Any, data_csv_path: str | Path | None) -> str:
    """Honest provenance label for the price series a backtest ran on."""
    if data_feed is not None:
        return "provided"
    if data_csv_path is not None:
        return f"csv:{Path(data_csv_path).name}"
    return _SYNTHETIC_SOURCE


def is_admissible_source(data_source: str) -> bool:
    """True unless the metrics were computed on synthetic (random) prices.

    Rigor numbers from synthetic data describe noise, not a strategy — they
    must never be the basis for Tier-1 admission.
    """
    return data_source != _SYNTHETIC_SOURCE


def run_dsl_backtest(
    spec: StrategySpec,
    *,
    data_feed: Any = None,
    data_csv_path: str | Path | None = None,
    initial_cash: float = _DEFAULT_CASH,
    tx_cost_bps: int = _DEFAULT_TX_BPS,
) -> BacktestMetrics:
    """Run a backtest for a DSL-interpreted strategy.

    If ``data_feed`` is None and ``data_csv_path`` is set, builds a
    ``GenericCSVData`` feed from the CSV. If both are None, generates a
    deterministic synthetic price series. The equity curve is captured
    **bar-by-bar** via a backtrader analyzer.
    """
    import backtrader as bt

    strategy_cls = interpret_spec(spec)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(strategy_cls)

    data_source = _data_source_label(data_feed, data_csv_path)
    if data_source == _SYNTHETIC_SOURCE:
        logger.warning(
            "run_dsl_backtest[%s] is using SYNTHETIC price data — rigor metrics "
            "from this run are NOT admissible for Tier-1 certification. Pass "
            "data_csv_path or data_feed with real OHLCV for an admissible result.",
            spec.name,
        )

    if data_feed is None:
        data_feed = _csv_data_feed(Path(data_csv_path)) if data_csv_path is not None else _synthetic_data()

    cerebro.adddata(data_feed)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=tx_cost_bps / 10_000)

    # Per-bar equity capture + trade tracking via custom analyzers. Without
    # these, _extract_equity_curve falls back to fake linear interpolation
    # (see commit log for the equity-curve correctness fix).
    cerebro.addanalyzer(_EquityCurveAnalyzer, _name="equity_curve")
    cerebro.addanalyzer(_TradeStatsAnalyzer, _name="trade_stats")

    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    initial = initial_cash

    strat = results[0] if results else None
    equity_curve: list[float]
    if strat is not None:
        ec = strat.analyzers.equity_curve.get_analysis()
        equity_curve = list(ec.get("values", [])) or [initial_cash]
    else:
        equity_curve = [initial_cash]

    monthly_returns = _compute_monthly_returns(equity_curve)

    total_return = (final_value - initial) / initial
    n_bars = len(equity_curve)
    years = max(n_bars / 252, 0.01)
    cagr = (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1.0

    daily_returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]
    # rf-convention (deliberate split — do NOT "reconcile" to one rate):
    #   DISPLAY (here) = raw Sharpe/Sortino with rf=0. This is the passport
    #   headline and matches how backtrader's analyzer / practitioners quote it.
    #   GATE = rigor_evaluator._RF_ANNUAL = 0.05: the DSR deflates an *excess*-
    #   return Sharpe because Bailey-LdP (2014) is defined on excess returns.
    # The two answer different questions (headline performance vs. selection-bias-
    # corrected significance); forcing a single rf would corrupt one of them.
    # See rigor_evaluator.py for the gate side. (audit 2026-06-13, MEDIUM #8)
    sharpe = _annualized_sharpe(daily_returns, rf_annual=0.0)
    sortino = _annualized_sortino(daily_returns, rf_annual=0.0)
    max_dd = _max_drawdown(equity_curve)
    calmar = cagr / max_dd if max_dd > 0 else 0.0

    # Real trade stats from the analyzer (replaces the fixed 0.5 win-rate stub).
    trade_stats = (
        strat.analyzers.trade_stats.get_analysis()
        if strat is not None
        else {"total_trades": 0, "win_rate": 0.0, "avg_holding_period_days": 0.0}
    )

    return BacktestMetrics(
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        max_drawdown=round(max_dd, 4),
        cagr=round(cagr, 4),
        calmar_ratio=round(calmar, 4),
        win_rate=round(float(trade_stats.get("win_rate", 0.0)), 4),
        total_trades=int(trade_stats.get("total_trades", 0)),
        avg_holding_period_days=round(
            float(trade_stats.get("avg_holding_period_days", 0.0)),
            2,
        ),
        equity_curve=[round(e, 2) for e in equity_curve],
        monthly_returns=[round(m, 4) for m in monthly_returns],
        backtest_start=date(2004, 1, 2) if data_feed is None else None,
        backtest_end=date(2026, 4, 30) if data_feed is None else None,
        data_source=data_source,
    )


def run_dsl_backtest_variants(
    spec: StrategySpec,
    *,
    data_feed: Any = None,
    data_csv_path: str | Path | None = None,
    initial_cash: float = _DEFAULT_CASH,
    tx_cost_bps: int = _DEFAULT_TX_BPS,
) -> dict[str, BacktestMetrics]:
    """Run backtests for each cartesian-product point in the parameter grid.

    If ``spec.parameter_variants`` is ``None`` or empty, returns a
    single-entry dict ``{"base": metrics}`` for the unmodified spec.
    Otherwise expands the variant grid and runs one backtest per combination.

    Returns:
        ``{variant_id: BacktestMetrics}`` where variant_id is a
        dash-separated key like ``"150"`` or ``"150_0.12"``.
    """
    if spec.parameter_variants is None or not spec.parameter_variants:
        metrics = run_dsl_backtest(
            spec,
            data_feed=data_feed,
            data_csv_path=data_csv_path,
            initial_cash=initial_cash,
            tx_cost_bps=tx_cost_bps,
        )
        return {"base": metrics}

    # Compute the cartesian product of variant values.
    import itertools

    variant_keys = sorted(spec.parameter_variants.keys())
    variant_value_lists = [spec.parameter_variants[k] for k in variant_keys]

    results: dict[str, BacktestMetrics] = {}
    for combo in itertools.product(*variant_value_lists):
        overrides = {k: int(v) for k, v in zip(variant_keys, combo, strict=False)}
        variant_id = "_".join(str(v) for v in combo)

        # Build a spec *without* parameter_variants for the variant run.
        strategy_cls = interpret_variant(spec, overrides)

        # Re-run the variant through the same backtest harness.
        # We call run_dsl_backtest with a spec that produces the variant cls.
        # Instead of re-validating, we build a variant spec and use interpret_spec.
        variant_metrics = _run_variant_backtest(
            strategy_cls,
            data_feed=data_feed,
            data_csv_path=data_csv_path,
            initial_cash=initial_cash,
            tx_cost_bps=tx_cost_bps,
        )
        results[variant_id] = variant_metrics

    return results


def _run_variant_backtest(
    strategy_cls: Any,
    *,
    data_feed: Any = None,
    data_csv_path: str | Path | None = None,
    initial_cash: float = _DEFAULT_CASH,
    tx_cost_bps: int = _DEFAULT_TX_BPS,
) -> BacktestMetrics:
    """Run a single variant backtest given an already-interpreted strategy class."""
    import backtrader as bt

    data_source = _data_source_label(data_feed, data_csv_path)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(strategy_cls)

    if data_feed is None:
        data_feed = _csv_data_feed(Path(data_csv_path)) if data_csv_path is not None else _synthetic_data()

    cerebro.adddata(data_feed)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=tx_cost_bps / 10_000)

    cerebro.addanalyzer(_EquityCurveAnalyzer, _name="equity_curve")
    cerebro.addanalyzer(_TradeStatsAnalyzer, _name="trade_stats")

    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    initial = initial_cash

    strat = results[0] if results else None
    equity_curve: list[float]
    if strat is not None:
        ec = strat.analyzers.equity_curve.get_analysis()
        equity_curve = list(ec.get("values", [])) or [initial_cash]
    else:
        equity_curve = [initial_cash]

    monthly_returns = _compute_monthly_returns(equity_curve)

    total_return = (final_value - initial) / initial
    n_bars = len(equity_curve)
    years = max(n_bars / 252, 0.01)
    cagr = (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1.0

    daily_returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]
    # rf-convention (deliberate split — do NOT "reconcile" to one rate):
    #   DISPLAY (here) = raw Sharpe/Sortino with rf=0. This is the passport
    #   headline and matches how backtrader's analyzer / practitioners quote it.
    #   GATE = rigor_evaluator._RF_ANNUAL = 0.05: the DSR deflates an *excess*-
    #   return Sharpe because Bailey-LdP (2014) is defined on excess returns.
    # The two answer different questions (headline performance vs. selection-bias-
    # corrected significance); forcing a single rf would corrupt one of them.
    # See rigor_evaluator.py for the gate side. (audit 2026-06-13, MEDIUM #8)
    sharpe = _annualized_sharpe(daily_returns, rf_annual=0.0)
    sortino = _annualized_sortino(daily_returns, rf_annual=0.0)
    max_dd = _max_drawdown(equity_curve)
    calmar = cagr / max_dd if max_dd > 0 else 0.0

    trade_stats = (
        strat.analyzers.trade_stats.get_analysis()
        if strat is not None
        else {"total_trades": 0, "win_rate": 0.0, "avg_holding_period_days": 0.0}
    )

    return BacktestMetrics(
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        max_drawdown=round(max_dd, 4),
        cagr=round(cagr, 4),
        calmar_ratio=round(calmar, 4),
        win_rate=round(float(trade_stats.get("win_rate", 0.0)), 4),
        total_trades=int(trade_stats.get("total_trades", 0)),
        avg_holding_period_days=round(
            float(trade_stats.get("avg_holding_period_days", 0.0)),
            2,
        ),
        equity_curve=[round(e, 2) for e in equity_curve],
        monthly_returns=[round(m, 4) for m in monthly_returns],
        backtest_start=date(2004, 1, 2) if data_csv_path is None else None,
        backtest_end=date(2026, 4, 30) if data_csv_path is None else None,
        data_source=data_source,
    )


# ── Rigor gate ────────────────────────────────────────────────────────


def _default_num_trials() -> int:
    """Fallback selection-set size: the curated strategy library's count.

    Mirrors the pattern in ``generation_pipeline.run_generation`` — a lazy
    import (avoids a module-load-time dependency on the DB-backed provider)
    inside a try/except, with a safe ``1`` fallback if the provider is
    unavailable (e.g. in a hermetic unit test with no DB).
    """
    try:
        from archimedes.services.strategy_provider import default_provider

        return max(1, len(default_provider().list_strategies()))
    except Exception:
        return 1


def apply_rigor_gate(
    metrics: BacktestMetrics,
    num_trials: int | None = None,
    variants_metrics: dict[str, BacktestMetrics] | None = None,
    data_source: str | None = None,
) -> RigorVerdict:
    """Apply rigor gate to fusion backtest metrics.

    PBO is set to ``None`` (not 0.0) when there are fewer than 2 variant
    backtests. The Bailey/Borwein/López de Prado/Zhu CSCV PBO algorithm
    formally compares multiple competing strategies against the same return
    matrix; a single DSL-generated strategy doesn't yield a meaningful PBO
    without parameter-sweep variants to cross-validate against.

    When ``variants_metrics`` is provided with >= 2 entries, real CSCV PBO
    is computed from the variant returns matrix and attached to the verdict.

    ``num_trials``, when ``None`` (the default), falls back to the curated
    strategy library's size via ``_default_num_trials()`` — the real
    multiple-testing selection set a fusion-generated strategy is being
    compared against, rather than an arbitrary placeholder (audit 06-14, Q4).
    """
    if num_trials is None:
        num_trials = _default_num_trials()
    daily_returns = [
        (metrics.equity_curve[i] - metrics.equity_curve[i - 1]) / metrics.equity_curve[i - 1]
        for i in range(1, len(metrics.equity_curve))
        if metrics.equity_curve[i - 1] > 0
    ]

    # Build the parameter-variant returns matrix once — it is the multiple-
    # testing selection set, and feeds both the DSR effective-N correction
    # (average pairwise correlation of the trials) and the CSCV PBO.
    variant_returns: dict[str, list[float]] = {}
    if variants_metrics is not None and len(variants_metrics) >= 2:
        for vid, vm in variants_metrics.items():
            curve = vm.equity_curve
            variant_returns[vid] = [
                (curve[i] - curve[i - 1]) / curve[i - 1] for i in range(1, len(curve)) if curve[i - 1] > 0
            ]

    # num_trials = actual size of the multiple-testing selection set. The
    # caller-supplied/default value (curated library size — see
    # _default_num_trials) under-deflates a large variant grid (e.g. a
    # 50-variant sweep gets only a library-sized penalty) and over-deflates a
    # small one. When the variant matrix is known, it is a MORE precise
    # selection-set size, so it takes priority over the library-size fallback.
    effective_trials = num_trials
    if variants_metrics is not None and len(variants_metrics) >= 2:
        effective_trials = len(variants_metrics)

    # Correlated variants carry fewer independent trials than their nominal
    # count, so the multiple-testing penalty in the DSR is relaxed accordingly.
    avg_correlation = compute_average_pairwise_correlation(variant_returns) if len(variant_returns) >= 2 else 0.0
    dsr, dsr_p = compute_dsr(daily_returns, effective_trials, avg_correlation)
    oos_sharpe = compute_oos_sharpe(daily_returns)
    in_sample_sharpe = compute_in_sample_sharpe(daily_returns)

    # PBO: compute real CSCV PBO when >= 2 variant backtests are available.
    pbo_score: float | None = None
    if len(variant_returns) >= 2:
        pbo_map = compute_pbo(variant_returns)
        # All strategies in the matrix get the same PBO score (library-level
        # metric per Bailey et al. 2014). Pick the first entry's value.
        first_key = next(iter(pbo_map))
        pbo_score = pbo_map[first_key]

    # Look-ahead admission: validate_strategy_spec rejects any DSL spec with a
    # self-declared look_ahead_safe=False before this evaluator ever runs, so
    # `look_ahead_clean` is always True for specs reaching this point. This is
    # the LLM's OWN self-attestation enforced as a closed-DSL gate — NOT the
    # independent AST audit (rigor_evaluator.look_ahead_audit) that runs
    # against cited curated source. `look_ahead_label` carries the honest
    # framing of that distinction for the passport/UI (audit 06-14, Q6).
    look_ahead_clean = True
    look_ahead_label = "N/A (closed-DSL, self-attested, not source-audited)"

    # DSR gate: require p-value >= 0.95 (same threshold enforced by the curated
    # path in run_rigor_gate). Using dsr > 0.0 was too permissive — a z-score of
    # 0.5 (p ≈ 0.69) would pass here while the same strategy fails the API gate,
    # creating an inconsistency that could admit under-credentialed Tier-1 strategies
    # through the fusion path.
    # NaN-harden every numeric comparison: a NaN metric makes `>=`/`<` False,
    # which would silently skip a fail branch. Treat non-finite as fail.
    dsr_pass = dsr_p is not None and math.isfinite(dsr_p) and dsr_p >= 0.95

    # Walk-forward OOS Sharpe is the fourth admission primitive (DSL look-ahead
    # safety, DSR, PBO, walk-forward OOS). Mirror the curated path's
    # RigorGateResult.passes_all in full: an absolute floor (OOS > 0) AND the
    # in-/out-of-sample cliff (OOS/IS >= 0.5). Before this, the fusion path
    # enforced only the floor, so a strategy grossly overfit in-sample (e.g. IS
    # Sharpe 5.0, OOS Sharpe +0.05) passed the fusion gate and was certified
    # Tier-1 while the identical strategy failed the curated API gate.
    oos_pass = oos_sharpe is not None and math.isfinite(oos_sharpe) and oos_sharpe > 0.0
    if (
        oos_pass
        and in_sample_sharpe is not None
        and math.isfinite(in_sample_sharpe)
        and in_sample_sharpe > 0
        and oos_sharpe / in_sample_sharpe < 0.5
    ):
        oos_pass = False

    # Fail-closed when PBO wasn't computed (audit 06-14, Q4): a missing PBO
    # means CSCV never ran (fewer than 2 variant backtests), NOT that the
    # strategy passed the overfitting check. Mirrors RigorGateResult.passes_all
    # (rigor_evaluator.py), where pbo_score is None fails the overall gate
    # rather than vacuously passing it.
    pbo_pass = pbo_score is not None and math.isfinite(pbo_score) and pbo_score < 0.5
    passing = dsr_pass and oos_pass and look_ahead_clean and pbo_pass

    # Provenance gate: a strategy is only admissible for Tier-1 if it passes
    # the statistics AND those statistics were computed on real market data.
    # Default to the metrics' own provenance unless the caller overrides it.
    source = data_source if data_source is not None else metrics.data_source
    admissible = passing and is_admissible_source(source)
    if passing and not admissible:
        logger.warning(
            "rigor verdict is PASSING but NOT admissible — metrics came from "
            "non-real data source %r. Refusing Tier-1 certification.",
            source,
        )

    return RigorVerdict(
        passing=passing,
        dsr=dsr,
        dsr_p_value=dsr_p,
        pbo_score=pbo_score,
        oos_sharpe=oos_sharpe,
        in_sample_sharpe=in_sample_sharpe,
        look_ahead_clean=look_ahead_clean,
        look_ahead_label=look_ahead_label,
        num_trials=effective_trials,
        data_source=source,
        admissible=admissible,
    )


# ── Full pipeline ─────────────────────────────────────────────────────


def evaluate_fusion_spec(
    spec_dict: dict[str, Any],
    *,
    data_feed: Any = None,
    num_trials: int | None = None,
) -> FusionEvalResult:
    """Full pipeline: validate → interpret → backtest → rigor gate.

    ``num_trials=None`` (the default) defers to ``apply_rigor_gate``'s own
    fallback (the curated library size) — see ``_default_num_trials``.
    """
    try:
        spec = validate_strategy_spec(spec_dict)
    except DSLError as e:
        logger.warning("fusion spec validation failed: %s", e)
        return FusionEvalResult(
            spec=None,  # type: ignore[arg-type]
            backtest=None,
            rigor=None,
            error=str(e),
        )

    try:
        metrics = run_dsl_backtest(spec, data_feed=data_feed)
    except Exception as e:
        logger.exception("DSL backtest failed for %s", spec.name)
        return FusionEvalResult(spec=spec, backtest=None, rigor=None, error=str(e))

    # Run variant grid if parameter_variants is present.
    variants_metrics: dict[str, BacktestMetrics] | None = None
    if spec.parameter_variants is not None and len(spec.parameter_variants) >= 1:
        try:
            variants_metrics = run_dsl_backtest_variants(spec, data_feed=data_feed)
        except Exception as e:
            logger.warning("variant backtest failed for %s: %s", spec.name, e)
            variants_metrics = None

    rigor = apply_rigor_gate(
        metrics,
        num_trials=num_trials,
        variants_metrics=variants_metrics,
    )

    logger.info(
        "fusion eval: %s — sharpe=%.3f rigor.passing=%s pbo=%s",
        spec.name,
        metrics.sharpe_ratio,
        rigor.passing,
        rigor.pbo_score,
    )

    return FusionEvalResult(spec=spec, backtest=metrics, rigor=rigor)


# ── Helpers ───────────────────────────────────────────────────────────


def _synthetic_data() -> Any:
    """Generate synthetic SPY-like daily data for testing (2004-2026)."""
    import random
    import tempfile
    from datetime import timedelta

    import backtrader as bt

    random.seed(42)
    rows = []
    price = 100.0
    d = date(2004, 1, 2)
    end = date(2026, 4, 30)

    while d <= end:
        daily_ret = random.gauss(0.0003, 0.012)
        price *= 1 + daily_ret
        rows.append(f"{d.isoformat()},{price:.4f},{price * 1.001:.4f},{price * 0.999:.4f},{price:.4f},1000000")
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)

    csv_text = "\n".join(rows)
    # delete=False is required: backtrader reads the file from disk in the
    # GenericCSVData(dataname=tmp.name) call below. A context manager would
    # close+delete it before backtrader can open it.
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)  # noqa: SIM115
    tmp.write(csv_text)
    tmp.close()

    return bt.feeds.GenericCSVData(
        dataname=tmp.name,
        dtformat=("%Y-%m-%d"),
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
    )


# ── Analyzers: real per-bar equity capture + trade stats ────────────────
# Replace the pre-existing _extract_equity_curve that linearly interpolated
# between initial and final broker value (making all downstream Sharpe/MaxDD
# numbers meaningless because they were computed on a fake straight line).


class _EquityCurveAnalyzer:
    """Backtrader analyzer that captures broker value on every bar.

    Backtrader's standard ``Cerebro.run()`` does not retain the broker's
    per-bar value history; an analyzer is the canonical way to record it.
    The captured list is the input to all downstream Sharpe/Sortino/MaxDD
    calculations.
    """

    # NOTE: defined as a regular class with the bt.Analyzer-compatible
    # surface rather than `class X(bt.Analyzer)` so it's importable even
    # when backtrader isn't on the path at module-import time (matters for
    # the test harness's lazy import pattern).
    def __init__(self):
        self._values: list[float] = []

    def __getattr__(self, name):
        # backtrader pokes a few attributes at analyzer instances during wiring;
        # be liberal about missing ones (we only need start/next/get_analysis).
        raise AttributeError(name)


# Wire as a real backtrader analyzer at import time (so cerebro.addanalyzer
# accepts it). Done lazily inside a function so module import doesn't pull
# backtrader (matters for environments where backtrader is optional).
def _build_analyzers():
    import backtrader as bt

    class _EquityCurve(bt.Analyzer):
        def start(self):
            self._values: list[float] = []

        def next(self):
            self._values.append(float(self.strategy.broker.getvalue()))

        def stop(self):
            # Capture the final value once after the last bar so the curve
            # spans the full backtest including the closing mark.
            final = float(self.strategy.broker.getvalue())
            if not self._values or self._values[-1] != final:
                self._values.append(final)

        def get_analysis(self):
            return {"values": list(self._values)}

    class _TradeStats(bt.Analyzer):
        """Trade-level stats: total trades, win rate, average holding period."""

        def start(self):
            self._closed_pnls: list[float] = []
            self._holding_periods_bars: list[int] = []

        def notify_trade(self, trade):
            if trade.isclosed:
                self._closed_pnls.append(float(trade.pnlcomm))
                self._holding_periods_bars.append(int(trade.barlen))

        def get_analysis(self):
            n = len(self._closed_pnls)
            wins = sum(1 for p in self._closed_pnls if p > 0)
            win_rate = wins / n if n > 0 else 0.0
            avg_hold = sum(self._holding_periods_bars) / n if n > 0 else 0.0
            return {
                "total_trades": n,
                "win_rate": win_rate,
                # Bars are roughly daily for our seed strategies → days.
                "avg_holding_period_days": avg_hold,
            }

    return _EquityCurve, _TradeStats


# Resolve the real analyzer classes once and bind module-level so
# cerebro.addanalyzer(_EquityCurveAnalyzer, ...) works.
_EquityCurveAnalyzer, _TradeStatsAnalyzer = _build_analyzers()


def _csv_data_feed(csv_path: Path) -> Any:
    """Build a GenericCSVData feed from a CSV file on disk.

    Column layout matches _synthetic_data(): datetime=0, open=1, high=2,
    low=3, close=4, volume=5, openinterest=-1.
    """
    import backtrader as bt

    return bt.feeds.GenericCSVData(
        dataname=str(csv_path),
        dtformat=("%Y-%m-%d"),
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
    )


def _extract_daily_returns(strat: Any) -> list[float]:
    """Extract daily return series from the TimeReturn analyzer."""
    try:
        tr = strat.analyzers.timereturn.get_analysis()
        return list(tr.values())
    except (AttributeError, KeyError):
        return []


def _extract_analyzer_sharpe(strat: Any) -> float:
    """Extract Sharpe ratio from the SharpeRatio analyzer (rf=0, annualized)."""
    try:
        raw = strat.analyzers.sharpe.get_analysis().get("sharperatio")
        return float(raw) if raw is not None else 0.0
    except (AttributeError, KeyError, TypeError):
        return 0.0


def _extract_analyzer_drawdown(strat: Any) -> float:
    """Extract max drawdown (decimal) from the DrawDown analyzer."""
    try:
        dd_analysis = strat.analyzers.drawdown.get_analysis()
        max_dd_pct = dd_analysis.get("max", {}).get("drawdown", 0.0)
        return float(max_dd_pct) / 100.0
    except (AttributeError, KeyError, TypeError):
        return 0.0


def _build_equity_curve(daily_returns: list[float], initial_cash: float) -> list[float]:
    """Build an equity curve from a series of daily returns."""
    if not daily_returns:
        return [initial_cash]
    curve = [initial_cash]
    for ret in daily_returns:
        curve.append(curve[-1] * (1 + ret))
    return curve


def _extract_equity_curve(strat: Any, initial_cash: float) -> list[float]:
    """Extract equity curve from a completed strategy run."""
    # Use the analyzer if available, otherwise synthesize from broker value
    try:
        for _i in range(len(strat.data)):
            # Approximate by replaying — in practice cerebro.run() doesn't keep history
            pass
    except Exception:
        pass
    # Cerebro doesn't easily expose per-bar equity after run()
    # Return a simplified curve based on initial → final
    final = float(strat.broker.getvalue())
    n_bars = max(1, len(strat.data))
    # Linear interpolation as approximation (real curve would need observer)
    return [initial_cash + (final - initial_cash) * i / n_bars for i in range(n_bars + 1)]


def _compute_monthly_returns(equity_curve: list[float]) -> list[float]:
    """Compute approximate monthly returns from daily equity curve."""
    if len(equity_curve) < 22:
        return []
    returns = []
    for i in range(21, len(equity_curve), 21):
        start = equity_curve[i - 21]
        end = equity_curve[i]
        if start > 0:
            returns.append((end - start) / start)
    return returns


def _annualized_sharpe(daily_returns: list[float], rf_annual: float = 0.05) -> float:
    if not daily_returns:
        return 0.0
    mean_ret = sum(daily_returns) / len(daily_returns)
    var = sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
    std = var**0.5 if var > 0 else 0.0
    if std == 0:
        return 0.0
    daily_rf = rf_annual / 252
    return (mean_ret - daily_rf) / std * (252**0.5)


def _annualized_sortino(daily_returns: list[float], rf_annual: float = 0.05) -> float:
    if not daily_returns:
        return 0.0
    mean_ret = sum(daily_returns) / len(daily_returns)
    daily_rf = rf_annual / 252
    downside = [min(r - daily_rf, 0) ** 2 for r in daily_returns]
    ds_std = (sum(downside) / len(downside)) ** 0.5 if downside else 0.0
    if ds_std == 0:
        return 0.0
    return (mean_ret - daily_rf) / ds_std * (252**0.5)


def _max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


# ══════════════════════════════════════════════════════════════════════
# Fusion-quality scoring framework
# ══════════════════════════════════════════════════════════════════════
# A multi-dimensional score for *how good it is to FUSE/COMBINE* a set of
# strategies, given each one's daily-return series. This is orthogonal to the
# single-strategy rigor gate (DSR/PBO/OOS) above — rigor asks "is each member
# admissible?"; fusion quality asks "do these members combine into something
# better than any one alone?".
#
# All dimensions are pure numpy. Every method returns a float in a documented
# range (mostly [0, 1], higher = better-for-fusion) or NaN when the input is
# too degenerate to score (N < 2, all-constant series, …). Degenerate inputs
# never raise — they return NaN or a neutral 0.5 so the aggregate can simply
# skip a missing dimension instead of crashing.
#
# Owner: Önder (math lane).

import numpy as _np

# Default aggregate weights. Equal-ish weighting over the six dimensions, with
# diversification + correlation-stability carrying slightly more (they are the
# load-bearing "is fusion worthwhile at all" signals). Only the dimensions that
# actually have data participate; the present weights are renormalized to sum to
# 1.0 at aggregation time, so omitting a dimension does not bias the others.
_FUSION_DIMENSION_WEIGHTS: dict[str, float] = {
    "correlation_stability": 0.20,
    "diversification_benefit": 0.25,
    "tail_hedge": 0.20,
    "turnover_interaction": 0.10,
    "parameter_stability": 0.10,
    "economic_sense": 0.15,
}

# A neutral mid-scale score returned when a dimension's input is present but
# uninformative (e.g. a single perturbation observation): neither rewards nor
# penalizes fusion.
_FUSION_NEUTRAL = 0.5

# Tail-risk quantile for CVaR (Conditional Value-at-Risk / Expected Shortfall).
_CVAR_ALPHA = 0.05


def _as_returns_matrix(
    returns_matrix: dict[str, list[float]] | _np.ndarray | list[list[float]],
) -> _np.ndarray | None:
    """Coerce assorted return-series inputs into an aligned ``(N, T)`` array.

    Accepts ``{id: series}``, a 2-D array, or a list of lists. Series of
    unequal length are **truncated to the shortest** (length-mismatch handling
    per the fusion-scorer contract). Returns ``None`` when fewer than two
    usable (length >= 2) series survive — the caller treats ``None`` as
    "not scoreable".
    """
    if isinstance(returns_matrix, dict):
        series = list(returns_matrix.values())
    else:
        series = list(returns_matrix)

    arrs = [_np.asarray(s, dtype=float).ravel() for s in series]
    arrs = [a for a in arrs if a.size >= 2]
    if len(arrs) < 2:
        return None

    T = min(a.size for a in arrs)
    if T < 2:
        return None
    return _np.vstack([a[:T] for a in arrs])


def _mean_pairwise_corr_matrix(matrix: _np.ndarray) -> _np.ndarray | None:
    """Pearson correlation matrix of an ``(N, T)`` return matrix.

    Constant (zero-variance) rows are filled with an identity-like 0 off the
    diagonal because their correlation is undefined; returns ``None`` if fewer
    than two non-constant rows remain.
    """
    live = matrix[_np.ptp(matrix, axis=1) > 0.0]
    if live.shape[0] < 2:
        return None
    corr = _np.corrcoef(live)
    # np.corrcoef can emit nan for pathological rows; treat nan as 0 corr.
    return _np.nan_to_num(corr, nan=0.0)


def score_correlation_stability(
    returns_matrix: dict[str, list[float]] | _np.ndarray | list[list[float]],
) -> float:
    """Out-of-sample stability of the cross-strategy correlation structure.

    Splits each series into an early and a late half, computes the pairwise
    correlation matrix on each half, and returns ``1 - mean(|corr_late -
    corr_early|)`` over the off-diagonal entries, clipped to ``[0, 1]``.

    High = the diversification structure observed in-sample persists
    out-of-sample, so a fusion weighting fit on history is more likely to hold.
    Low = correlations drift (a regime shift), so historical diversification is
    unreliable.

    Statistical concept: rolling-/split-sample correlation stability — a
    non-stationarity diagnostic on the dependence structure (cf. correlation
    breakdown during regime shifts).

    Returns ``NaN`` for fewer than two usable series or when a half is too short
    (< 2 bars) or all-constant to form a correlation matrix.
    """
    matrix = _as_returns_matrix(returns_matrix)
    if matrix is None:
        return float("nan")

    T = matrix.shape[1]
    half = T // 2
    if half < 2:
        return float("nan")

    early = matrix[:, :half]
    late = matrix[:, half : 2 * half]

    corr_early = _mean_pairwise_corr_matrix(early)
    corr_late = _mean_pairwise_corr_matrix(late)
    if corr_early is None or corr_late is None or corr_early.shape != corr_late.shape:
        return float("nan")

    n = corr_early.shape[0]
    iu = _np.triu_indices(n, k=1)
    diff = _np.abs(corr_late[iu] - corr_early[iu])
    if diff.size == 0:
        return float("nan")

    return float(_np.clip(1.0 - float(_np.mean(diff)), 0.0, 1.0))


def score_diversification_benefit(
    returns_matrix: dict[str, list[float]] | _np.ndarray | list[list[float]],
) -> float:
    """Effective number of independent risk bets, normalized to ``[0, 1]``.

    Builds the correlation matrix, takes its eigenvalues, and computes the
    participation ratio / effective dimension::

        N_eff = (Σ λ_i)² / Σ λ_i²

    then normalizes by ``N`` so the score is ``N_eff / N ∈ (0, 1]``.

    High (→ 1) = the strategies span roughly ``N`` independent risk directions
    (low mutual correlation) — fusing them genuinely diversifies. Low (→ 1/N) =
    they collapse onto a single common factor (high correlation) — fusing buys
    little.

    Statistical concept: effective dimension / participation ratio of the
    correlation spectrum (Meucci 2009, "Managing Diversification"). For an
    ``N × N`` correlation matrix the eigenvalues sum to ``N``, so ``N_eff``
    ranges from ``1`` (one dominant factor) to ``N`` (isotropic / independent).

    Returns ``NaN`` for fewer than two usable, non-constant series.
    """
    matrix = _as_returns_matrix(returns_matrix)
    if matrix is None:
        return float("nan")

    corr = _mean_pairwise_corr_matrix(matrix)
    if corr is None:
        return float("nan")

    n = corr.shape[0]
    # Symmetric matrix → eigvalsh; clip tiny negatives from float error to 0.
    eigvals = _np.clip(_np.linalg.eigvalsh(corr), 0.0, None)
    denom = float(_np.sum(eigvals**2))
    if denom <= 0.0:
        return float("nan")

    n_eff = (float(_np.sum(eigvals)) ** 2) / denom
    return float(_np.clip(n_eff / n, 0.0, 1.0))


def _cvar(returns: _np.ndarray, alpha: float = _CVAR_ALPHA) -> float | None:
    """Conditional Value-at-Risk (Expected Shortfall) of the worst ``alpha`` tail.

    Returns the mean of the worst ``alpha`` fraction of returns as a **loss
    magnitude** (positive number for a loss). ``None`` if the series is empty.
    """
    arr = _np.asarray(returns, dtype=float).ravel()
    if arr.size == 0:
        return None
    # At least one observation in the tail even for short series.
    k = max(1, int(_np.ceil(alpha * arr.size)))
    worst = _np.sort(arr)[:k]
    return -float(_np.mean(worst))  # loss magnitude: positive = loss


def score_tail_hedge(
    returns_matrix: dict[str, list[float]] | _np.ndarray | list[list[float]],
) -> float:
    """Joint tail-risk reduction from equal-weight fusion, in ``[0, 1]``.

    Compares the equal-weight portfolio's 95% CVaR (mean of its worst 5% days)
    against the average of the individual strategies' 95% CVaR, returning::

        max(0, 1 - portfolio_CVaR / avg_individual_CVaR)

    High = combining the strategies materially softens the joint left tail
    (their bad days don't coincide) — a genuine tail hedge. ``0`` = the
    portfolio's tail is no better (or worse) than the average member's, so
    fusion provides no downside protection.

    Statistical concept: Conditional Value-at-Risk / Expected Shortfall at the
    95% level; tail diversification.

    Returns ``NaN`` for fewer than two usable series. Returns ``0.0`` (no
    benefit) when the average individual tail loss is non-positive (e.g. no
    losses in-sample), since there is no downside to hedge.
    """
    matrix = _as_returns_matrix(returns_matrix)
    if matrix is None:
        return float("nan")

    portfolio = matrix.mean(axis=0)  # equal-weight daily returns
    port_cvar = _cvar(portfolio)

    indiv = [_cvar(matrix[i]) for i in range(matrix.shape[0])]
    indiv = [c for c in indiv if c is not None]
    if port_cvar is None or not indiv:
        return float("nan")

    avg_indiv_cvar = float(_np.mean(indiv))
    if avg_indiv_cvar <= 0.0:
        # No average downside in-sample → nothing to hedge.
        return 0.0

    return float(_np.clip(1.0 - port_cvar / avg_indiv_cvar, 0.0, 1.0))


def score_turnover_interaction(
    weights_or_signals: dict[str, list[float]] | _np.ndarray | list[list[float]],
) -> float:
    """Directional agreement of strategies, in ``[0, 1]`` (churn proxy).

    When two strategies in a fused book hold opposite directional positions on
    the same day, the combined book partially nets out — and rebalancing back to
    target weights generates turnover (and transaction cost) that neither
    strategy incurs alone. This dimension rewards directional *agreement*::

        1 - mean_fraction_of_opposing_days

    averaged over all strategy pairs, where an "opposing day" is one where the
    two strategies' position signs differ.

    Approximation (documented): the function ideally consumes daily *position
    signals* (signed weights). When only return series are available it uses
    ``sign(returns)`` as a directional proxy — a strategy that made money on a
    given day is assumed to have been positioned long, lost money → short. This
    conflates "direction of the bet" with "direction of the outcome" and is a
    deliberate approximation; pass real signed signals for an exact measure.

    Statistical concept: signal disagreement / netting-induced turnover.

    High = strategies mostly agree on direction (low incremental churn from
    fusion). Low = they frequently oppose (high churn / cost drag). Days where a
    signal is exactly flat (sign 0) are excluded from that pair's tally.
    Returns ``NaN`` for fewer than two usable series.
    """
    matrix = _as_returns_matrix(weights_or_signals)
    if matrix is None:
        return float("nan")

    signs = _np.sign(matrix)  # proxy: sign(return) ≈ direction of position
    n = signs.shape[0]
    pair_agreements: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            si, sj = signs[i], signs[j]
            # Only days where both strategies took a directional stance.
            active = (si != 0) & (sj != 0)
            if not _np.any(active):
                continue
            opposing = (si[active] != sj[active]).mean()
            pair_agreements.append(1.0 - float(opposing))

    if not pair_agreements:
        return float("nan")

    return float(_np.clip(_np.mean(pair_agreements), 0.0, 1.0))


def score_parameter_stability(
    metric_under_perturbation: list[float] | _np.ndarray,
) -> float:
    """Robustness of a performance metric to small parameter perturbations.

    Given a list of metric values (e.g. Sharpe ratios) observed while a
    strategy's parameters are jittered slightly, returns::

        1 - normalized_std

    where ``normalized_std = std / |mean|`` is the coefficient of variation
    (clipped so the score stays in ``[0, 1]``). A flat response surface around
    the chosen operating point → low CV → score near ``1`` (robust); a metric
    that swings wildly under tiny perturbations → high CV → score near ``0``
    (fragile / likely overfit).

    Statistical concept: robustness-to-perturbation / coefficient of variation
    of the local response surface. Kept generic — the caller decides which
    metric and which perturbation grid to feed.

    Returns ``NaN`` for an empty input, a neutral ``0.5`` for a single
    observation (no spread is measurable), and ``0.5`` when the mean is ~0 so
    the CV is undefined (cannot normalize) — neither rewards nor penalizes.
    """
    arr = _np.asarray(metric_under_perturbation, dtype=float).ravel()
    if arr.size == 0:
        return float("nan")
    if arr.size == 1:
        return _FUSION_NEUTRAL

    mean = float(arr.mean())
    std = float(arr.std(ddof=1))
    if abs(mean) < 1e-12:
        # Mean ~0 → coefficient of variation is undefined; neutral.
        return _FUSION_NEUTRAL

    cv = std / abs(mean)
    return float(_np.clip(1.0 - cv, 0.0, 1.0))


def score_economic_sense(regime_tags: list[str] | tuple[str, ...]) -> float:
    """Regime diversity of the fused strategy set, in ``[0, 1]``.

    Given a list of regime tags (e.g. ``["bull", "bear", "neutral"]`` — one tag
    per strategy describing the regime it is designed to exploit), rewards
    coverage breadth::

        unique_regimes / total_tags

    High = the fused book spans multiple market regimes (e.g. a trend strategy
    plus a mean-reversion strategy plus a vol-managed sleeve) — economically
    sensible diversification across environments. Low (→ small) = every member
    targets the same regime, so the book is concentrated in one environment.

    Statistical/economic concept: regime coverage / economic diversification —
    a sanity check that the fusion is not just statistically diverse but spans
    distinct economic environments.

    Tags are normalized (stripped + lower-cased); empty / whitespace tags are
    ignored. Returns ``NaN`` for an empty input after filtering.
    """
    if regime_tags is None:
        return float("nan")
    cleaned = [str(t).strip().lower() for t in regime_tags if str(t).strip()]
    if not cleaned:
        return float("nan")
    return float(len(set(cleaned)) / len(cleaned))


class FusionQualityScorer:
    """Multi-dimensional scorer for the quality of fusing several strategies.

    Each dimension is a thin wrapper around the module-level pure functions so
    the class can be subclassed / reweighted without touching the math. The
    aggregate ``fusion_quality`` is a weighted mean over **only the dimensions
    that produced a finite score**, with the present weights renormalized to sum
    to 1.0 — so a missing input (e.g. no regime tags) drops that dimension
    cleanly rather than dragging the aggregate toward 0.

    Weights (``_FUSION_DIMENSION_WEIGHTS``, documented at module level):
    diversification 0.25, correlation-stability 0.20, tail-hedge 0.20,
    economic-sense 0.15, turnover-interaction 0.10, parameter-stability 0.10.
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = dict(weights) if weights is not None else dict(_FUSION_DIMENSION_WEIGHTS)

    # ── individual dimensions (instance-method facade over the pure fns) ──

    def score_correlation_stability(self, returns_matrix: Any) -> float:
        return score_correlation_stability(returns_matrix)

    def score_diversification_benefit(self, returns_matrix: Any) -> float:
        return score_diversification_benefit(returns_matrix)

    def score_tail_hedge(self, returns_matrix: Any) -> float:
        return score_tail_hedge(returns_matrix)

    def score_turnover_interaction(self, weights_or_signals: Any) -> float:
        return score_turnover_interaction(weights_or_signals)

    def score_parameter_stability(self, metric_under_perturbation: Any) -> float:
        return score_parameter_stability(metric_under_perturbation)

    def score_economic_sense(self, regime_tags: Any) -> float:
        return score_economic_sense(regime_tags)

    # ── aggregate ─────────────────────────────────────────────────────

    def score_all(
        self,
        returns_matrix: dict[str, list[float]] | _np.ndarray | list[list[float]] | None = None,
        *,
        signals: dict[str, list[float]] | _np.ndarray | list[list[float]] | None = None,
        perturbation_metrics: list[float] | _np.ndarray | None = None,
        regime_tags: list[str] | None = None,
    ) -> dict[str, float]:
        """Compute every sub-score that has data plus the weighted aggregate.

        Args:
            returns_matrix: ``{id: daily_returns}`` (or array) — drives the
                correlation-stability, diversification, and tail-hedge
                dimensions, and (if ``signals`` is not given) the
                turnover-interaction proxy via ``sign(returns)``.
            signals: Optional signed daily position signals; if provided,
                turnover-interaction uses these instead of the return-sign proxy.
            perturbation_metrics: Optional metric-under-perturbation list for
                the parameter-stability dimension.
            regime_tags: Optional per-strategy regime tags for economic-sense.

        Returns:
            A dict with each computed dimension's score (only finite ones are
            included as numeric; a dimension whose input was absent is omitted)
            plus ``fusion_quality`` — the renormalized weighted mean over the
            present dimensions. ``fusion_quality`` is ``NaN`` if no dimension
            had usable data.
        """
        scores: dict[str, float] = {}

        if returns_matrix is not None:
            scores["correlation_stability"] = self.score_correlation_stability(returns_matrix)
            scores["diversification_benefit"] = self.score_diversification_benefit(returns_matrix)
            scores["tail_hedge"] = self.score_tail_hedge(returns_matrix)

        # Turnover: prefer explicit signed signals, fall back to return-sign proxy.
        turnover_input = signals if signals is not None else returns_matrix
        if turnover_input is not None:
            scores["turnover_interaction"] = self.score_turnover_interaction(turnover_input)

        if perturbation_metrics is not None:
            scores["parameter_stability"] = self.score_parameter_stability(perturbation_metrics)

        if regime_tags is not None:
            scores["economic_sense"] = self.score_economic_sense(regime_tags)

        # Aggregate over finite dimensions only, renormalizing their weights.
        present = {k: v for k, v in scores.items() if v is not None and _np.isfinite(v)}
        total_w = sum(self.weights.get(k, 0.0) for k in present)
        if present and total_w > 0.0:
            agg = sum(self.weights.get(k, 0.0) * v for k, v in present.items()) / total_w
            fusion_quality = float(_np.clip(agg, 0.0, 1.0))
        else:
            fusion_quality = float("nan")

        result = dict(scores)
        result["fusion_quality"] = fusion_quality
        return result


def generate_fusion_report(scores: dict[str, float], threshold: float = 0.7) -> dict[str, Any]:
    """Structured (dict) recommendation report from ``FusionQualityScorer.score_all``.

    NOT an HTML/PDF artifact — a plain dict suitable for JSON serialization or
    further programmatic use.

    Args:
        scores: The dict returned by ``score_all`` (must contain
            ``fusion_quality``; other keys are treated as dimension scores).
        threshold: ``fusion_quality`` at or above this recommends fusion.

    Returns:
        ``{recommended, fusion_quality, dimension_breakdown, rationale}`` where
        ``recommended`` is a bool (``False`` if ``fusion_quality`` is NaN/missing),
        ``dimension_breakdown`` maps each present dimension to its score, and
        ``rationale`` is a human-readable one-liner naming the strongest and
        weakest contributing dimensions.
    """
    fq = scores.get("fusion_quality", float("nan"))
    dimension_breakdown = {
        k: float(v) for k, v in scores.items() if k != "fusion_quality" and v is not None and _np.isfinite(v)
    }

    fq_finite = isinstance(fq, (int, float)) and _np.isfinite(fq)
    recommended = bool(fq_finite and fq >= threshold)

    if not fq_finite:
        rationale = "Insufficient data to score fusion quality (no dimension had usable inputs)."
    elif not dimension_breakdown:
        rationale = f"Fusion quality {fq:.2f} computed but no per-dimension breakdown available."
    else:
        strongest = max(dimension_breakdown, key=dimension_breakdown.get)
        weakest = min(dimension_breakdown, key=dimension_breakdown.get)
        verdict = "Recommend fusion" if recommended else "Do not fuse yet"
        rationale = (
            f"{verdict}: fusion quality {fq:.2f} vs threshold {threshold:.2f}. "
            f"Strongest dimension: {strongest} ({dimension_breakdown[strongest]:.2f}); "
            f"weakest: {weakest} ({dimension_breakdown[weakest]:.2f})."
        )

    return {
        "recommended": recommended,
        "fusion_quality": float(fq) if fq_finite else float("nan"),
        "dimension_breakdown": dimension_breakdown,
        "rationale": rationale,
    }
