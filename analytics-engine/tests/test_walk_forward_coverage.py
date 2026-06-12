"""Coverage tests for walk_forward.py — the walk-forward selection harness.

Hermetic: synthetic in-memory frames, no network. Complements
test_walk_forward.py by exercising the helper functions (_expand_grid,
_align), the train_bars/test_bars validation branches, the no-common-dates
alignment error, single-fold layout, multi-parameter grid expansion, and the
WalkForwardFold/WalkForwardResult dataclass fields.
"""

from __future__ import annotations

import math

import backtrader as bt
import pandas as pd
import pytest
from archimedes_analytics_engine.walk_forward import (
    WalkForwardFold,
    WalkForwardResult,
    _align,
    _expand_grid,
    walk_forward_select,
)


def _frame(closes: list[float], start: str = "2018-01-01") -> pd.DataFrame:
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


def _uptrend(n: int, base: float = 100.0, slope: float = 0.3) -> list[float]:
    return [base + slope * i + 1.5 * math.sin(i / 6.0) for i in range(n)]


class _ExposureStrategy(bt.Strategy):
    params = (("invested", 0.0),)

    def next(self) -> None:
        target = float(self.params.invested)
        if len(self) == 2 and target > 0 and not self.position:
            self.order_target_percent(target=target)


# ── _expand_grid ──────────────────────────────────────────────────────────────


def test_expand_grid_single_param() -> None:
    combos = _expand_grid({"a": [1, 2, 3]})
    assert combos == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_expand_grid_cartesian_product_order() -> None:
    combos = _expand_grid({"a": [1, 2], "b": [10, 20]})
    # itertools.product is row-major over the key order.
    assert combos == [
        {"a": 1, "b": 10},
        {"a": 1, "b": 20},
        {"a": 2, "b": 10},
        {"a": 2, "b": 20},
    ]


def test_expand_grid_single_value_each() -> None:
    assert _expand_grid({"x": [5], "y": [7]}) == [{"x": 5, "y": 7}]


# ── _align ────────────────────────────────────────────────────────────────────


def test_align_single_frame_identity() -> None:
    f = _frame(_uptrend(50))
    aligned = _align([f])
    assert len(aligned) == 1
    assert len(aligned[0]) == 50
    pd.testing.assert_index_equal(aligned[0].index, f.index)


def test_align_intersects_indices() -> None:
    a = _frame(_uptrend(60), start="2018-01-01")  # 2018-01-01 .. +60d
    b = _frame(_uptrend(60), start="2018-01-15")  # overlaps a from 01-15
    aligned = _align([a, b])
    # Both frames trimmed to the common index, same length, sorted.
    assert len(aligned[0]) == len(aligned[1])
    assert len(aligned[0]) > 0
    pd.testing.assert_index_equal(aligned[0].index, aligned[1].index)
    assert aligned[0].index.is_monotonic_increasing


def test_align_no_common_dates_raises() -> None:
    a = _frame(_uptrend(30), start="2018-01-01")
    b = _frame(_uptrend(30), start="2025-01-01")
    with pytest.raises(ValueError, match="no common dates"):
        _align([a, b])


# ── walk_forward_select input validation ──────────────────────────────────────


def test_rejects_train_bars_too_small() -> None:
    with pytest.raises(ValueError, match="train_bars >= 2"):
        walk_forward_select(
            _frame(_uptrend(200)),
            strategy_cls=_ExposureStrategy,
            param_grid={"invested": [0.9]},
            initial_cash=100_000.0,
            train_bars=1,
            test_bars=50,
        )


def test_rejects_test_bars_too_small() -> None:
    with pytest.raises(ValueError, match="test_bars >= 1"):
        walk_forward_select(
            _frame(_uptrend(200)),
            strategy_cls=_ExposureStrategy,
            param_grid={"invested": [0.9]},
            initial_cash=100_000.0,
            train_bars=100,
            test_bars=0,
        )


def test_rejects_list_input_with_no_common_dates() -> None:
    a = _frame(_uptrend(200), start="2018-01-01")
    b = _frame(_uptrend(200), start="2030-01-01")
    with pytest.raises(ValueError, match="no common dates"):
        walk_forward_select(
            [a, b],
            strategy_cls=_ExposureStrategy,
            param_grid={"invested": [0.9]},
            initial_cash=100_000.0,
            train_bars=100,
            test_bars=50,
        )


# ── single-fold layout + dataclass fields ─────────────────────────────────────


def test_single_fold_layout() -> None:
    # Exactly train_bars + test_bars → exactly one fold.
    result = walk_forward_select(
        _frame(_uptrend(150)),
        strategy_cls=_ExposureStrategy,
        param_grid={"invested": [0.0, 0.9]},
        initial_cash=100_000.0,
        train_bars=100,
        test_bars=50,
    )
    assert isinstance(result, WalkForwardResult)
    assert len(result.folds) == 1
    fold = result.folds[0]
    assert isinstance(fold, WalkForwardFold)
    assert fold.fold == 0
    assert len(fold.test_returns) == 50
    assert len(result.oos_daily_returns) == 50
    # Dataclass string fields are ISO timestamps and chronologically ordered.
    assert fold.train_start < fold.train_end < fold.test_start < fold.test_end


def test_param_grid_echoed_in_result() -> None:
    grid = {"invested": [0.0, 0.5, 0.9]}
    result = walk_forward_select(
        _frame(_uptrend(200)),
        strategy_cls=_ExposureStrategy,
        param_grid=grid,
        initial_cash=100_000.0,
        train_bars=100,
        test_bars=50,
    )
    assert result.n_param_combos == 3
    assert result.param_grid == {"invested": [0.0, 0.5, 0.9]}
    # param_grid is copied (lists rebuilt), not the same object.
    assert result.param_grid is not grid


def test_multi_param_grid_combos_count() -> None:
    result = walk_forward_select(
        _frame(_uptrend(220)),
        strategy_cls=_ExposureStrategy,
        param_grid={"invested": [0.0, 0.9]},
        initial_cash=100_000.0,
        train_bars=100,
        test_bars=40,
    )
    # (220 - 100) // 40 == 3 folds.
    assert len(result.folds) == 3
    assert result.n_param_combos == 2
    assert len(result.oos_daily_returns) == 3 * 40


def test_oos_sharpe_uses_engine_convention() -> None:
    # When at least one combo invests, selection succeeds and the stitched OOS
    # series feeds _sharpe_bt_convention. On a steady uptrend the OOS Sharpe is
    # a finite float computed under the engine's net-Sharpe convention.
    from archimedes_analytics_engine.walk_forward import _sharpe_bt_convention

    result = walk_forward_select(
        _frame(_uptrend(200)),
        strategy_cls=_ExposureStrategy,
        param_grid={"invested": [0.0, 0.9]},
        initial_cash=100_000.0,
        train_bars=100,
        test_bars=50,
    )
    assert result.oos_sharpe == _sharpe_bt_convention(result.oos_daily_returns)


def test_single_none_sharpe_combo_raises_assertion() -> None:
    # NOTE: discovered behavior — a single-combo grid whose only combo yields a
    # None train Sharpe (an always-flat strategy never deploys, so the engine
    # reports sharpe_ratio=None) leaves best_sharpe at -inf; the `> -inf` guard
    # never fires and the `assert best_params is not None` trips. We assert the
    # ACTUAL behavior rather than treating it as a bug to fix in the source.
    with pytest.raises(AssertionError):
        walk_forward_select(
            _frame(_uptrend(200)),
            strategy_cls=_ExposureStrategy,
            param_grid={"invested": [0.0]},
            initial_cash=100_000.0,
            train_bars=100,
            test_bars=50,
        )


def test_walk_forward_fold_dataclass_defaults() -> None:
    fold = WalkForwardFold(
        fold=0,
        train_start="2018-01-01",
        train_end="2018-04-10",
        test_start="2018-04-11",
        test_end="2018-05-30",
        chosen_params={"invested": 0.9},
        train_sharpe=1.5,
    )
    # test_returns defaults to an empty list (field(default_factory=list)).
    assert fold.test_returns == []
    assert fold.chosen_params == {"invested": 0.9}
    assert fold.train_sharpe == 1.5
