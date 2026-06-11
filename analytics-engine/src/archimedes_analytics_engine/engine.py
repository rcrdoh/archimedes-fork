from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

import backtrader as bt
import pandas as pd

ANNUALIZATION = 252
RF_ANNUAL = 0.05  # 5% annual risk-free rate
RF_DAILY = RF_ANNUAL / ANNUALIZATION
BACKTEST_ENGINE_TAG = "backtrader"


@dataclass
class BacktestResult:
    final_value: float
    total_return_pct: float
    equity_curve: list[float]
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown_pct: float | None = None
    max_drawdown_duration_bars: int | None = None
    cagr: float | None = None
    total_trades: int = 0
    win_rate: float | None = None
    profit_factor: float | None = None
    avg_holding_period_days: float | None = None
    correlation_to_spy: float | None = None
    correlation_to_btc: float | None = None
    monthly_returns: list[float] = field(default_factory=list)
    daily_returns: list[float] = field(default_factory=list)
    transaction_cost_bps: int = 10
    slippage_bps: int = 0
    walk_forward_split: float | None = None
    out_of_sample_sharpe: float | None = None
    look_ahead_audit_passed: bool = False
    backtest_engine: str = BACKTEST_ENGINE_TAG
    bars: int = 0
    backtest_start: str | None = None
    backtest_end: str | None = None


class BuyAndHoldStrategy(bt.Strategy):
    PAPER_ARXIV_ID: str | None = None
    PAPER_TITLE = "Buy-and-Hold Baseline"
    METHODOLOGY_TEXT = (
        "Allocate the full available cash to the single asset on the first bar "
        "where no position is open; hold the position to the end of the period."
    )
    PAPER_CLAIMED_SHARPE: float | None = None

    def next(self) -> None:
        if not self.position:
            size = int(self.broker.getcash() / self.data.close[0])
            if size > 0:
                self.buy(size=size)


def _safe_get(d: Any, *keys: str, default: Any = None) -> Any:
    cur = d
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _build_equity_curve(initial_cash: float, daily_pairs: list[tuple]) -> list[float]:
    equity = initial_cash
    curve = [initial_cash]
    for _, value in daily_pairs:
        equity *= 1.0 + float(value)
        curve.append(float(equity))
    return curve


def _compute_sortino(daily_returns: list[float]) -> float | None:
    if not daily_returns:
        return None
    mean = statistics.fmean(daily_returns)
    downside = [r for r in daily_returns if r < 0]
    if not downside:
        return None
    dd_rms = math.sqrt(sum(r * r for r in downside) / len(downside))
    if dd_rms == 0:
        return None
    return ((mean - RF_DAILY) / dd_rms) * math.sqrt(ANNUALIZATION)


def _compute_cagr(initial: float, final: float, bars: int) -> float | None:
    if bars <= 0 or initial <= 0 or final <= 0:
        return None
    years = bars / ANNUALIZATION
    if years <= 0:
        return None
    return (final / initial) ** (1.0 / years) - 1.0


def _trade_stats(
    trade: dict,
) -> tuple[int, float | None, float | None, float | None]:
    total_closed = _safe_get(trade, "total", "closed", default=0) or 0
    won = _safe_get(trade, "won", "total", default=0) or 0
    won_pnl = _safe_get(trade, "won", "pnl", "total", default=0.0) or 0.0
    lost_pnl = _safe_get(trade, "lost", "pnl", "total", default=0.0) or 0.0
    avg_len = _safe_get(trade, "len", "average", default=None)

    if total_closed == 0:
        return 0, None, None, None

    win_rate = won / total_closed
    profit_factor: float | None
    profit_factor = float(won_pnl) / abs(float(lost_pnl)) if lost_pnl else None
    avg_len_f = float(avg_len) if avg_len is not None else None
    return int(total_closed), float(win_rate), profit_factor, avg_len_f


def _lookahead_audit_passed(cerebro: bt.Cerebro) -> bool:
    coc = getattr(cerebro.broker.p, "coc", False)
    coo = getattr(cerebro.broker.p, "coo", False)
    return not coc and not coo


def run_backtest(
    prices: pd.DataFrame,
    *,
    strategy_cls: type[bt.Strategy],
    initial_cash: float,
    transaction_cost_bps: int = 10,
    slippage_bps: int = 0,
) -> BacktestResult:
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=transaction_cost_bps / 10_000)
    if slippage_bps > 0:
        cerebro.broker.set_slippage_perc(perc=slippage_bps / 10_000)

    feed = bt.feeds.PandasData(dataname=prices)
    cerebro.adddata(feed)
    cerebro.addstrategy(strategy_cls)
    _add_analyzers(cerebro)

    strategy = cerebro.run()[0]

    bars = len(prices)
    return _extract_result(
        cerebro=cerebro,
        strategy=strategy,
        initial_cash=initial_cash,
        bars=bars,
        backtest_start=prices.index[0].isoformat() if bars else None,
        backtest_end=prices.index[-1].isoformat() if bars else None,
        transaction_cost_bps=transaction_cost_bps,
        slippage_bps=slippage_bps,
    )


def _extract_result(
    *,
    cerebro: bt.Cerebro,
    strategy: bt.Strategy,
    initial_cash: float,
    bars: int,
    backtest_start: str | None,
    backtest_end: str | None,
    transaction_cost_bps: int,
    slippage_bps: int,
) -> BacktestResult:
    """Pull metrics off a finished cerebro run. Shared by single- and multi-asset runners."""
    final_value = float(cerebro.broker.getvalue())
    total_return_pct = ((final_value / initial_cash) - 1.0) * 100.0

    time_returns_raw = strategy.analyzers.timereturn.get_analysis()
    daily_pairs = sorted(time_returns_raw.items(), key=lambda x: x[0])
    daily_returns = [float(v) for _, v in daily_pairs]
    equity_curve = _build_equity_curve(initial_cash, daily_pairs)

    monthly_raw = strategy.analyzers.monthly.get_analysis()
    monthly_returns = [float(v) for _, v in sorted(monthly_raw.items(), key=lambda x: x[0])]

    sharpe_raw = strategy.analyzers.sharpe.get_analysis().get("sharperatio")
    sharpe = float(sharpe_raw) if sharpe_raw is not None else None

    dd_analysis = strategy.analyzers.dd.get_analysis()
    max_dd_pct_raw = _safe_get(dd_analysis, "max", "drawdown")
    max_dd_len_raw = _safe_get(dd_analysis, "max", "len")
    max_dd_pct = float(max_dd_pct_raw) if max_dd_pct_raw is not None else None
    max_dd_len = int(max_dd_len_raw) if max_dd_len_raw is not None else None

    cagr = _compute_cagr(initial_cash, final_value, bars)

    calmar: float | None = None
    if cagr is not None and max_dd_pct is not None and max_dd_pct > 0:
        calmar = cagr / (max_dd_pct / 100.0)

    sortino = _compute_sortino(daily_returns)

    trades_analysis = strategy.analyzers.trades.get_analysis()
    total_trades, win_rate, profit_factor, avg_len = _trade_stats(trades_analysis)

    look_ahead_passed = _lookahead_audit_passed(cerebro)

    return BacktestResult(
        final_value=final_value,
        total_return_pct=total_return_pct,
        equity_curve=equity_curve,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_duration_bars=max_dd_len,
        cagr=cagr,
        total_trades=total_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_holding_period_days=avg_len,
        monthly_returns=monthly_returns,
        daily_returns=daily_returns,
        transaction_cost_bps=transaction_cost_bps,
        slippage_bps=slippage_bps,
        look_ahead_audit_passed=look_ahead_passed,
        bars=bars,
        backtest_start=backtest_start,
        backtest_end=backtest_end,
    )


def _add_analyzers(cerebro: bt.Cerebro) -> None:
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="timereturn")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="monthly", timeframe=bt.TimeFrame.Months)
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio,
        _name="sharpe",
        timeframe=bt.TimeFrame.Days,
        annualize=True,
        riskfreerate=RF_ANNUAL,
    )
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")


def run_pairs_backtest(
    prices_a: pd.DataFrame,
    prices_b: pd.DataFrame,
    *,
    strategy_cls: type[bt.Strategy],
    initial_cash: float,
    name_a: str = "leg_a",
    name_b: str = "leg_b",
    transaction_cost_bps: int = 10,
    slippage_bps: int = 0,
) -> BacktestResult:
    """Run a two-asset (pairs / relative-value) strategy in a single cerebro.

    Both price frames are inner-joined on their datetime index first so the two
    feeds are bar-aligned — the strategy can rely on ``self.datas[0]`` and
    ``self.datas[1]`` advancing together. Metrics are computed on portfolio value,
    so the existing analyzer + extraction path is reused unchanged.
    """
    common_index = prices_a.index.intersection(prices_b.index)
    if len(common_index) == 0:
        raise ValueError("prices_a and prices_b share no common dates; cannot align pair feeds")
    aligned_a = prices_a.loc[common_index].sort_index()
    aligned_b = prices_b.loc[common_index].sort_index()

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=transaction_cost_bps / 10_000)
    if slippage_bps > 0:
        cerebro.broker.set_slippage_perc(perc=slippage_bps / 10_000)

    cerebro.adddata(bt.feeds.PandasData(dataname=aligned_a), name=name_a)
    cerebro.adddata(bt.feeds.PandasData(dataname=aligned_b), name=name_b)
    cerebro.addstrategy(strategy_cls)
    _add_analyzers(cerebro)

    strategy = cerebro.run()[0]

    bars = len(common_index)
    return _extract_result(
        cerebro=cerebro,
        strategy=strategy,
        initial_cash=initial_cash,
        bars=bars,
        backtest_start=common_index[0].isoformat() if bars else None,
        backtest_end=common_index[-1].isoformat() if bars else None,
        transaction_cost_bps=transaction_cost_bps,
        slippage_bps=slippage_bps,
    )


def run_multi_backtest(
    prices_list: list[pd.DataFrame],
    *,
    strategy_cls: type[bt.Strategy],
    initial_cash: float,
    names: list[str] | None = None,
    transaction_cost_bps: int = 10,
    slippage_bps: int = 0,
) -> BacktestResult:
    """Run an N-asset (cross-sectional / portfolio) strategy in a single cerebro.

    The N-feed generalization of :func:`run_pairs_backtest`. All price frames are
    inner-joined on their common datetime index first, so every feed advances
    together bar-for-bar — the strategy can rely on ``self.datas[i]`` for
    ``i in range(N)`` being aligned and rank/weight across the universe each bar.
    Metrics are computed on portfolio value, so the existing analyzer +
    extraction path (:func:`_add_analyzers` / :func:`_extract_result`) is reused
    unchanged, keeping metric shapes identical across single / pair / N-asset runs.
    """
    if not prices_list:
        raise ValueError("prices_list is empty; need at least one price frame")
    if names is not None and len(names) != len(prices_list):
        raise ValueError(f"names has {len(names)} entries but prices_list has {len(prices_list)}")

    feed_names = names if names is not None else [f"leg_{i}" for i in range(len(prices_list))]

    # N-way index intersection: only bars present in every feed are backtested.
    common_index = prices_list[0].index
    for prices in prices_list[1:]:
        common_index = common_index.intersection(prices.index)
    if len(common_index) == 0:
        raise ValueError("price frames share no common dates; cannot align feeds")

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=transaction_cost_bps / 10_000)
    if slippage_bps > 0:
        cerebro.broker.set_slippage_perc(perc=slippage_bps / 10_000)

    for prices, name in zip(prices_list, feed_names, strict=True):
        aligned = prices.loc[common_index].sort_index()
        cerebro.adddata(bt.feeds.PandasData(dataname=aligned), name=name)
    cerebro.addstrategy(strategy_cls)
    _add_analyzers(cerebro)

    strategy = cerebro.run()[0]

    bars = len(common_index)
    return _extract_result(
        cerebro=cerebro,
        strategy=strategy,
        initial_cash=initial_cash,
        bars=bars,
        backtest_start=common_index[0].isoformat() if bars else None,
        backtest_end=common_index[-1].isoformat() if bars else None,
        transaction_cost_bps=transaction_cost_bps,
        slippage_bps=slippage_bps,
    )


def run_buy_and_hold(
    prices: pd.DataFrame,
    *,
    initial_cash: float,
    transaction_cost_bps: int = 10,
    slippage_bps: int = 0,
) -> BacktestResult:
    return run_backtest(
        prices,
        strategy_cls=BuyAndHoldStrategy,
        initial_cash=initial_cash,
        transaction_cost_bps=transaction_cost_bps,
        slippage_bps=slippage_bps,
    )
