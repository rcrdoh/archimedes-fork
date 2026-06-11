"""Generate backtest_fixtures.json entries for the NEW strategies (add-only).

Fetches real market data via yfinance, runs each new strategy's backtest
(single-asset via ``run_backtest``; pairs via ``run_pairs_backtest``), then
computes the full rigor-metric suite — DSR, OOS Sharpe, Kelly, and a
cohort-level PBO — and writes the entries.

SCOPE — add-only (decided 2026-06-11):
    This script touches ONLY the new strategies listed in ``NEW_SPECS``. The
    six legacy fixture entries are left byte-for-byte untouched, because
    re-backtesting them on current data does not reproduce their stored
    metrics (data-vintage drift; and capital_preservation_tbill models a
    T-bill yield, not a TLT buy-hold). Overwriting live published metrics with
    drifted numbers would be a silent, hard-to-reverse regression.

PBO caveat:
    PBO (Bailey et al. 2014 CSCV) is a library-level metric requiring every
    strategy's daily-return series simultaneously. Since we cannot faithfully
    reproduce the legacy return series, PBO here is computed over the NEW
    cohort only and is reported as such. It is a cohort-overfit signal, not the
    full-library value. ``num_trials_in_selection`` IS set to the full library
    size (legacy + new) so the DSR multiple-testing penalty is conservative.

DSR math (compute_dsr / compute_oos_sharpe / compute_kelly) is imported from
``regen_buy_hold_fixture`` so there is a single source for the rigor formulas
(Önder's lane). PBO is ported here from backend ``rigor_evaluator.compute_pbo``.

Usage:
    cd analytics-engine
    uv run python scripts/regen_fixtures.py          # dry-run (print only)
    uv run python scripts/regen_fixtures.py --write   # write new entries
"""

from __future__ import annotations

import json
import math
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "strategies"))
sys.path.insert(0, str(Path(__file__).parent))  # for importing regen_buy_hold_fixture

from archimedes_analytics_engine.data import fetch_ohlcv
from archimedes_analytics_engine.engine import run_backtest, run_pairs_backtest
from archimedes_analytics_engine.strategy_loader import load_strategy

# Single source of truth for the DSR / OOS / Kelly formulas (Önder's lane).
from regen_buy_hold_fixture import compute_dsr, compute_kelly, compute_oos_sharpe

# ── Config ────────────────────────────────────────────────────────────────────
BACKTEST_START = "2004-01-02"
BACKTEST_END = "2026-05-01"  # yfinance end is exclusive; includes bars through 2026-04-30
INITIAL_CASH = 100_000.0
_ANN = 252
_RF_DAILY = 0.05 / _ANN
_FIXTURE_PATH = ROOT / "strategies" / "backtest_fixtures.json"
_STRATEGIES_DIR = ROOT / "strategies"

# Representative backtest instrument(s) per new strategy. Single-asset strategies
# use SPY for comparability with the legacy SPY-based entries; the pairs strategy
# uses its GLD/GDX demo pair.
NEW_SINGLE_SPECS: list[dict] = [
    {"stem": "connors_alvarez_2009_rsi2", "symbol": "SPY", "tx_cost_bps": 10},
    {"stem": "bollinger_2001_band_reversion", "symbol": "SPY", "tx_cost_bps": 10},
    {"stem": "donchian_breakout", "symbol": "SPY", "tx_cost_bps": 10},
    {"stem": "appel_1979_macd", "symbol": "SPY", "tx_cost_bps": 10},
    {"stem": "brock_1992_dual_ma_crossover", "symbol": "SPY", "tx_cost_bps": 10},
    {"stem": "ariel_1987_turn_of_month", "symbol": "SPY", "tx_cost_bps": 10},
]
NEW_PAIR_SPECS: list[dict] = [
    {"stem": "gatev_2006_pairs_distance", "pair": ("GLD", "GDX"), "tx_cost_bps": 10},
]


# ── PBO (CSCV) — ported from backend rigor_evaluator.compute_pbo ───────────────


def _sharpe_per_col(R: np.ndarray) -> np.ndarray:
    if R.shape[0] < 2:
        return np.zeros(R.shape[1])
    mu = R.mean(axis=0)
    sigma = R.std(axis=0, ddof=1)
    safe_sigma = np.where(sigma > 0, sigma, np.inf)
    return ((mu - _RF_DAILY) / safe_sigma) * math.sqrt(_ANN)


def _ascending_ranks(values: np.ndarray) -> np.ndarray:
    n = len(values)
    order = np.argsort(values)
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)
    return ranks


def compute_pbo(returns_matrix: dict[str, list[float]], s_partitions: int = 16) -> dict[str, float]:
    """Probability of Backtest Overfitting via CSCV (Bailey et al. 2014).

    Mirrors backend rigor_evaluator.compute_pbo. Returns {id: pbo} with the same
    value attached to every member of the cohort.
    """
    if len(returns_matrix) < 2:
        return dict.fromkeys(returns_matrix, 0.0)

    sorted_ids = sorted(returns_matrix.keys())
    N = len(sorted_ids)
    T = min(len(v) for v in returns_matrix.values())
    R = np.array([returns_matrix[sid][:T] for sid in sorted_ids], dtype=float).T  # (T, N)

    S = s_partitions if (s_partitions % 2 == 0 and s_partitions >= 2) else 16
    rows_per_block = T // S
    if rows_per_block < 1:
        return dict.fromkeys(sorted_ids, 0.0)

    blocks = [R[i * rows_per_block : (i + 1) * rows_per_block, :] for i in range(S)]
    half = S // 2
    lambdas: list[float] = []
    for is_indices in combinations(range(S), half):
        oos_indices = [i for i in range(S) if i not in is_indices]
        IS = np.vstack([blocks[i] for i in is_indices])
        OOS = np.vstack([blocks[i] for i in oos_indices])
        best_is_idx = int(np.argmax(_sharpe_per_col(IS)))
        oos_ranks = _ascending_ranks(_sharpe_per_col(OOS))
        omega = float(np.clip(oos_ranks[best_is_idx] / N, 1e-9, 1.0 - 1e-9))
        lambdas.append(math.log(omega / (1.0 - omega)))

    if not lambdas:
        return dict.fromkeys(sorted_ids, 0.0)
    pbo = round(sum(1 for lam in lambdas if lam <= 0.0) / len(lambdas), 6)
    return dict.fromkeys(sorted_ids, pbo)


# ── Rigor gate (full criteria incl. paper-claim check) ─────────────────────────


def _compute_passes_rigor_gate(
    *,
    passes_validation: bool,
    dsr: float | None,
    dsr_p: float | None,
    num_trials: int | None,
    full_sharpe: float | None,
    oos_sharpe: float | None,
    pbo_score: float | None,
    look_ahead_passed: bool | None,
    sharpe_vs_paper: float | None,
) -> bool:
    """Mirror BacktestResult.passes_rigor_gate criteria 1-7."""
    if not passes_validation:
        return False
    if dsr is None or dsr_p is None or num_trials is None:
        return False
    if dsr_p < 0.95:
        return False
    if pbo_score is None or pbo_score >= 0.5:
        return False
    if look_ahead_passed is not True:
        return False
    if oos_sharpe is None:
        return False
    if full_sharpe is not None and full_sharpe > 0 and oos_sharpe / full_sharpe < 0.5:
        return False
    # Criterion 7: paper-claim delta (only when a paper Sharpe is declared).
    return not (sharpe_vs_paper is not None and sharpe_vs_paper < 0.5)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _correlation_to(daily_returns: list[float], benchmark_returns: list[float]) -> float | None:
    n = min(len(daily_returns), len(benchmark_returns))
    if n < 3:
        return None
    a = np.asarray(daily_returns[-n:], dtype=float)
    b = np.asarray(benchmark_returns[-n:], dtype=float)
    if float(np.ptp(a)) == 0.0 or float(np.ptp(b)) == 0.0:
        return None
    return round(float(np.corrcoef(a, b)[0, 1]), 6)


def _passes_validation(result) -> bool:
    return (
        result.sharpe_ratio is not None
        and result.sharpe_ratio > 0.5
        and result.max_drawdown_pct is not None
        and (result.max_drawdown_pct / 100.0) < 0.5
        and result.cagr is not None
        and result.cagr < 10.0
        and (result.total_trades < 2 or result.total_trades >= 10)
    )


def _build_entry(result, *, metadata: dict, num_trials: int, corr_spy: float | None, tx_cost_bps: int) -> dict:
    daily = result.daily_returns
    dsr, dsr_p = compute_dsr(daily, num_trials)
    oos = compute_oos_sharpe(daily)
    kelly = compute_kelly(daily)

    max_dd_frac = (result.max_drawdown_pct / 100.0) if result.max_drawdown_pct is not None else None
    calmar = None
    if result.cagr is not None and max_dd_frac and max_dd_frac > 0:
        calmar = round(result.cagr / max_dd_frac, 7)

    # strategy_loader lowercases module-constant keys (PAPER_CLAIMED_SHARPE -> paper_claimed_sharpe).
    paper_sharpe = metadata.get("paper_claimed_sharpe")
    sharpe_vs_paper = None
    if paper_sharpe and result.sharpe_ratio is not None and paper_sharpe != 0:
        sharpe_vs_paper = result.sharpe_ratio / paper_sharpe

    return {
        "n_obs_daily": len(daily),
        "sharpe_ratio": round(result.sharpe_ratio, 10) if result.sharpe_ratio is not None else None,
        "sortino_ratio": round(result.sortino_ratio, 10) if result.sortino_ratio is not None else None,
        "max_drawdown": round(max_dd_frac, 16) if max_dd_frac is not None else None,
        "cagr": round(result.cagr, 16) if result.cagr is not None else None,
        "calmar_ratio": calmar,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "total_trades": result.total_trades,
        "avg_holding_period_days": result.avg_holding_period_days,
        "correlation_to_spy": corr_spy,
        "correlation_to_btc": None,
        "out_of_sample_sharpe": oos,
        "look_ahead_audit_passed": result.look_ahead_audit_passed,
        "backtest_engine": "backtrader",
        "transaction_cost_bps": tx_cost_bps,
        "backtest_start": result.backtest_start,
        "backtest_end": result.backtest_end,
        "paper_claimed_sharpe": metadata.get("paper_claimed_sharpe"),
        "paper_claimed_cagr": metadata.get("paper_claimed_cagr"),
        "paper_claimed_max_dd": metadata.get("paper_claimed_max_dd"),
        "deflated_sharpe_ratio": dsr,
        "dsr_p_value": dsr_p,
        "num_trials_in_selection": num_trials,
        "pbo_score": None,  # filled in after cohort PBO is computed
        "passes_rigor_gate": _compute_passes_rigor_gate(
            passes_validation=_passes_validation(result),
            dsr=dsr,
            dsr_p=dsr_p,
            num_trials=num_trials,
            full_sharpe=result.sharpe_ratio,
            oos_sharpe=oos,
            pbo_score=None,  # provisional; re-evaluated after PBO below
            look_ahead_passed=result.look_ahead_audit_passed,
            sharpe_vs_paper=sharpe_vs_paper,
        ),
        "kelly_fraction": kelly,
    }


# ── Main ──────────────────────────────────────────────────────────────────────


def main(write: bool = False) -> None:
    fixtures = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    num_trials = len(fixtures) + len(NEW_SINGLE_SPECS) + len(NEW_PAIR_SPECS)
    print(f"Library size after add: {num_trials} strategies (num_trials_in_selection)")

    print(f"Fetching SPY benchmark {BACKTEST_START} → {BACKTEST_END}…")
    spy = fetch_ohlcv("SPY", BACKTEST_START, BACKTEST_END)
    spy_returns = [(float(spy["Close"].iloc[i]) / float(spy["Close"].iloc[i - 1])) - 1.0 for i in range(1, len(spy))]

    new_entries: dict[str, dict] = {}
    cohort_returns: dict[str, list[float]] = {}

    for spec in NEW_SINGLE_SPECS:
        stem = spec["stem"]
        bundle = load_strategy(_STRATEGIES_DIR / f"{stem}.py")
        print(f"Backtesting {stem} on {spec['symbol']}…")
        prices = fetch_ohlcv(spec["symbol"], BACKTEST_START, BACKTEST_END)
        result = run_backtest(
            prices, strategy_cls=bundle.cls, initial_cash=INITIAL_CASH, transaction_cost_bps=spec["tx_cost_bps"]
        )
        corr = _correlation_to(result.daily_returns, spy_returns)
        new_entries[stem] = _build_entry(
            result, metadata=bundle.metadata, num_trials=num_trials, corr_spy=corr, tx_cost_bps=spec["tx_cost_bps"]
        )
        cohort_returns[stem] = result.daily_returns
        print(
            f"  sharpe={result.sharpe_ratio:+.4f} cagr={result.cagr:+.4f} dd={result.max_drawdown_pct:.1f}% trades={result.total_trades} corr_spy={corr}"
        )

    for spec in NEW_PAIR_SPECS:
        stem = spec["stem"]
        sym_a, sym_b = spec["pair"]
        bundle = load_strategy(_STRATEGIES_DIR / f"{stem}.py")
        print(f"Backtesting {stem} on {sym_a}/{sym_b}…")
        pa = fetch_ohlcv(sym_a, BACKTEST_START, BACKTEST_END)
        pb = fetch_ohlcv(sym_b, BACKTEST_START, BACKTEST_END)
        result = run_pairs_backtest(
            pa,
            pb,
            strategy_cls=bundle.cls,
            initial_cash=INITIAL_CASH,
            name_a=sym_a,
            name_b=sym_b,
            transaction_cost_bps=spec["tx_cost_bps"],
        )
        corr = _correlation_to(result.daily_returns, spy_returns)
        new_entries[stem] = _build_entry(
            result, metadata=bundle.metadata, num_trials=num_trials, corr_spy=corr, tx_cost_bps=spec["tx_cost_bps"]
        )
        cohort_returns[stem] = result.daily_returns
        print(
            f"  sharpe={result.sharpe_ratio:+.4f} cagr={result.cagr:+.4f} dd={result.max_drawdown_pct:.1f}% trades={result.total_trades} corr_spy={corr}"
        )

    # Cohort-level PBO across the new strategies, then re-evaluate the gate with it.
    print("\nComputing cohort PBO across new strategies (CSCV)…")
    pbo_by_stem = compute_pbo(cohort_returns)
    cohort_pbo = next(iter(pbo_by_stem.values())) if pbo_by_stem else None
    print(f"  cohort PBO = {cohort_pbo}  (NOTE: new-cohort only, not full-library; see module docstring)")

    for stem, entry in new_entries.items():
        entry["pbo_score"] = pbo_by_stem.get(stem)
        paper_sharpe = entry["paper_claimed_sharpe"]
        sharpe_vs_paper = (
            entry["sharpe_ratio"] / paper_sharpe
            if (paper_sharpe and entry["sharpe_ratio"] is not None and paper_sharpe != 0)
            else None
        )
        entry["passes_rigor_gate"] = _compute_passes_rigor_gate(
            passes_validation=(
                entry["sharpe_ratio"] is not None
                and entry["sharpe_ratio"] > 0.5
                and entry["max_drawdown"] is not None
                and entry["max_drawdown"] < 0.5
                and entry["cagr"] is not None
                and entry["cagr"] < 10.0
                and (entry["total_trades"] < 2 or entry["total_trades"] >= 10)
            ),
            dsr=entry["deflated_sharpe_ratio"],
            dsr_p=entry["dsr_p_value"],
            num_trials=entry["num_trials_in_selection"],
            full_sharpe=entry["sharpe_ratio"],
            oos_sharpe=entry["out_of_sample_sharpe"],
            pbo_score=entry["pbo_score"],
            look_ahead_passed=entry["look_ahead_audit_passed"],
            sharpe_vs_paper=sharpe_vs_paper,
        )

    print("\n── New fixture entries ────────────────────────────────")
    print(json.dumps(new_entries, indent=2))
    print("\n── Rigor-gate summary ─────────────────────────────────")
    for stem, entry in new_entries.items():
        print(
            f"  {stem:34s} sharpe={entry['sharpe_ratio']:+.3f} "
            f"DSR_p={entry['dsr_p_value']} PBO={entry['pbo_score']} "
            f"passes_gate={entry['passes_rigor_gate']}"
        )

    # Sanity: refuse to overwrite an existing entry.
    collisions = set(new_entries) & set(fixtures)
    if collisions:
        raise SystemExit(f"Refusing to overwrite existing fixture entries: {sorted(collisions)}")

    if write:
        fixtures.update(new_entries)
        _FIXTURE_PATH.write_text(json.dumps(fixtures, indent=2) + "\n", encoding="utf-8")
        print(f"\n✓ Added {len(new_entries)} entries to {_FIXTURE_PATH} (legacy entries untouched)")
    else:
        print("\n(dry-run — pass --write to add these entries; legacy entries are never modified)")


if __name__ == "__main__":
    main(write="--write" in sys.argv)
