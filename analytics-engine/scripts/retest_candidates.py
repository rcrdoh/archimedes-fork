"""Third-wave item 4: re-test the library through the cost model + walk-forward.

Two diagnostics, both read-only (NO fixture is written — the add-only law
stands; this is a findings script whose output feeds
docs/specs/third-wave-retest.md):

Part A — cost/turnover diagnosis. Re-run every strategy in its fixture
configuration on current data and report the item-1 cost metrics: annualized
one-way turnover, annual cost drag, break-even cost (the per-side bps at which
the gross CAGR is fully consumed), and gross-vs-net Sharpe. This separates
"the alpha is absent" (gross Sharpe already bad) from "the alpha is
cost-bled" (gross fine, net bad — the Kalman hypothesis).

Part B — walk-forward parameter selection (item 3 harness) on the strategies
with natural, paper-plausible parameter grids. Parameters are chosen on a
4-year train window and evaluated on the following 1-year unseen window,
rolling. The stitched OOS Sharpe is the honest answer to "would the right
parameters have rescued it?" — with n_param_combos recorded per run.

Honesty notes:
- Fresh runs on CURRENT yfinance data; legacy fixture entries are known not to
  reproduce on current data (vintage drift), so Part A numbers are labeled as
  re-run diagnostics, never written back to the fixture file.
- Grids are small and paper-plausible (the values the papers themselves
  discuss), not a mining sweep; the walk-forward OOS discipline is what makes
  even this small search honest.
- capital_preservation_tbill is skipped (it models a T-bill yield, not a
  tradeable instrument run).

Usage:
    cd analytics-engine
    uv run python scripts/retest_candidates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "strategies"))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from archimedes_analytics_engine.data import fetch_ohlcv
from archimedes_analytics_engine.engine import run_backtest, run_multi_backtest, run_pairs_backtest
from archimedes_analytics_engine.strategy_loader import load_strategy
from archimedes_analytics_engine.walk_forward import walk_forward_select
from regen_fixtures import (
    BACKTEST_END,
    BACKTEST_START,
    INITIAL_CASH,
    NEW_MULTI_SPECS,
    NEW_PAIR_SPECS,
    NEW_SINGLE_SPECS,
)

_STRATEGIES_DIR = ROOT / "strategies"

# Legacy stems re-run for context (their fixtures predate the spec catalog).
# All legacy single-asset entries were SPY-based; capital_preservation_tbill
# (synthetic T-bill yield) and pipeline_buy_hold (baseline) are skipped.
LEGACY_SINGLE_SPECS: list[dict] = [
    {"stem": "faber_2007_sma200_timing", "symbol": "SPY", "tx_cost_bps": 10},
    {"stem": "george_hwang_2004_52w_high", "symbol": "SPY", "tx_cost_bps": 10},
    {"stem": "moreira_muir_2017_volatility_managed", "symbol": "SPY", "tx_cost_bps": 10},
    {"stem": "moskowitz_ooi_pedersen_2012_tsmom", "symbol": "SPY", "tx_cost_bps": 10},
]

# Part B grids — paper-plausible values only (see module docstring).
WALK_FORWARD_SPECS: list[dict] = [
    {
        "stem": "faber_2007_sma200_timing",
        "symbol": "SPY",
        "grid": {"sma_period": [126, 168, 210, 252]},  # 6/8/10/12-month timing windows (Faber 2007)
    },
    {
        "stem": "donchian_breakout",
        "symbol": "SPY",
        # Classic channel variants incl. the Turtle 20/10 and 55/20 systems.
        "grid": {"entry_period": [20, 55, 100], "exit_period": [10, 20, 50]},
    },
    {
        "stem": "connors_alvarez_2009_rsi2",
        "symbol": "SPY",
        "grid": {"rsi_entry": [5.0, 10.0, 15.0]},  # Connors-Alvarez tested entry thresholds
    },
    {
        "stem": "bollinger_2001_band_reversion",
        "symbol": "SPY",
        "grid": {"period": [10, 20, 50], "devfactor": [2.0, 2.5]},
    },
    {
        "stem": "brock_1992_dual_ma_crossover",
        "symbol": "SPY",
        # The fixed-length MA pairs Brock-Lakonishok-LeBaron actually test.
        "grid": {"fast_period": [1, 2, 5], "slow_period": [50, 150, 200]},
    },
]
# The one genuine near-miss (multi-asset): risk parity, blocked by num_trials
# (issue #537), not by parameters. Walk-forward confirms the OOS robustness.
WALK_FORWARD_MULTI_SPEC = {
    "stem": "maillard_2010_risk_parity",
    "symbols": ["SPY", "^N225", "GC=F", "TLT", "CL=F"],
    "grid": {"lookback": [42, 63, 126]},
}

TRAIN_BARS = 1008  # ~4 years
TEST_BARS = 252  # ~1 year

_prices_cache: dict[str, pd.DataFrame] = {}


def _prices(symbol: str) -> pd.DataFrame:
    if symbol not in _prices_cache:
        _prices_cache[symbol] = fetch_ohlcv(symbol, BACKTEST_START, BACKTEST_END)
    return _prices_cache[symbol]


def _fmt(value: float | None, spec: str = "+.2f") -> str:
    return format(value, spec) if value is not None else "n/a"


def part_a() -> None:
    print("\n## Part A — cost/turnover diagnosis (fresh runs, current data, 10 bps/side)\n")
    print("| strategy | net Sharpe | gross Sharpe | turnover x/yr | cost drag %/yr | break-even bps | trades |")
    print("|---|---|---|---|---|---|---|")

    rows: list[tuple] = []
    for spec in (*LEGACY_SINGLE_SPECS, *NEW_SINGLE_SPECS):
        bundle = load_strategy(_STRATEGIES_DIR / f"{spec['stem']}.py")
        result = run_backtest(
            _prices(spec["symbol"]),
            strategy_cls=bundle.cls,
            initial_cash=INITIAL_CASH,
            transaction_cost_bps=spec["tx_cost_bps"],
        )
        rows.append((spec["stem"], result))
    for spec in NEW_PAIR_SPECS:
        bundle = load_strategy(_STRATEGIES_DIR / f"{spec['stem']}.py")
        sym_a, sym_b = spec["pair"]
        result = run_pairs_backtest(
            _prices(sym_a),
            _prices(sym_b),
            strategy_cls=bundle.cls,
            initial_cash=INITIAL_CASH,
            name_a=sym_a,
            name_b=sym_b,
            transaction_cost_bps=spec["tx_cost_bps"],
        )
        rows.append((spec["stem"], result))
    for spec in NEW_MULTI_SPECS:
        bundle = load_strategy(_STRATEGIES_DIR / f"{spec['stem']}.py")
        result = run_multi_backtest(
            [_prices(s) for s in spec["symbols"]],
            strategy_cls=bundle.cls,
            initial_cash=INITIAL_CASH,
            names=spec["symbols"],
            transaction_cost_bps=spec["tx_cost_bps"],
        )
        rows.append((spec["stem"], result))

    for stem, r in rows:
        print(
            f"| {stem} | {_fmt(r.sharpe_ratio)} | {_fmt(r.gross_sharpe_ratio)} "
            f"| {_fmt(r.turnover_annualized, '.2f')} | {_fmt(r.cost_drag_annual_pct, '.2f')} "
            f"| {_fmt(r.break_even_cost_bps, '.1f')} | {r.total_trades} |"
        )


def part_b() -> None:
    print("\n## Part B — walk-forward parameter selection (train 1008 bars, test 252, OOS stitched)\n")
    print("| strategy | combos | folds | WF OOS Sharpe | default full-sample Sharpe | chosen params (mode) |")
    print("|---|---|---|---|---|---|")

    for spec in WALK_FORWARD_SPECS:
        bundle = load_strategy(_STRATEGIES_DIR / f"{spec['stem']}.py")
        prices = _prices(spec["symbol"])
        default = run_backtest(prices, strategy_cls=bundle.cls, initial_cash=INITIAL_CASH, transaction_cost_bps=10)
        wf = walk_forward_select(
            prices,
            strategy_cls=bundle.cls,
            param_grid=spec["grid"],
            initial_cash=INITIAL_CASH,
            train_bars=TRAIN_BARS,
            test_bars=TEST_BARS,
            transaction_cost_bps=10,
        )
        chosen = [tuple(sorted(f.chosen_params.items())) for f in wf.folds]
        mode = max(set(chosen), key=chosen.count)
        print(
            f"| {spec['stem']} | {wf.n_param_combos} | {len(wf.folds)} | {_fmt(wf.oos_sharpe)} "
            f"| {_fmt(default.sharpe_ratio)} | {dict(mode)} ({chosen.count(mode)}/{len(chosen)} folds) |"
        )

    spec = WALK_FORWARD_MULTI_SPEC
    bundle = load_strategy(_STRATEGIES_DIR / f"{spec['stem']}.py")
    frames = [_prices(s) for s in spec["symbols"]]
    default = run_multi_backtest(
        frames, strategy_cls=bundle.cls, initial_cash=INITIAL_CASH, names=spec["symbols"], transaction_cost_bps=10
    )
    wf = walk_forward_select(
        frames,
        strategy_cls=bundle.cls,
        param_grid=spec["grid"],
        initial_cash=INITIAL_CASH,
        train_bars=TRAIN_BARS,
        test_bars=TEST_BARS,
        names=spec["symbols"],
        transaction_cost_bps=10,
    )
    chosen = [tuple(sorted(f.chosen_params.items())) for f in wf.folds]
    mode = max(set(chosen), key=chosen.count)
    print(
        f"| {spec['stem']} | {wf.n_param_combos} | {len(wf.folds)} | {_fmt(wf.oos_sharpe)} "
        f"| {_fmt(default.sharpe_ratio)} | {dict(mode)} ({chosen.count(mode)}/{len(chosen)} folds) |"
    )


if __name__ == "__main__":
    print(f"Re-test window: {BACKTEST_START} -> {BACKTEST_END} (current yfinance data; read-only, no fixture writes)")
    part_a()
    part_b()
