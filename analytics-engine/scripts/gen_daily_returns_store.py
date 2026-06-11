"""Generate the per-strategy daily-returns store (add-only, idempotent).

Writes one JSON file per strategy under ``strategies/daily_returns/`` carrying
the strategy's dated daily-return series from a fresh backtest run in its
fixture configuration. The store exists to unlock the *library-level* PBO
(Bailey et al. 2014 CSCV) — a metric that needs every strategy's return series
simultaneously, which the summary-only ``backtest_fixtures.json`` cannot
provide (see ``scripts/compute_library_pbo.py``).

PROVENANCE — fresh measurement, NOT a fixture backfill:
    The legacy strategies' fixture-era return series cannot be reproduced —
    current yfinance data has drifted (the reason fixtures are add-only; see
    ``regen_fixtures.py``). Every series written here is a fresh measurement on
    current data, stamped with ``data_vintage`` = the run date. Library PBO
    computed from this store is a new, parallel diagnostic and must never be
    written back into ``backtest_fixtures.json``.

SCOPE — add-only + idempotent, same law as the fixture file:
    A run only backtests stems whose store file does NOT already exist; a
    second run after a successful one is a no-op. Never overwrite a store
    file — if a series must be re-measured (new vintage), that is a team
    decision and a new, explicitly-versioned file, not an overwrite.

COVERAGE — 22 of the 23 fixture strategies:
    The catalog = regen_fixtures' NEW_* specs (17) + retest_candidates'
    LEGACY_SINGLE_SPECS (4, fresh-run on SPY like the retest did)
    + pipeline_buy_hold (SPY baseline). ``capital_preservation_tbill`` is
    excluded: its fixture models a synthetic T-bill yield, not a tradeable
    instrument run (same exclusion as retest_candidates.py).

Usage:
    cd analytics-engine
    uv run python scripts/gen_daily_returns_store.py          # dry-run (summary only)
    uv run python scripts/gen_daily_returns_store.py --write  # write missing files
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "strategies"))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from archimedes_analytics_engine.data import fetch_ohlcv
from archimedes_analytics_engine.engine import run_backtest, run_multi_backtest, run_pairs_backtest
from archimedes_analytics_engine.strategy_loader import load_strategy
from regen_fixtures import (
    BACKTEST_END,
    BACKTEST_START,
    INITIAL_CASH,
    NEW_MULTI_SPECS,
    NEW_PAIR_SPECS,
    NEW_SINGLE_SPECS,
)
from retest_candidates import LEGACY_SINGLE_SPECS

STORE_DIR = ROOT / "strategies" / "daily_returns"
_STRATEGIES_DIR = ROOT / "strategies"

# SPY buy-and-hold baseline — part of the library shelf, so part of the
# selection set the CSCV measures over.
_BASELINE_SINGLE_SPECS: list[dict] = [
    {"stem": "pipeline_buy_hold", "symbol": "SPY", "tx_cost_bps": 10},
]

SINGLE_SPECS: list[dict] = [*LEGACY_SINGLE_SPECS, *_BASELINE_SINGLE_SPECS, *NEW_SINGLE_SPECS]
PAIR_SPECS: list[dict] = list(NEW_PAIR_SPECS)
MULTI_SPECS: list[dict] = list(NEW_MULTI_SPECS)

_prices_cache: dict[str, pd.DataFrame] = {}


def _prices(symbol: str) -> pd.DataFrame:
    if symbol not in _prices_cache:
        _prices_cache[symbol] = fetch_ohlcv(symbol, BACKTEST_START, BACKTEST_END)
    return _prices_cache[symbol]


def store_path(stem: str, store_dir: Path = STORE_DIR) -> Path:
    return store_dir / f"{stem}.json"


def pending_specs(specs: list[dict], store_dir: Path = STORE_DIR) -> tuple[list[dict], list[str]]:
    """Split specs into (to-generate, skipped-stems). Add-only: existing files are never regenerated."""
    pending = [s for s in specs if not store_path(s["stem"], store_dir).exists()]
    skipped = [s["stem"] for s in specs if store_path(s["stem"], store_dir).exists()]
    return pending, skipped


def build_record(stem: str, result, *, run_config: dict, data_vintage: str) -> dict:
    if len(result.daily_return_dates) != len(result.daily_returns):
        raise SystemExit(f"{stem}: dates/returns length mismatch — refusing to write a misaligned record")
    return {
        "stem": stem,
        "run_config": run_config,
        "backtest_start": result.backtest_start,
        "backtest_end": result.backtest_end,
        "data_vintage": data_vintage,
        "n_obs": len(result.daily_returns),
        "sharpe_ratio_this_run": result.sharpe_ratio,
        "dates": result.daily_return_dates,
        "daily_returns": result.daily_returns,
    }


def _write_record(record: dict, store_dir: Path) -> Path:
    path = store_path(record["stem"], store_dir)
    if path.exists():  # final safety net — same shape as regen_fixtures' collision guard
        raise SystemExit(f"Refusing to overwrite existing store file: {path}")
    store_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def main(write: bool = False) -> None:
    vintage = date.today().isoformat()
    pend_single, skip_single = pending_specs(SINGLE_SPECS)
    pend_pair, skip_pair = pending_specs(PAIR_SPECS)
    pend_multi, skip_multi = pending_specs(MULTI_SPECS)
    skipped = [*skip_single, *skip_pair, *skip_multi]
    if skipped:
        print(f"Add-only: skipping {len(skipped)} stem(s) with existing store files: {sorted(skipped)}")
    if not pend_single and not pend_pair and not pend_multi:
        print("Nothing to generate — every catalog stem already has a store file.")
        return

    records: list[dict] = []
    for spec in pend_single:
        stem = spec["stem"]
        bundle = load_strategy(_STRATEGIES_DIR / f"{stem}.py")
        print(f"Backtesting {stem} on {spec['symbol']}…")
        result = run_backtest(
            _prices(spec["symbol"]),
            strategy_cls=bundle.cls,
            initial_cash=INITIAL_CASH,
            transaction_cost_bps=spec["tx_cost_bps"],
        )
        cfg = {"kind": "single", "symbols": [spec["symbol"]], "tx_cost_bps": spec["tx_cost_bps"]}
        records.append(build_record(stem, result, run_config=cfg, data_vintage=vintage))

    for spec in pend_pair:
        stem = spec["stem"]
        sym_a, sym_b = spec["pair"]
        bundle = load_strategy(_STRATEGIES_DIR / f"{stem}.py")
        print(f"Backtesting {stem} on {sym_a}/{sym_b}…")
        result = run_pairs_backtest(
            _prices(sym_a),
            _prices(sym_b),
            strategy_cls=bundle.cls,
            initial_cash=INITIAL_CASH,
            name_a=sym_a,
            name_b=sym_b,
            transaction_cost_bps=spec["tx_cost_bps"],
        )
        cfg = {"kind": "pair", "symbols": [sym_a, sym_b], "tx_cost_bps": spec["tx_cost_bps"]}
        records.append(build_record(stem, result, run_config=cfg, data_vintage=vintage))

    for spec in pend_multi:
        stem = spec["stem"]
        bundle = load_strategy(_STRATEGIES_DIR / f"{stem}.py")
        print(f"Backtesting {stem} on universe {spec['symbols']}…")
        result = run_multi_backtest(
            [_prices(s) for s in spec["symbols"]],
            strategy_cls=bundle.cls,
            initial_cash=INITIAL_CASH,
            names=spec["symbols"],
            transaction_cost_bps=spec["tx_cost_bps"],
        )
        cfg = {"kind": "multi", "symbols": list(spec["symbols"]), "tx_cost_bps": spec["tx_cost_bps"]}
        records.append(build_record(stem, result, run_config=cfg, data_vintage=vintage))

    print(f"\n── Store records ({vintage} vintage) ─────────────────────")
    for rec in records:
        sharpe = rec["sharpe_ratio_this_run"]
        sharpe_s = f"{sharpe:+.4f}" if sharpe is not None else "n/a"
        print(
            f"  {rec['stem']:46s} n_obs={rec['n_obs']:5d} "
            f"window={rec['backtest_start'][:10]}→{rec['backtest_end'][:10]} sharpe={sharpe_s}"
        )

    if write:
        for rec in records:
            path = _write_record(rec, STORE_DIR)
            print(f"✓ wrote {path.relative_to(ROOT)}")
        print(f"\n✓ Store now covers {len(list(STORE_DIR.glob('*.json')))} strategies (existing files untouched)")
    else:
        print("\n(dry-run — pass --write to write the missing store files; existing files are never modified)")


if __name__ == "__main__":
    main(write="--write" in sys.argv)
