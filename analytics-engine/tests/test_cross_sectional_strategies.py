"""Tests for the Phase 2 cross-sectional / portfolio strategies.

Hermetic: synthetic N-feed data, no network. Each strategy file is loaded via
the real strategy_loader (proving its metadata block + single strategy class
resolve) and run through engine.run_multi_backtest with named feeds. The real
performance metrics live in backtest_fixtures.json; these tests only guard the
plumbing and the trade path.
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

# Feed names mirror the production universe so name-dependent logic (e.g.
# DualMomentum's "TLT" defensive leg) is actually exercised.
_NAMES = ["SPY", "^N225", "GC=F", "TLT", "CL=F"]


def _trending_universe(n: int = 400) -> list[pd.DataFrame]:
    """Five synthetic feeds with distinct drifts/phases so ranks and vols differ."""
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


@pytest.mark.parametrize(
    ("stem", "expected_cls"),
    [
        ("jegadeesh_titman_1993_cross_sectional_momentum", "CrossSectionalMomentum"),
        ("antonacci_2014_dual_momentum", "DualMomentum"),
        ("maillard_2010_risk_parity", "RiskParityInverseVol"),
    ],
)
def test_phase2_strategy_loads_and_runs(stem: str, expected_cls: str) -> None:
    from archimedes_analytics_engine.strategy_loader import load_strategy

    bundle = load_strategy(_STRATEGIES_DIR / f"{stem}.py")
    assert bundle.cls.__name__ == expected_cls

    frames = _trending_universe()
    result = run_multi_backtest(frames, strategy_cls=bundle.cls, initial_cash=100_000.0, names=_NAMES)
    assert isinstance(result, BacktestResult)
    assert result.bars == 400
    assert result.look_ahead_audit_passed is True
    assert isinstance(result.daily_returns, list)
    assert len(result.daily_returns) > 0
    # Every Phase 2 strategy must actually deploy capital (open positions) — i.e.
    # final value diverges from the untouched initial cash.
    assert result.final_value != pytest.approx(100_000.0)
