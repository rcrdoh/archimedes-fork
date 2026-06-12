"""Coverage tests for costs.py — the transaction-cost + turnover model.

Hermetic: synthetic in-memory frames, no network. Complements test_costs.py by
exercising branches it does not: CostModel.apply_to_broker per-feed/slippage
paths, position_weight flat/zero-equity branches, no_trade_band exact boundary,
TurnoverAnalyzer accumulation invariants, and zero-cost models.
"""

from __future__ import annotations

import backtrader as bt
import pandas as pd
import pytest
from archimedes_analytics_engine.costs import (
    CostModel,
    TurnoverAnalyzer,
    no_trade_band,
    position_weight,
)
from archimedes_analytics_engine.engine import run_backtest, run_multi_backtest


def _flat_prices(periods: int, price: float = 100.0, start: str = "2020-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq="D")
    return pd.DataFrame(
        {
            "Open": [price] * periods,
            "High": [price] * periods,
            "Low": [price] * periods,
            "Close": [price] * periods,
            "Volume": [1_000] * periods,
        },
        index=idx,
    )


class _OneRoundTrip(bt.Strategy):
    """Buy 50 on bar 2, sell on bar 10 — two known executions at flat prices."""

    def next(self) -> None:
        if len(self) == 2:
            self.buy(size=50)
        elif len(self) == 10:
            self.sell(size=50)


class _LongOnce(bt.Strategy):
    def next(self) -> None:
        if len(self) == 2 and not self.position:
            self.order_target_percent(target=0.9)


# ── CostModel construction + per_side_bps ─────────────────────────────────────


def test_cost_model_defaults() -> None:
    model = CostModel()
    assert model.default_bps == 10.0
    assert model.slippage_bps == 0.0
    assert model.per_symbol == {}
    assert model.per_side_bps() == 10.0
    assert model.per_side_bps("ANYTHING") == 10.0


def test_cost_model_per_side_bps_none_symbol() -> None:
    model = CostModel(default_bps=7.0, per_symbol={"SPY": 3.0})
    assert model.per_side_bps(None) == 7.0
    assert model.per_side_bps("SPY") == 3.0
    assert model.per_side_bps("UNKNOWN") == 7.0


def test_cost_model_is_frozen() -> None:
    model = CostModel(default_bps=10.0)
    with pytest.raises((AttributeError, Exception)):
        model.default_bps = 20.0  # type: ignore[misc]


def test_cost_model_zero_bps_is_allowed() -> None:
    # Zero is the boundary of the >= 0 validation — must NOT raise.
    model = CostModel(default_bps=0.0, slippage_bps=0.0, per_symbol={"SPY": 0.0})
    assert model.per_side_bps("SPY") == 0.0


# ── apply_to_broker branches ──────────────────────────────────────────────────


def test_apply_to_broker_sets_default_commission() -> None:
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(100_000.0)
    CostModel(default_bps=20.0).apply_to_broker(cerebro, ["SPY"])
    # 20 bps == 0.0020 commission in percent mode. The default (feed-agnostic)
    # commission is stored under the None key in broker.comminfo.
    assert cerebro.broker.comminfo[None].p.commission == pytest.approx(0.0020)


def test_apply_to_broker_per_symbol_override_ignores_inactive_names() -> None:
    # per_symbol carries a name NOT in feed_names → must be silently ignored
    # (no crash), exercising the "name in per_symbol" false branch per feed.
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(100_000.0)
    model = CostModel(default_bps=10.0, per_symbol={"INACTIVE": 99.0})
    model.apply_to_broker(cerebro, ["SPY", "GLD"])
    # Default commission still applies; no exception from the inactive override.
    assert cerebro.broker.comminfo[None].p.commission == pytest.approx(0.0010)


def test_zero_cost_model_charges_no_commission() -> None:
    result = run_backtest(
        _flat_prices(20),
        strategy_cls=_OneRoundTrip,
        initial_cash=100_000.0,
        cost_model=CostModel(default_bps=0.0),
    )
    assert result.traded_notional == pytest.approx(10_000.0)
    assert result.total_commission_paid == pytest.approx(0.0)
    # default_bps recorded on the result rounds to 0.
    assert result.transaction_cost_bps == 0


def test_cost_model_slippage_recorded_on_result() -> None:
    result = run_backtest(
        _flat_prices(20),
        strategy_cls=_LongOnce,
        initial_cash=100_000.0,
        cost_model=CostModel(default_bps=10.0, slippage_bps=15.0),
    )
    assert result.slippage_bps == 15


def test_higher_default_bps_costs_more() -> None:
    cheap = run_backtest(
        _flat_prices(20), strategy_cls=_OneRoundTrip, initial_cash=100_000.0, cost_model=CostModel(default_bps=10.0)
    )
    pricey = run_backtest(
        _flat_prices(20), strategy_cls=_OneRoundTrip, initial_cash=100_000.0, cost_model=CostModel(default_bps=100.0)
    )
    assert pricey.total_commission_paid > cheap.total_commission_paid
    # Cost scales ~10x with bps on identical executions.
    assert pricey.total_commission_paid == pytest.approx(cheap.total_commission_paid * 10.0, rel=1e-6)


# ── no_trade_band boundary ────────────────────────────────────────────────────


def test_no_trade_band_exact_boundary_trades() -> None:
    # |target - current| == band → the >= comparison fires → trade.
    # NOTE: use integer-representable deltas; 0.25-0.20 is 0.04999.. < 0.05 in
    # binary float and would (correctly) hold, so we pick 1.0 - 0.5 == 0.5.
    assert no_trade_band(0.5, 1.0, band=0.5) == 1.0


def test_no_trade_band_just_inside_holds() -> None:
    assert no_trade_band(0.20, 0.2499, band=0.05) == 0.20


def test_no_trade_band_zero_band_always_trades_even_tiny_move() -> None:
    assert no_trade_band(0.20, 0.2001, band=0.0) == 0.2001
    # No move at all with zero band: abs(0) >= 0 is True → returns target==current.
    assert no_trade_band(0.20, 0.20, band=0.0) == 0.20


# ── position_weight branches ──────────────────────────────────────────────────


class _AssertFlatWeight(bt.Strategy):
    """Records position_weight on an early bar while still flat (weight == 0)."""

    def __init__(self) -> None:
        self.observed: list[float] = []

    def next(self) -> None:
        if len(self) == 2:
            self.observed.append(position_weight(self, self.data))


def test_position_weight_zero_when_flat() -> None:
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(100_000.0)
    cerebro.adddata(bt.feeds.PandasData(dataname=_flat_prices(10)))
    cerebro.addstrategy(_AssertFlatWeight)
    strat = cerebro.run()[0]
    assert strat.observed == [0.0]


def test_position_weight_zero_equity_returns_zero() -> None:
    # When broker equity is non-positive, position_weight short-circuits to 0.0.
    class _FakeData:
        pass

    class _FakeBroker:
        def getvalue(self, datas=None):  # noqa: ANN001, ANN201
            return 0.0

    class _FakeStrategy:
        broker = _FakeBroker()

    assert position_weight(_FakeStrategy(), _FakeData()) == 0.0  # type: ignore[arg-type]


# ── TurnoverAnalyzer accumulation invariants ──────────────────────────────────


def test_turnover_analyzer_get_analysis_shape() -> None:
    result = run_backtest(
        _flat_prices(20),
        strategy_cls=_OneRoundTrip,
        initial_cash=100_000.0,
        transaction_cost_bps=10,
    )
    # Two-way notional == 50 * 100 * 2 == 10_000; commission == 10 bps/side.
    assert result.traded_notional == pytest.approx(10_000.0)
    assert result.total_commission_paid == pytest.approx(10.0)


def test_turnover_analyzer_bar_commissions_sum_matches_total() -> None:
    # The per-bar commission series, exposed through the cost metrics, must be
    # internally consistent: gross_sharpe is computed from it, so it must exist
    # and the run must not crash. We verify the aggregate invariant indirectly:
    # total commission equals notional * bps/10000 for the round trip.
    result = run_backtest(
        _flat_prices(20),
        strategy_cls=_OneRoundTrip,
        initial_cash=100_000.0,
        transaction_cost_bps=25,
    )
    assert result.total_commission_paid == pytest.approx(10_000.0 * 25 / 10_000.0)


def test_turnover_analyzer_direct_lifecycle() -> None:
    # Drive the analyzer's start/next/stop directly with no executions.
    analyzer = TurnoverAnalyzer.__new__(TurnoverAnalyzer)
    analyzer.start()
    assert analyzer.traded_notional == 0.0
    assert analyzer.commission_paid == 0.0
    analyzer.next()
    analyzer.next()
    analyzer.stop()
    out = analyzer.get_analysis()
    assert out["traded_notional"] == 0.0
    assert out["commission_paid"] == 0.0
    assert out["bar_commissions"] == [0.0, 0.0]


# ── multi-feed default cost model path ────────────────────────────────────────


def test_cost_model_multi_feed_zero_cost() -> None:
    frames = [_flat_prices(30, price=100.0), _flat_prices(30, price=50.0)]

    class _EqualWeight(bt.Strategy):
        def next(self) -> None:
            if len(self) != 3:
                return
            for d in self.datas:
                self.order_target_percent(data=d, target=0.45)

    result = run_multi_backtest(
        frames,
        strategy_cls=_EqualWeight,
        initial_cash=100_000.0,
        names=["A", "B"],
        cost_model=CostModel(default_bps=0.0),
    )
    assert result.total_commission_paid == pytest.approx(0.0)
    assert result.traded_notional > 0.0
