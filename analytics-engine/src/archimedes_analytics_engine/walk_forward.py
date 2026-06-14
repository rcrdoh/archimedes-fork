"""Walk-forward parameter selection (third-wave item 3, roadmap Priority 2.3).

Parameters chosen in-sample and reported in-sample are the canonical source of
backtest overfitting. This harness makes any parameterized result credible:
parameters are selected on a trailing train window only, then evaluated on the
*next* window the selector never saw, rolling forward through the data. The
stitched out-of-sample return series is the honest performance estimate, and
``n_param_combos`` records exactly how many variants were tried — the right
``num_trials`` input for the DSR penalty (issue #537's "variants actually
tried" reading) rather than an unstated, unauditable search.

Anti-look-ahead mechanics, in order:

1. Fold k trains on bars ``[k*test_bars, k*test_bars + train_bars)`` and tests
   on the following ``test_bars`` bars — train always strictly precedes test.
2. Every grid combination is backtested on the train slice only; the best
   train Sharpe wins (ties: first in grid order, deterministic).
3. The winner is then run once over train+test, and only the final
   ``test_bars`` per-bar returns are kept as out-of-sample. Running over
   train+test lets indicator warm-up draw on *train* bars (data already
   available at the test start) instead of forcing a cold start — no future
   information is involved.
4. OOS fold returns are stitched chronologically; the summary Sharpe uses the
   same convention as the engine's net Sharpe so numbers are comparable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any

import backtrader as bt
import pandas as pd

from archimedes_analytics_engine.costs import CostModel
from archimedes_analytics_engine.engine import (
    BacktestResult,
    _sharpe_bt_convention,
    run_backtest,
    run_multi_backtest,
)


@dataclass
class WalkForwardFold:
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    chosen_params: dict[str, Any]
    train_sharpe: float | None
    test_returns: list[float] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    folds: list[WalkForwardFold]
    oos_daily_returns: list[float]  # all fold test returns, stitched chronologically
    oos_sharpe: float | None  # engine net-Sharpe convention on the stitched series
    n_param_combos: int  # honest num_trials input for the DSR penalty
    param_grid: dict[str, list[Any]]


def _expand_grid(param_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    # PERF: full Cartesian product, O(prod(len(v) for v in param_grid.values())) —
    # callers are expected to bound param_grid size before calling this.
    keys = list(param_grid.keys())
    return [dict(zip(keys, values, strict=True)) for values in product(*(param_grid[k] for k in keys))]


def _align(prices_list: list[pd.DataFrame]) -> list[pd.DataFrame]:
    common = prices_list[0].index
    for prices in prices_list[1:]:
        common = common.intersection(prices.index)
    if len(common) == 0:
        raise ValueError("price frames share no common dates; cannot align feeds")
    return [p.loc[common].sort_index() for p in prices_list]


def walk_forward_select(
    prices: pd.DataFrame | list[pd.DataFrame],
    *,
    strategy_cls: type[bt.Strategy],
    param_grid: dict[str, list[Any]],
    initial_cash: float,
    train_bars: int,
    test_bars: int,
    names: list[str] | None = None,
    transaction_cost_bps: int = 10,
    slippage_bps: int = 0,
    cost_model: CostModel | None = None,
) -> WalkForwardResult:
    """Roll a train/select/test cycle through the data; see module docstring.

    ``prices`` is a single OHLCV frame or a list of frames (multi-feed
    strategies run via ``run_multi_backtest`` with ``names`` passthrough).
    Raises if the grid is empty or the data is too short for one full fold.
    """
    if not param_grid or any(not v for v in param_grid.values()):
        raise ValueError("param_grid must have at least one parameter with at least one value")
    if train_bars < 2 or test_bars < 1:
        raise ValueError(f"need train_bars >= 2 and test_bars >= 1, got {train_bars}/{test_bars}")

    frames = _align([prices] if isinstance(prices, pd.DataFrame) else list(prices))
    n_bars = len(frames[0])
    if n_bars < train_bars + test_bars:
        raise ValueError(f"{n_bars} aligned bars < one fold of train_bars+test_bars = {train_bars + test_bars}")

    combos = _expand_grid(param_grid)

    def _run(start: int, stop: int, params: dict[str, Any]) -> BacktestResult:
        window = [f.iloc[start:stop] for f in frames]
        if len(window) == 1:
            return run_backtest(
                window[0],
                strategy_cls=strategy_cls,
                initial_cash=initial_cash,
                transaction_cost_bps=transaction_cost_bps,
                slippage_bps=slippage_bps,
                cost_model=cost_model,
                strategy_params=params,
            )
        return run_multi_backtest(
            window,
            strategy_cls=strategy_cls,
            initial_cash=initial_cash,
            names=names,
            transaction_cost_bps=transaction_cost_bps,
            slippage_bps=slippage_bps,
            cost_model=cost_model,
            strategy_params=params,
        )

    folds: list[WalkForwardFold] = []
    stitched: list[float] = []
    index = frames[0].index
    fold_no = 0
    while fold_no * test_bars + train_bars + test_bars <= n_bars:
        train_lo = fold_no * test_bars
        train_hi = train_lo + train_bars  # exclusive
        test_hi = train_hi + test_bars  # exclusive

        best_params: dict[str, Any] | None = None
        best_sharpe = -float("inf")
        for params in combos:
            train_result = _run(train_lo, train_hi, params)
            sharpe = train_result.sharpe_ratio if train_result.sharpe_ratio is not None else -float("inf")
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = params

        assert best_params is not None  # combos is non-empty by construction
        eval_result = _run(train_lo, test_hi, best_params)
        # Per-bar returns over train+test; keep only the test tail as OOS. The
        # engine emits exactly one return per bar — verify rather than assume,
        # since a silent misalignment would leak train bars into the OOS series.
        expected_bars = test_hi - train_lo
        if len(eval_result.daily_returns) != expected_bars:
            raise RuntimeError(
                f"fold {fold_no}: engine returned {len(eval_result.daily_returns)} per-bar returns "
                f"for a {expected_bars}-bar window; cannot slice the OOS tail safely"
            )
        test_returns = eval_result.daily_returns[-test_bars:]

        folds.append(
            WalkForwardFold(
                fold=fold_no,
                train_start=index[train_lo].isoformat(),
                train_end=index[train_hi - 1].isoformat(),
                test_start=index[train_hi].isoformat(),
                test_end=index[test_hi - 1].isoformat(),
                chosen_params=best_params,
                train_sharpe=None if best_sharpe == -float("inf") else best_sharpe,
                test_returns=test_returns,
            )
        )
        stitched.extend(test_returns)
        fold_no += 1

    return WalkForwardResult(
        folds=folds,
        oos_daily_returns=stitched,
        oos_sharpe=_sharpe_bt_convention(stitched),
        n_param_combos=len(combos),
        param_grid={k: list(v) for k, v in param_grid.items()},
    )
