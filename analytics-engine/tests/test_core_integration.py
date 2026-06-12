"""End-to-end integration tests across the analytics-engine core modules.

These exercise multiple core modules *together* — the engine runner
(``engine.py``), the transaction-cost / turnover model (``costs.py``), and the
walk-forward harness (``walk_forward.py``) — rather than any single function in
isolation. The invariants asserted here are the load-bearing properties the
strategy passport relies on:

- transaction costs only ever *reduce* net performance (cost realism),
- higher per-side costs ⇒ lower net Sharpe (monotonicity), and
- the walk-forward harness produces train/test splits with no temporal overlap
  (the anti-look-ahead guard).

Hermetic: all data is small, deterministic synthetic OHLCV built in-process via
``numpy.random.default_rng(seed=...)`` or hand-built arrays. No network, no
yfinance, no real downloads — mirroring the existing analytics-engine tests.
"""

from __future__ import annotations

import math

import backtrader as bt
import numpy as np
import pandas as pd
import pytest
from archimedes_analytics_engine.costs import CostModel
from archimedes_analytics_engine.engine import (
    BacktestResult,
    run_backtest,
    run_buy_and_hold,
)
from archimedes_analytics_engine.walk_forward import (
    WalkForwardResult,
    walk_forward_select,
)

# ── Deterministic synthetic data builders ─────────────────────────────────────


def _ohlcv(closes: list[float], start: str = "2021-01-01") -> pd.DataFrame:
    """Build an OHLCV frame from a close series.

    ``Open == Close`` so market executions happen at known, exact prices —
    the same convention the existing cost tests rely on for hand-computed
    expectations.
    """
    idx = pd.date_range(start, periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.004 for c in closes],
            "Low": [c * 0.996 for c in closes],
            "Close": closes,
            "Volume": [1_000] * len(closes),
        },
        index=idx,
    )


def _rng_uptrend(periods: int, *, seed: int, drift: float = 0.08) -> pd.DataFrame:
    """A noisy upward-drifting close series from a fixed-seed RNG (reproducible)."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 0.6, size=periods)
    closes = [100.0 + drift * i + float(noise[i]) for i in range(periods)]
    return _ohlcv(closes)


def _deterministic_uptrend(periods: int, *, base: float = 100.0, slope: float = 0.25) -> pd.DataFrame:
    """A smooth, sinusoidally-perturbed uptrend — fully deterministic, no RNG."""
    closes = [base + slope * i + 1.5 * math.sin(i / 6.0) for i in range(periods)]
    return _ohlcv(closes)


# ── Strategies under test (all warm-up-free unless noted) ────────────────────


class _ChurnEveryBar(bt.Strategy):
    """Alternate between 30% and 80% exposure every bar — deliberately churny.

    Generates turnover on (almost) every bar so the transaction-cost model has
    something to bite on; used to prove costs reduce net return.
    """

    def next(self) -> None:
        target = 0.3 if len(self) % 2 == 0 else 0.8
        self.order_target_percent(target=target)


class _ExposureStrategy(bt.Strategy):
    """Hold a constant target exposure — the simplest selectable parameter."""

    params = (("invested", 0.0),)

    def next(self) -> None:
        target = float(self.params.invested)
        if len(self) == 2 and target > 0 and not self.position:
            self.order_target_percent(target=target)


# ── A. Engine + cost-model: costs reduce net return ──────────────────────────


def test_costs_reduce_net_return_vs_zero_cost() -> None:
    """A churny strategy run with costs must end below the same run at zero cost."""
    prices = _rng_uptrend(120, seed=7)
    free = run_backtest(prices, strategy_cls=_ChurnEveryBar, initial_cash=100_000.0, transaction_cost_bps=0)
    costly = run_backtest(prices, strategy_cls=_ChurnEveryBar, initial_cash=100_000.0, transaction_cost_bps=30)

    assert free.total_commission_paid == 0.0
    assert costly.total_commission_paid > 0.0
    assert costly.final_value < free.final_value
    assert costly.total_return_pct < free.total_return_pct


def test_cost_model_path_matches_flat_bps_path() -> None:
    """Routing the same per-side cost through a CostModel must match the flat-bps path."""
    prices = _rng_uptrend(120, seed=11)
    flat = run_backtest(prices, strategy_cls=_ChurnEveryBar, initial_cash=100_000.0, transaction_cost_bps=15)
    modeled = run_backtest(
        prices,
        strategy_cls=_ChurnEveryBar,
        initial_cash=100_000.0,
        cost_model=CostModel(default_bps=15.0),
    )
    assert modeled.final_value == pytest.approx(flat.final_value)
    assert modeled.total_commission_paid == pytest.approx(flat.total_commission_paid)
    assert modeled.transaction_cost_bps == 15


def test_gross_sharpe_recovers_above_net_under_costs() -> None:
    """Adding commissions back (gross) must lift Sharpe above the net figure when costs bite."""
    prices = _rng_uptrend(150, seed=3)
    costly = run_backtest(prices, strategy_cls=_ChurnEveryBar, initial_cash=100_000.0, transaction_cost_bps=40)
    assert costly.sharpe_ratio is not None
    assert costly.gross_sharpe_ratio is not None
    assert costly.gross_sharpe_ratio > costly.sharpe_ratio


# ── B. Engine metric invariants end-to-end ───────────────────────────────────


def test_higher_costs_monotonically_lower_net_sharpe() -> None:
    """Sharpe must be monotonically non-increasing as per-side cost rises."""
    prices = _rng_uptrend(160, seed=5)
    sharpes: list[float] = []
    for bps in (0, 20, 60, 120):
        result = run_backtest(prices, strategy_cls=_ChurnEveryBar, initial_cash=100_000.0, transaction_cost_bps=bps)
        assert result.sharpe_ratio is not None
        sharpes.append(result.sharpe_ratio)
    for lo, hi in zip(sharpes[1:], sharpes[:-1], strict=True):
        # later (higher-cost) Sharpe must not exceed the earlier (lower-cost) one
        assert lo <= hi + 1e-9


def test_metric_keys_and_signs_are_coherent() -> None:
    """An end-to-end run exposes the expected metric keys with coherent signs."""
    prices = _deterministic_uptrend(90)
    result = run_buy_and_hold(prices, initial_cash=100_000.0)

    assert isinstance(result, BacktestResult)
    assert result.backtest_engine == "backtrader"
    assert result.bars == 90
    # Upward-drifting buy-and-hold: positive total return, equity ends above start.
    assert result.total_return_pct > 0
    assert result.final_value > 100_000.0
    assert result.equity_curve[0] == pytest.approx(100_000.0)
    # daily return series and its date labels are 1:1 aligned.
    assert len(result.daily_returns) == len(result.daily_return_dates)
    # CAGR sign agrees with total return sign.
    assert result.cagr is not None and result.cagr > 0


def test_equity_curve_length_tracks_daily_returns() -> None:
    """equity_curve carries the initial-cash seed plus one point per daily return."""
    prices = _deterministic_uptrend(75)
    result = run_buy_and_hold(prices, initial_cash=50_000.0)
    assert len(result.equity_curve) == len(result.daily_returns) + 1
    assert result.equity_curve[0] == pytest.approx(50_000.0)
    assert result.equity_curve[-1] == pytest.approx(result.final_value)


# ── C. Walk-forward harness: anti-look-ahead split guarantees ─────────────────


def test_walk_forward_splits_have_no_temporal_overlap() -> None:
    """Every fold's train window must strictly precede its test window."""
    prices = _deterministic_uptrend(300)
    result = walk_forward_select(
        prices,
        strategy_cls=_ExposureStrategy,
        param_grid={"invested": [0.0, 0.9]},
        initial_cash=100_000.0,
        train_bars=100,
        test_bars=50,
    )
    assert isinstance(result, WalkForwardResult)
    for fold in result.folds:
        # train ends strictly before test starts within the fold (no overlap).
        assert fold.train_end < fold.test_start
        # and the test window is non-degenerate.
        assert fold.test_start <= fold.test_end


def test_walk_forward_produces_expected_split_count() -> None:
    """Fold count follows (n - train_bars) // test_bars and stitches OOS returns."""
    prices = _deterministic_uptrend(300)
    result = walk_forward_select(
        prices,
        strategy_cls=_ExposureStrategy,
        param_grid={"invested": [0.0, 0.9]},
        initial_cash=100_000.0,
        train_bars=100,
        test_bars=50,
    )
    assert len(result.folds) == (300 - 100) // 50  # == 4
    assert result.n_param_combos == 2
    assert len(result.oos_daily_returns) == len(result.folds) * 50


def test_walk_forward_folds_advance_without_test_overlap() -> None:
    """Consecutive folds' test windows are disjoint and ordered forward in time."""
    prices = _deterministic_uptrend(300)
    result = walk_forward_select(
        prices,
        strategy_cls=_ExposureStrategy,
        param_grid={"invested": [0.0, 0.9]},
        initial_cash=100_000.0,
        train_bars=100,
        test_bars=50,
    )
    test_starts = [f.test_start for f in result.folds]
    test_ends = [f.test_end for f in result.folds]
    # strictly increasing test starts
    assert test_starts == sorted(test_starts)
    assert len(set(test_starts)) == len(test_starts)
    # each fold's test ends before the next fold's test begins
    for end, nxt_start in zip(test_ends[:-1], test_starts[1:], strict=True):
        assert end < nxt_start


def test_walk_forward_selects_invested_leg_on_uptrend() -> None:
    """On a clean uptrend the harness picks the invested param and is OOS-positive."""
    prices = _deterministic_uptrend(300)
    result = walk_forward_select(
        prices,
        strategy_cls=_ExposureStrategy,
        param_grid={"invested": [0.0, 0.9]},
        initial_cash=100_000.0,
        train_bars=100,
        test_bars=50,
    )
    assert all(f.chosen_params == {"invested": 0.9} for f in result.folds)
    assert result.oos_sharpe is not None and result.oos_sharpe > 0


# ── D. Cross-module: walk-forward + cost model wired together ──────────────────


def test_walk_forward_honours_cost_model_passthrough() -> None:
    """A cost model threaded into walk_forward_select still yields disjoint folds.

    Exercises engine + costs + walk_forward together: the cost model must flow
    through to the per-fold backtests without breaking the split structure.
    """
    prices = _deterministic_uptrend(300)
    result = walk_forward_select(
        prices,
        strategy_cls=_ExposureStrategy,
        param_grid={"invested": [0.0, 0.9]},
        initial_cash=100_000.0,
        train_bars=100,
        test_bars=50,
        cost_model=CostModel(default_bps=20.0),
    )
    assert len(result.folds) == 4
    for fold in result.folds:
        assert fold.train_end < fold.test_start
    assert len(result.oos_daily_returns) == 4 * 50
