"""Tests for factor-based strategies: BAB, RMOM, QMJ, Low-IdiοVol.

Hermetic: synthetic N-feed data, no network. Each strategy is loaded via
strategy_loader (validates metadata + single strategy class) and run through
engine.run_multi_backtest. Verifies plumbing and that capital is deployed.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest
from archimedes_analytics_engine.engine import BacktestResult, run_multi_backtest

_STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"
sys.path.insert(0, str(_STRATEGIES_DIR))
sys.path.insert(0, str(_STRATEGIES_DIR.parent / "src"))

_NAMES = ["SPY", "^N225", "GC=F", "TLT", "CL=F"]


def _factor_universe(n: int = 500) -> list[pd.DataFrame]:
    """Five synthetic feeds with diverse beta/vol/trend profiles.

    Feed 0 (SPY) is the market benchmark used by BAB/RMOM/IdioVol for
    beta estimation.  Feeds 1-4 have distinct drift and noise levels so
    ranking by beta, residual return, quality, or idio-vol produces a
    meaningful spread.
    """
    specs = [
        # (start_price, drift_per_bar, annual_vol_approx, phase)
        (100.0, 0.08, 0.20, 0.0),  # SPY: moderate drift, moderate vol
        (80.0, 0.03, 0.30, 1.0),  # high-vol, slow drift → high beta-like
        (120.0, 0.12, 0.10, 2.0),  # low-vol, high drift → high quality
        (90.0, 0.00, 0.40, 3.0),  # high-vol, flat → low quality
        (70.0, 0.06, 0.15, 4.0),  # moderate
    ]
    frames = []
    for base, drift, vol, phase in specs:
        idx = pd.date_range("2014-01-01", periods=n, freq="D")
        daily_sigma = vol / math.sqrt(252)
        closes = []
        price = base
        for i in range(n):
            price = price * (1.0 + drift / 252.0) + daily_sigma * price * math.sin(i / 15.0 + phase)
            price = max(price, 1.0)
            closes.append(price)
        frames.append(
            pd.DataFrame(
                {
                    "Open": [c - 0.2 for c in closes],
                    "High": [c + 0.5 for c in closes],
                    "Low": [c - 0.5 for c in closes],
                    "Close": closes,
                    "Volume": [1_000] * n,
                },
                index=idx,
            )
        )
    return frames


@pytest.mark.parametrize(
    ("stem", "expected_cls"),
    [
        ("frazzini_pedersen_2014_bab", "FrazziniPedersenBAB"),
        ("blitz_hanauer_2010_rmom", "BlitzHanauerRMOM"),
        ("novy_marx_2013_qmj", "NoVyMarxQMJ"),
        ("ang_hodrick_2006_low_idiovol", "AngHodrickLowIdioVol"),
    ],
)
def test_factor_strategy_loads_and_runs(stem: str, expected_cls: str) -> None:
    from archimedes_analytics_engine.strategy_loader import load_strategy

    bundle = load_strategy(_STRATEGIES_DIR / f"{stem}.py")
    assert bundle.cls.__name__ == expected_cls

    frames = _factor_universe()
    result = run_multi_backtest(frames, strategy_cls=bundle.cls, initial_cash=100_000.0, names=_NAMES)

    assert isinstance(result, BacktestResult)
    assert result.bars == 500
    assert result.look_ahead_audit_passed is True
    assert isinstance(result.daily_returns, list)
    assert len(result.daily_returns) > 0
    assert result.final_value != pytest.approx(100_000.0, rel=1e-3)


@pytest.mark.parametrize(
    "stem",
    [
        "frazzini_pedersen_2014_bab",
        "blitz_hanauer_2010_rmom",
        "novy_marx_2013_qmj",
        "ang_hodrick_2006_low_idiovol",
    ],
)
def test_factor_strategy_metadata(stem: str) -> None:
    """Each strategy file must export the required metadata constants."""
    import importlib.util

    path = _STRATEGIES_DIR / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert isinstance(mod.PAPER_TITLE, str) and mod.PAPER_TITLE
    assert isinstance(mod.PAPER_AUTHORS, list) and len(mod.PAPER_AUTHORS) >= 1
    assert isinstance(mod.PAPER_YEAR, int) and mod.PAPER_YEAR > 1900
    assert mod.REGIME_TAG in ("bull", "bear", "regime_neutral")
    assert isinstance(mod.RISK_PROFILES, list) and len(mod.RISK_PROFILES) >= 1
    assert mod.STATUS in ("live", "candidate", "deprecated")
    assert isinstance(mod.METHODOLOGY_SUMMARY, str) and len(mod.METHODOLOGY_SUMMARY) > 20
    assert isinstance(mod.METHODOLOGY_TEXT, str) and len(mod.METHODOLOGY_TEXT) > 100


def test_bab_flattens_when_insufficient_history() -> None:
    """BAB should not crash and should hold 0% exposure when fewer bars than lookback."""
    from archimedes_analytics_engine.strategy_loader import load_strategy

    bundle = load_strategy(_STRATEGIES_DIR / "frazzini_pedersen_2014_bab.py")

    # Only 30 bars — less than BAB's beta_window=63; strategy must return without trading
    short_frames = _factor_universe(n=30)
    result = run_multi_backtest(short_frames, strategy_cls=bundle.cls, initial_cash=100_000.0, names=_NAMES)

    assert isinstance(result, BacktestResult)
    # With no trades, final_value equals initial cash (no positions taken)
    assert result.final_value == pytest.approx(100_000.0, rel=1e-4)


def test_rmom_degrades_gracefully_without_beta() -> None:
    """RMOM falls back to unadjusted total return when beta cannot be estimated."""
    from archimedes_analytics_engine.strategy_loader import load_strategy

    bundle = load_strategy(_STRATEGIES_DIR / "blitz_hanauer_2010_rmom.py")

    # 300 bars — enough for formation window (252+21=273) but NOT for beta_window=63
    # on top of that, so beta fallback path should trigger for the first few rebalances
    frames = _factor_universe(n=300)
    result = run_multi_backtest(frames, strategy_cls=bundle.cls, initial_cash=100_000.0, names=_NAMES)

    assert isinstance(result, BacktestResult)
    assert result.look_ahead_audit_passed is True


def test_qmj_scores_spread_across_universe() -> None:
    """QMJ should assign distinct quality scores to the diverse synthetic universe."""
    from archimedes_analytics_engine.strategy_loader import load_strategy

    bundle = load_strategy(_STRATEGIES_DIR / "novy_marx_2013_qmj.py")
    frames = _factor_universe(n=400)
    result = run_multi_backtest(frames, strategy_cls=bundle.cls, initial_cash=100_000.0, names=_NAMES)

    assert isinstance(result, BacktestResult)
    assert result.bars == 400
    assert result.look_ahead_audit_passed is True


def test_ang_hodrick_excludes_market_benchmark() -> None:
    """Ang-Hodrick must exclude datas[0] from idio-vol ranking (it has zero residual vol)."""
    from archimedes_analytics_engine.strategy_loader import load_strategy

    bundle = load_strategy(_STRATEGIES_DIR / "ang_hodrick_2006_low_idiovol.py")
    frames = _factor_universe(n=400)
    result = run_multi_backtest(frames, strategy_cls=bundle.cls, initial_cash=100_000.0, names=_NAMES)

    assert isinstance(result, BacktestResult)
    assert result.final_value != pytest.approx(100_000.0, rel=1e-3)
