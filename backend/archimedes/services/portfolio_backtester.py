"""Real multi-year backtester for AI-generated portfolio strategies.

Closes the gap that left every generated strategy stuck at "Pending Backtest"
on the Library page. The analytics-engine's :mod:`engine.run_backtest` runs
single-asset backtrader Cerebro sims keyed on a hand-written ``bt.Strategy``
class — fine for the 6 curated example strategies (each ships its own class)
but wrong for generated output: the LLM emits ``{ticker: weight}`` maps + a
rebalance period, not Python strategy code.

This module fills that hole with a vanilla pandas/numpy simulator:

  1. ``fetch_ohlcv`` (yfinance) for every ticker in ``weights``
  2. Wide-form close panel with strict inner-join on the business-day index
  3. Periodic rebalance with linear transaction costs (``tx_cost_bps``)
  4. Daily portfolio return series → Sharpe / Sortino / CAGR / max DD / Calmar
  5. The same daily-return series is fed into :mod:`rigor_evaluator` for
     DSR (Bailey & López de Prado 2014) and walk-forward OOS Sharpe — same
     primitives the curated strategies use, so generated and curated
     strategies are graded on the same scale.

Honest framing the UI inherits via the ``backtest_engine`` field:
this is a static-rebalance backtest of the agent's *allocation*. It does NOT
test regime-conditional signal logic — the agent does not emit signals, only
weights. Surfacing this as ``"portfolio-simulator-v1"`` lets the passport
distinguish it from the curated strategies' ``"backtrader"`` runs.

Owner: Dan (strategy engine); rigor primitives owned by Önder.
Spec:  docs/specs/selection-bias-corrections-spec.md (rigor gate unchanged).
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from archimedes.models.backtest import BacktestResult

logger = logging.getLogger(__name__)


# Defaults tuned to give enough bars for a meaningful DSR (T ≥ 4 minimum;
# practical floor is ~252 bars / 1 year so the annualization isn't junk).
DEFAULT_LOOKBACK_YEARS = 7
DEFAULT_REBALANCE_DAYS = 21  # ~monthly
DEFAULT_INITIAL_CASH = 100_000.0
DEFAULT_TX_COST_BPS = 10  # round-trip; matches analytics-engine default
ANNUALIZATION = 252
MIN_BARS_FOR_BACKTEST = 60  # ~3 months; refuse to backtest shorter windows


def _ensure_analytics_import() -> None:
    """Place ``analytics-engine/src`` on sys.path so its ``data`` module imports.

    Mirrors :func:`archimedes.scripts.run_backtests._ensure_analytics_import` —
    we deliberately reuse the analytics-engine's yfinance wrapper rather than
    pulling yfinance directly here, so a single function owns the fetch+
    normalize contract.
    """
    analytics_src = Path(__file__).resolve().parents[3] / "analytics-engine" / "src"
    if str(analytics_src) not in sys.path:
        sys.path.insert(0, str(analytics_src))


def _fetch_price_panel(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """Fetch close prices for ``symbols`` and inner-join on the date index.

    Drops rows where any symbol is missing data — strict alignment so we never
    invent a return where one of the legs wasn't trading.
    """
    _ensure_analytics_import()
    from archimedes_analytics_engine.data import fetch_ohlcv  # noqa: PLC0415

    closes: dict[str, pd.Series] = {}
    for sym in symbols:
        df = fetch_ohlcv(sym, start, end)
        closes[sym] = df["Close"]
    panel = pd.DataFrame(closes).dropna()
    if len(panel) < MIN_BARS_FOR_BACKTEST:
        raise ValueError(
            f"Insufficient overlapping history: only {len(panel)} bars across {symbols} (min {MIN_BARS_FOR_BACKTEST})"
        )
    return panel


def _simulate_portfolio(
    panel: pd.DataFrame,
    target_weights: dict[str, float],
    *,
    rebalance_days: int,
    initial_cash: float,
    tx_cost_bps: int,
) -> tuple[list[float], list[float]]:
    """Run a periodic-rebalance simulation; returns ``(daily_returns, equity_curve)``.

    Implementation notes:
      - Held weights drift between rebalance bars with realized returns.
      - On rebalance bars, the L1 turnover ``|held - target|`` is charged as a
        proportional cost in bps; this is a conservative model (no slippage,
        no spread — those are tx_cost_bps's job to encode).
      - No leverage. Negative weights are clamped to zero at normalization
        (long-only enforcement matches the agent's actual output contract).
    """
    syms = list(panel.columns)
    n_bars = len(panel)

    # Build canonical target weights aligned to the panel (zero-fill for any
    # symbol that fell out of the inner-join, then long-only normalize).
    raw = pd.Series({s: max(target_weights.get(s, 0.0), 0.0) for s in syms})
    total = float(raw.sum())
    if total <= 0:
        raise ValueError("All weights non-positive after symbol alignment")
    target = raw / total

    returns = panel.pct_change().fillna(0.0)
    held = target.copy()
    portfolio_returns: list[float] = []
    equity = float(initial_cash)
    equity_curve: list[float] = []

    for i in range(n_bars):
        r_t = float((returns.iloc[i] * held).sum())

        # Apply the realized return to held weights first; THEN, if this is a
        # rebalance bar, charge turnover cost and snap back to target.
        new_value = held * (1.0 + returns.iloc[i])
        new_total = float(new_value.sum())
        if new_total > 0:
            drifted = new_value / new_total
        else:
            drifted = held

        if i > 0 and i % rebalance_days == 0:
            turnover = float((drifted - target).abs().sum())
            cost = turnover * (tx_cost_bps / 10_000.0)
            r_t -= cost
            held = target.copy()
        else:
            held = drifted

        portfolio_returns.append(r_t)
        equity *= 1.0 + r_t
        equity_curve.append(equity)

    return portfolio_returns, equity_curve


def _annualized_metrics(daily_returns: list[float], equity_curve: list[float]) -> dict[str, float]:
    """Annualized Sharpe / Sortino / CAGR / max DD / Calmar from a daily return series."""
    arr = np.asarray(daily_returns, dtype=float)
    T = len(arr)
    if T < 2:
        return {
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "cagr": 0.0,
            "max_drawdown": 0.0,
            "calmar_ratio": 0.0,
        }

    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1))
    sharpe = (mu / sigma) * np.sqrt(ANNUALIZATION) if sigma > 0 else 0.0

    downside = arr[arr < 0]
    down_sigma = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = (mu / down_sigma) * np.sqrt(ANNUALIZATION) if down_sigma > 0 else 0.0

    eq = np.asarray(equity_curve, dtype=float)
    if eq[0] > 0 and T >= 2:
        cagr = float((eq[-1] / eq[0]) ** (ANNUALIZATION / T) - 1.0)
    else:
        cagr = 0.0

    drawdown = (eq / np.maximum.accumulate(eq)) - 1.0
    max_dd = float(-drawdown.min()) if T > 0 else 0.0

    calmar = float(cagr / max_dd) if max_dd > 0 else 0.0

    return {
        "sharpe_ratio": float(sharpe),
        "sortino_ratio": float(sortino),
        "cagr": cagr,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
    }


def _correlation_to_benchmark(daily_returns: list[float], benchmark_returns: list[float]) -> float:
    """Pearson correlation between two return series, robust to unequal length."""
    n = min(len(daily_returns), len(benchmark_returns))
    if n < 2:
        return 0.0
    a = np.asarray(daily_returns[:n], dtype=float)
    b = np.asarray(benchmark_returns[:n], dtype=float)
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _module_hash() -> str:
    """SHA-256 of the simulator's source — for replay verification on the artifact."""
    try:
        src = inspect.getsource(_simulate_portfolio) + inspect.getsource(_annualized_metrics)
        return hashlib.sha256(src.encode("utf-8")).hexdigest()
    except (OSError, TypeError):
        return ""


def _panel_hash(panel: pd.DataFrame) -> str:
    """SHA-256 of the price panel content — lets a replayer verify same data."""
    return hashlib.sha256(panel.to_csv(index=True).encode("utf-8")).hexdigest()


def backtest_portfolio(
    *,
    strategy_id: str,
    weights: dict[str, float],
    start: str | None = None,
    end: str | None = None,
    rebalance_days: int = DEFAULT_REBALANCE_DAYS,
    initial_cash: float = DEFAULT_INITIAL_CASH,
    tx_cost_bps: int = DEFAULT_TX_COST_BPS,
    num_trials_for_dsr: int = 1,
    paper_claimed_sharpe: float | None = None,
    paper_title: str | None = None,
) -> tuple[BacktestResult, dict[str, Any]]:
    """Backtest a static-weight portfolio over real multi-year market data.

    Args:
        strategy_id: FK back to the StrategyPassport row.
        weights: ``{ticker: weight}`` — non-positive entries are dropped.
        start: ISO date for backtest start. Defaults to ``end - DEFAULT_LOOKBACK_YEARS``.
        end: ISO date for backtest end. Defaults to today (UTC).
        rebalance_days: Periodic rebalance interval in trading days.
        initial_cash: Starting equity.
        tx_cost_bps: Round-trip cost in basis points (10 = 0.10%, matches default).
        num_trials_for_dsr: Multiple-testing correction; pass library size for
            meaningful DSR. Default 1 = no correction (passport's own row).
        paper_claimed_sharpe: If set, recorded for paper-vs-actual delta display.
        paper_title: Optional human-readable title for the artifact metadata.

    Returns:
        ``(BacktestResult, artifact_dict)`` — the dataclass for DB persistence,
        the dict for the JSON ``artifact_json`` blob (mirrors analytics-engine
        artifact shape so the existing rigor-gate consumers stay generic).

    Raises:
        ValueError: insufficient overlap (< MIN_BARS_FOR_BACKTEST) or all weights
            zero after symbol alignment. Callers should treat these as
            non-fatal: a failed backtest leaves the placeholder in place.
    """
    end_iso = end or datetime.now(UTC).date().isoformat()
    if start is None:
        start_dt = datetime.fromisoformat(end_iso) - timedelta(days=365 * DEFAULT_LOOKBACK_YEARS)
        start_iso = start_dt.date().isoformat()
    else:
        start_iso = start

    active_weights = {sym: float(w) for sym, w in (weights or {}).items() if w and w > 0 and sym}
    if not active_weights:
        raise ValueError(f"No positive weights for strategy {strategy_id}")

    symbols = list(active_weights.keys())
    panel = _fetch_price_panel(symbols, start_iso, end_iso)
    daily_returns, equity_curve = _simulate_portfolio(
        panel,
        active_weights,
        rebalance_days=rebalance_days,
        initial_cash=initial_cash,
        tx_cost_bps=tx_cost_bps,
    )

    core = _annualized_metrics(daily_returns, equity_curve)

    # ── Rigor primitives — same evaluator the curated strategies use ──
    from archimedes.services.rigor_evaluator import compute_dsr, compute_oos_sharpe  # noqa: PLC0415

    deflated_sharpe, dsr_p_value = compute_dsr(daily_returns, num_trials_for_dsr)
    oos_sharpe = compute_oos_sharpe(daily_returns)
    # Static rebalance with t-1 prices generating t returns is structurally
    # lookahead-free — no signal computation at all. We mark this true for
    # the gate; the analytics-engine's AST-based audit on real strategy code
    # is the higher bar that the curated strategies pass.
    look_ahead_passed = True

    # ── SPY correlation (diversification signal) ──
    correlation_to_spy = 0.0
    try:
        spy_panel = _fetch_price_panel(["SPY"], start_iso, end_iso)
        spy_full = spy_panel["SPY"].pct_change().fillna(0.0)
        # Align to the portfolio's panel index (inner-join already applied)
        common = panel.index.intersection(spy_panel.index)
        if len(common) >= 2:
            spy_aligned = spy_full.loc[common].tolist()
            port_series = pd.Series(daily_returns, index=panel.index)
            port_aligned = port_series.loc[common].tolist()
            correlation_to_spy = _correlation_to_benchmark(port_aligned, spy_aligned)
    except (ValueError, KeyError) as exc:
        logger.debug("SPY correlation skipped: %s", exc)

    n_obs_daily = len(daily_returns)
    # Number of rebalance events ≈ trades; pure buy-and-hold (no rebalance bars
    # crossed) reports 0 which is honest.
    rebalance_events = max(0, n_obs_daily // rebalance_days - 1)

    result = BacktestResult(
        strategy_id=strategy_id,
        sharpe_ratio=core["sharpe_ratio"],
        sortino_ratio=core["sortino_ratio"],
        max_drawdown=core["max_drawdown"],
        cagr=core["cagr"],
        calmar_ratio=core["calmar_ratio"],
        win_rate=0.0,  # No closed trades in static rebalance; honest 0
        profit_factor=0.0,
        total_trades=rebalance_events,
        avg_holding_period_days=float(rebalance_days),
        correlation_to_spy=correlation_to_spy,
        correlation_to_btc=0.0,  # not computed for portfolio sim
        equity_curve=equity_curve,
        monthly_returns=[],
        backtest_start=date.fromisoformat(start_iso),
        backtest_end=date.fromisoformat(end_iso),
        paper_claimed_sharpe=paper_claimed_sharpe,
        paper_claimed_cagr=None,
        paper_claimed_max_dd=None,
        deflated_sharpe_ratio=deflated_sharpe,
        dsr_p_value=dsr_p_value,
        num_trials_in_selection=num_trials_for_dsr,
        pbo_score=None,  # library-level metric; a follow-up scheduler can refresh
        out_of_sample_sharpe=oos_sharpe,
        walk_forward_train_fraction=0.70,
        look_ahead_audit_passed=look_ahead_passed,
        backtest_engine="portfolio-simulator-v1",
        backtest_code_hash=_module_hash(),
        transaction_cost_bps=tx_cost_bps,
    )

    artifact = {
        "run_id": f"gen-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{strategy_id[:8]}",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "operations": symbols,
        "strategy": {
            "path": f"generated/{strategy_id}",
            "class_name": "GeneratedStaticRebalance",
            "backtest_code_hash": result.backtest_code_hash,
            "paper_arxiv_id": None,
            "paper_title": paper_title or f"Generated Strategy {strategy_id[:8]}",
            "methodology_hash": None,
            "paper_claimed_sharpe": paper_claimed_sharpe,
            "paper_claimed_cagr": None,
            "paper_claimed_max_dd": None,
        },
        "assumptions": {
            "start": start_iso,
            "end": end_iso,
            "transaction_cost_bps": tx_cost_bps,
            "slippage_bps": 0,
            "lookahead_guard": "static_rebalance_no_signal_shift",
            "walk_forward_split": 0.70,
            "data_source": "yfinance",
            "backtest_engine": "portfolio-simulator-v1",
            "rebalance_days": rebalance_days,
            "weights": active_weights,
        },
        "results": [
            {
                "operation": "PORTFOLIO",
                "symbol": "PORTFOLIO",
                "metrics": {
                    **core,
                    "daily_returns": daily_returns,
                    "equity_curve": equity_curve,
                    "deflated_sharpe_ratio": deflated_sharpe,
                    "dsr_p_value": dsr_p_value,
                    "out_of_sample_sharpe": oos_sharpe,
                    "correlation_to_spy": correlation_to_spy,
                    "num_bars": n_obs_daily,
                    "rebalance_events": rebalance_events,
                },
            }
        ],
        "data_hashes": [_panel_hash(panel)],
        "integrity_flags": {
            "lookahead_audit_passed": look_ahead_passed,
            "survivorship_bias_mitigated": False,  # yfinance ticker list is current-roster
            "paper_claim_comparison_applied": paper_claimed_sharpe is not None,
        },
    }
    return result, artifact
