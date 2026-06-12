"""Tests for the dividend-yield-proxy and defensive-quality strategies.

Hermetic: synthetic N-feed data, no network. Each strategy file is loaded via
the real strategy_loader (proving its metadata block + single strategy class
resolve) and run through engine.run_multi_backtest with named feeds. Metadata
is asserted by loading the module directly via importlib (StrategyBundle has no
``.module`` attribute). The real performance metrics live elsewhere; these
tests only guard the plumbing, the trade path, and the metadata block.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd
import pytest
from archimedes_analytics_engine.engine import BacktestResult, run_multi_backtest

_STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"
sys.path.insert(0, str(_STRATEGIES_DIR))
sys.path.insert(0, str(_STRATEGIES_DIR.parent / "src"))

# Feed names mirror the production universe; datas[0] (SPY) is the benchmark.
_NAMES = ["SPY", "^N225", "GC=F", "TLT", "CL=F"]


def _trending_universe(n: int = 500) -> list[pd.DataFrame]:
    """Five synthetic feeds with distinct drifts/phases so ranks/vols/betas differ."""
    specs = [(100.0, 0.06, 0.0), (80.0, 0.03, 1.0), (120.0, 0.01, 2.0), (90.0, 0.02, 3.0), (70.0, 0.05, 4.0)]
    frames = []
    for base, drift, phase in specs:
        idx = pd.date_range("2015-01-01", periods=n, freq="D")
        closes = [base + drift * i + 8.0 * math.sin(i / 20.0 + phase) for i in range(n)]
        frames.append(
            pd.DataFrame(
                {
                    "Open": [c - 0.3 for c in closes],
                    "High": [c + 0.6 for c in closes],
                    "Low": [c - 0.6 for c in closes],
                    "Close": closes,
                    "Volume": [1_000] * n,
                },
                index=idx,
            )
        )
    return frames


def _load_module(stem: str):
    path = _STRATEGIES_DIR / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"_meta_{stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CASES = [
    ("low_tan_wermers_2004_dividend_yield", "FamaFrenchDividendYield"),
    ("arnott_2019_defensive_quality", "ArnottDefensiveQuality"),
]


@pytest.mark.parametrize(("stem", "expected_cls"), _CASES)
def test_strategy_loads_and_runs(stem: str, expected_cls: str) -> None:
    from archimedes_analytics_engine.strategy_loader import load_strategy

    bundle = load_strategy(_STRATEGIES_DIR / f"{stem}.py")
    assert bundle.cls.__name__ == expected_cls

    frames = _trending_universe()
    result = run_multi_backtest(frames, strategy_cls=bundle.cls, initial_cash=100_000.0, names=_NAMES)
    assert isinstance(result, BacktestResult)
    assert result.look_ahead_audit_passed is True
    assert isinstance(result.daily_returns, list)
    assert len(result.daily_returns) > 0
    # Strategy must actually deploy capital — final value diverges from initial cash.
    assert result.final_value != pytest.approx(100_000.0, rel=1e-3)


@pytest.mark.parametrize(("stem", "expected_cls"), _CASES)
def test_strategy_metadata(stem: str, expected_cls: str) -> None:
    module = _load_module(stem)

    assert isinstance(module.PAPER_TITLE, str) and module.PAPER_TITLE.strip()
    assert isinstance(module.PAPER_AUTHORS, list) and len(module.PAPER_AUTHORS) >= 1
    assert all(isinstance(a, str) and a.strip() for a in module.PAPER_AUTHORS)
    assert isinstance(module.PAPER_YEAR, int) and module.PAPER_YEAR > 1900
    assert module.REGIME_TAG == "bear"
    assert isinstance(module.RISK_PROFILES, list) and len(module.RISK_PROFILES) >= 1
    assert module.STATUS == "candidate"
    assert isinstance(module.METHODOLOGY_TEXT, str) and len(module.METHODOLOGY_TEXT) > 100
    # The class the tests reference must exist on the module.
    assert hasattr(module, expected_cls)


@pytest.mark.parametrize(("stem", "expected_cls"), _CASES)
def test_insufficient_history_holds_flat(stem: str, expected_cls: str) -> None:
    from archimedes_analytics_engine.strategy_loader import load_strategy

    bundle = load_strategy(_STRATEGIES_DIR / f"{stem}.py")
    assert bundle.cls.__name__ == expected_cls

    # 30 bars is below every warmup window → strategy never deploys capital.
    frames = _trending_universe(n=30)
    result = run_multi_backtest(frames, strategy_cls=bundle.cls, initial_cash=100_000.0, names=_NAMES)
    assert isinstance(result, BacktestResult)
    assert result.final_value == pytest.approx(100_000.0, rel=1e-6)
