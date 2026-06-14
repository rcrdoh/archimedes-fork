"""Tests for portfolio_backtester.profile_backtest — the simulator micro-benchmark.

Hermetic: no network, no DB, no .env. Builds a synthetic wide close panel and a
matching volume panel as pandas DataFrames (DatetimeIndex, one column per symbol),
exactly the shape ``_simulate_portfolio`` reads — it calls ``panel.pct_change()``
on the close panel and ``volume_panel * panel`` for dollar-volume, so both are
wide frames indexed by date with one column per symbol.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from archimedes.services.portfolio_backtester import profile_backtest


def _synthetic_panels(n_bars: int = 252, symbols: tuple[str, ...] = ("AAA", "BBB", "CCC")):
    """Deterministic synthetic close + volume panels for the profiler."""
    rng = np.random.default_rng(7)
    idx = pd.date_range("2020-01-01", periods=n_bars, freq="B")
    closes: dict[str, pd.Series] = {}
    volumes: dict[str, pd.Series] = {}
    for k, sym in enumerate(symbols):
        rets = rng.normal(0.0004, 0.012, n_bars)
        prices = 100.0 * (1.0 + k * 0.1) * np.cumprod(1.0 + rets)
        closes[sym] = pd.Series(prices, index=idx)
        volumes[sym] = pd.Series(rng.uniform(1_000_000, 5_000_000, n_bars), index=idx)
    return pd.DataFrame(closes), pd.DataFrame(volumes)


_WEIGHTS = {"AAA": 0.5, "BBB": 0.3, "CCC": 0.2}


def test_returns_all_expected_keys():
    panel, volume_panel = _synthetic_panels()
    result = profile_backtest(panel=panel, volume_panel=volume_panel, target_weights=_WEIGHTS, n_runs=5)
    expected = {
        "n_runs",
        "n_bars",
        "n_assets",
        "time_mean_ms",
        "time_median_ms",
        "time_min_ms",
        "time_max_ms",
        "time_std_ms",
        "peak_memory_kb",
        "bars_per_second",
        "deterministic",
    }
    assert expected == set(result.keys())


def test_n_runs_respected_and_timing_stats_ordered():
    panel, volume_panel = _synthetic_panels()
    result = profile_backtest(panel=panel, volume_panel=volume_panel, target_weights=_WEIGHTS, n_runs=8)
    assert result["n_runs"] == 8
    assert result["time_min_ms"] <= result["time_median_ms"] <= result["time_max_ms"]
    assert result["time_min_ms"] <= result["time_mean_ms"] <= result["time_max_ms"]
    assert result["time_std_ms"] >= 0.0


def test_deterministic_is_true_for_deterministic_simulator():
    panel, volume_panel = _synthetic_panels()
    result = profile_backtest(panel=panel, volume_panel=volume_panel, target_weights=_WEIGHTS, n_runs=6)
    assert result["deterministic"] is True


def test_bars_per_second_positive():
    panel, volume_panel = _synthetic_panels()
    result = profile_backtest(panel=panel, volume_panel=volume_panel, target_weights=_WEIGHTS, n_runs=4)
    assert result["bars_per_second"] > 0


def test_peak_memory_positive():
    panel, volume_panel = _synthetic_panels()
    result = profile_backtest(panel=panel, volume_panel=volume_panel, target_weights=_WEIGHTS, n_runs=3)
    assert result["peak_memory_kb"] > 0


def test_n_runs_below_one_raises():
    panel, volume_panel = _synthetic_panels()
    with pytest.raises(ValueError):
        profile_backtest(panel=panel, volume_panel=volume_panel, target_weights=_WEIGHTS, n_runs=0)


def test_empty_panel_raises():
    _, volume_panel = _synthetic_panels()
    empty = pd.DataFrame()
    with pytest.raises(ValueError):
        profile_backtest(panel=empty, volume_panel=volume_panel, target_weights=_WEIGHTS, n_runs=5)


def test_n_bars_and_n_assets_reported_correctly():
    panel, volume_panel = _synthetic_panels(n_bars=180, symbols=("AAA", "BBB"))
    result = profile_backtest(
        panel=panel,
        volume_panel=volume_panel,
        target_weights={"AAA": 0.6, "BBB": 0.4},
        n_runs=3,
    )
    assert result["n_bars"] == 180
    assert result["n_assets"] == 2
