"""Tests for the faithful-scale Gatev portfolio-of-pairs strategy.

Hermetic: synthetic N-feed data, no network. Loads the strategy file via the
real strategy_loader (proving the metadata block + single strategy class
resolve), unit-tests the SSD pair-selection helper, and runs the full
formation -> trading -> re-formation cycle through engine.run_multi_backtest.
The real performance metrics live in backtest_fixtures.json; these tests only
guard the plumbing and the trade path. Mirrors test_cross_sectional_strategies.py.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
from archimedes_analytics_engine.engine import BacktestResult, run_multi_backtest

_STRATEGIES_DIR = Path(__file__).parent.parent / "strategies"
sys.path.insert(0, str(_STRATEGIES_DIR))
sys.path.insert(0, str(_STRATEGIES_DIR.parent / "src"))

_STEM = "gatev_2006_portfolio_of_pairs"


def _load():
    from archimedes_analytics_engine.strategy_loader import load_strategy

    return load_strategy(_STRATEGIES_DIR / f"{_STEM}.py")


def _small_params_cls(base_cls):
    """Subclass the loaded strategy with test-sized windows (the engine grows a
    strategy_params passthrough in the walk-forward PR; until then, subclass)."""

    class _SmallGatev(base_cls):
        params = (("formation", 60), ("trading", 50), ("n_pairs", 2), ("entry_sigma", 2.0))

    return _SmallGatev


def _frame(closes: list[float], start: str = "2015-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "Open": closes,  # Open == Close so executions happen at known prices
            "High": [c * 1.005 for c in closes],
            "Low": [c * 0.995 for c in closes],
            "Close": closes,
            "Volume": [1_000] * len(closes),
        },
        index=idx,
    )


def _divergent_pair_universe(n: int = 200, formation: int = 60) -> list[pd.DataFrame]:
    """Four feeds: A and B co-move tightly through formation, then B diverges
    hard inside the trading window and converges back; C and D are unrelated
    trends. The (A, B) pair has by far the smallest formation SSD."""
    common = [100.0 + 0.02 * i + 2.0 * math.sin(i / 9.0) for i in range(n)]
    a = list(common)
    b = []
    for i, c in enumerate(common):
        wobble = 0.05 * math.sin(i / 5.0)  # tiny spread noise -> small but nonzero sigma
        bump = 0.0
        if formation + 10 <= i < formation + 40:  # diverge inside the first trading window
            bump = 8.0 * math.sin((i - formation - 10) * math.pi / 30.0)
        b.append(c * 0.8 + wobble + bump)
    c_feed = [80.0 + 0.15 * i + 4.0 * math.sin(i / 23.0 + 2.0) for i in range(n)]
    d_feed = [150.0 - 0.05 * i + 6.0 * math.sin(i / 17.0 + 4.0) for i in range(n)]
    return [_frame(a), _frame(b), _frame(c_feed), _frame(d_feed)]


# ── select_pairs_by_ssd unit behaviour ────────────────────────────────────────


def test_select_pairs_ranks_co_movers_first() -> None:
    from gatev_2006_portfolio_of_pairs import select_pairs_by_ssd

    base = [100.0 + math.sin(i / 4.0) for i in range(50)]
    closes = [
        base,  # asset 0
        [p * 0.5 + 0.01 * math.sin(i / 3.0) for i, p in enumerate(base)],  # 1: ~scaled twin of 0
        [50.0 + 2.0 * i for i in range(50)],  # 2: unrelated trend
        [200.0 - 1.5 * i for i in range(50)],  # 3: unrelated downtrend
    ]
    pairs = select_pairs_by_ssd(closes, n_pairs=2)
    assert len(pairs) == 2
    top_i, top_j, top_sigma = pairs[0]
    assert (top_i, top_j) == (0, 1)
    assert top_sigma > 0


def test_select_pairs_skips_degenerate_series() -> None:
    from gatev_2006_portfolio_of_pairs import select_pairs_by_ssd

    closes = [
        [100.0] * 30,  # flat
        [100.0] * 30,  # identical flat twin -> zero spread variance, untradeable
        [50.0 + i for i in range(30)],
    ]
    pairs = select_pairs_by_ssd(closes, n_pairs=3)
    # The (0, 1) pair has sigma == 0 and must be excluded.
    assert all((i, j) != (0, 1) for i, j, _ in pairs)


def test_select_pairs_caps_at_n_pairs() -> None:
    from gatev_2006_portfolio_of_pairs import select_pairs_by_ssd

    closes = [[100.0 + 0.1 * k * i + math.sin(i / 3.0 + k) for i in range(40)] for k in range(6)]
    assert len(select_pairs_by_ssd(closes, n_pairs=4)) == 4
    # More pairs requested than combinations exist -> return what's available.
    assert len(select_pairs_by_ssd(closes[:3], n_pairs=20)) <= 3


# ── Full strategy cycle through the engine ────────────────────────────────────


def test_loads_via_strategy_loader_with_metadata() -> None:
    bundle = _load()
    assert bundle.cls.__name__ == "GatevPortfolioOfPairs"
    assert bundle.metadata["paper_title"] == "Pairs Trading: Performance of a Relative-Value Arbitrage Rule"
    assert bundle.metadata["paper_claimed_sharpe"] is None
    assert bundle.metadata["paper_claimed_cagr"] == 0.11


def test_methodology_distinct_from_single_pair_gatev_files() -> None:
    # Same paper anchor as the four single-pair files -> the strategy ID only
    # stays unique if the methodology text genuinely differs (handover gotcha 1).
    bundle = _load()
    for other_stem in (
        "gatev_2006_pairs_distance",
        "gatev_2006_pairs_ko_pep",
        "gatev_2006_pairs_ewa_ewc",
        "gatev_2006_pairs_gld_slv",
    ):
        from archimedes_analytics_engine.strategy_loader import load_strategy

        other = load_strategy(_STRATEGIES_DIR / f"{other_stem}.py")
        assert bundle.metadata["methodology_text"] != other.metadata["methodology_text"]


def test_full_cycle_trades_the_planted_divergence() -> None:
    bundle = _load()
    frames = _divergent_pair_universe(n=200, formation=60)
    result = run_multi_backtest(
        frames,
        strategy_cls=_small_params_cls(bundle.cls),
        initial_cash=100_000.0,
        names=["A", "B", "C", "D"],
    )
    assert isinstance(result, BacktestResult)
    assert result.bars == 200
    assert result.look_ahead_audit_passed is True
    # The planted 2-sigma divergence inside the trading window must be traded.
    assert result.total_trades > 0
    assert result.traded_notional > 0
    assert result.turnover_annualized is not None and result.turnover_annualized > 0


def test_survives_multiple_reformation_cycles() -> None:
    bundle = _load()
    frames = _divergent_pair_universe(n=400, formation=60)
    result = run_multi_backtest(
        frames,
        strategy_cls=_small_params_cls(bundle.cls),
        initial_cash=100_000.0,
        names=["A", "B", "C", "D"],
    )
    # 400 bars at formation=60/trading=50 -> several re-formations; the cycle
    # must keep running and produce a finite, extractable result.
    assert isinstance(result, BacktestResult)
    assert result.final_value > 0
    assert math.isfinite(result.final_value)
