"""Compute the library-level PBO (Bailey et al. 2014 CSCV) from the daily-returns store.

Reads every record in ``strategies/daily_returns/`` (see
``gen_daily_returns_store.py``), date-aligns the return series (inner join on
ISO dates — the strategies trade different calendars: ^N225 vs SPY vs joined
pair windows), and runs the honest, full-library CSCV PBO that the fixture-era
cohort PBO could only approximate.

The headline number comes from ``archimedes_analytics_engine.pbo.compute_pbo``
— the same algorithm (parity-tested) as backend
``rigor_evaluator.compute_pbo``; this script never forks the formula. The
per-strategy table is a diagnostic layer on top: how often each strategy is
the in-sample best, and how it ranks out-of-sample when it is.

READ-ONLY with respect to fixtures: nothing here writes to
``backtest_fixtures.json``. The library PBO is a new, parallel diagnostic on
current-vintage data — NOT a backfill of the stored per-cohort ``pbo_score``
values (different data vintage, different selection set). Promoting it into
the served fixtures is a team decision.

Usage:
    cd analytics-engine
    uv run python scripts/compute_library_pbo.py
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

from archimedes_analytics_engine.pbo import _ascending_ranks, _sharpe_per_col, compute_pbo

STORE_DIR = ROOT / "strategies" / "daily_returns"


def load_store(store_dir: Path = STORE_DIR) -> list[dict]:
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(store_dir.glob("*.json"))]
    if not records:
        raise SystemExit(f"No store files in {store_dir} — run gen_daily_returns_store.py --write first")
    return records


def build_aligned_matrix(records: list[dict]) -> tuple[list[str], dict[str, list[float]]]:
    """Inner-join the dated series: keep only dates present in EVERY record.

    Returns (joint_dates_sorted, {stem: returns_on_joint_dates}). Alignment is
    what makes row i of the CSCV matrix mean the same trading day for every
    strategy — compute_pbo itself only truncates to the shortest length.
    """
    date_sets = [set(rec["dates"]) for rec in records]
    joint = sorted(set.intersection(*date_sets))
    if not joint:
        raise SystemExit("Empty date intersection across store records — cannot align")
    matrix: dict[str, list[float]] = {}
    for rec in records:
        by_date = dict(zip(rec["dates"], rec["daily_returns"], strict=True))
        matrix[rec["stem"]] = [by_date[d] for d in joint]
    return joint, matrix


def cscv_diagnostics(matrix: dict[str, list[float]], s_partitions: int = 16) -> dict:
    """Per-strategy CSCV diagnostics + an independently-recomputed PBO.

    Re-runs the same split loop as compute_pbo to report, per strategy: how
    many of the C(S, S/2) splits selected it as the in-sample best, and its
    median OOS rank-quantile (rank/N, 1.0 = OOS best) over those splits. The
    recomputed ``pbo`` is asserted equal to compute_pbo's output by the caller
    — a consistency check, not a second source of truth.
    """
    sorted_ids = sorted(matrix.keys())
    N = len(sorted_ids)
    T = min(len(v) for v in matrix.values())
    R = np.array([matrix[sid][:T] for sid in sorted_ids], dtype=float).T

    S = s_partitions
    rows_per_block = T // S
    blocks = [R[i * rows_per_block : (i + 1) * rows_per_block, :] for i in range(S)]
    half = S // 2

    is_best_counts = dict.fromkeys(sorted_ids, 0)
    oos_quantiles: dict[str, list[float]] = {sid: [] for sid in sorted_ids}
    lambdas: list[float] = []
    for is_indices in combinations(range(S), half):
        oos_indices = [i for i in range(S) if i not in is_indices]
        IS = np.vstack([blocks[i] for i in is_indices])
        OOS = np.vstack([blocks[i] for i in oos_indices])
        best_is_idx = int(np.argmax(_sharpe_per_col(IS)))
        oos_ranks = _ascending_ranks(_sharpe_per_col(OOS))
        omega = float(np.clip(oos_ranks[best_is_idx] / N, 1e-9, 1.0 - 1e-9))
        lambdas.append(math.log(omega / (1.0 - omega)))
        best_id = sorted_ids[best_is_idx]
        is_best_counts[best_id] += 1
        oos_quantiles[best_id].append(oos_ranks[best_is_idx] / N)

    full_sharpes = _sharpe_per_col(R)
    return {
        "n_splits": len(lambdas),
        "pbo": round(sum(1 for lam in lambdas if lam <= 0.0) / len(lambdas), 6),
        "per_strategy": {
            sid: {
                "joint_window_sharpe": round(float(full_sharpes[i]), 4),
                "is_best_count": is_best_counts[sid],
                "median_oos_rank_quantile": (
                    round(float(np.median(oos_quantiles[sid])), 4) if oos_quantiles[sid] else None
                ),
            }
            for i, sid in enumerate(sorted_ids)
        },
    }


def main() -> None:
    records = load_store()
    joint_dates, matrix = build_aligned_matrix(records)
    vintages = sorted({rec["data_vintage"] for rec in records})
    print(f"Store: {len(records)} strategies, data vintage(s) {vintages}")
    print(f"Joint window after date alignment: {joint_dates[0]} → {joint_dates[-1]} ({len(joint_dates)} trading days)")
    dropped = {rec["stem"]: rec["n_obs"] - len(joint_dates) for rec in records}
    worst = sorted(dropped.items(), key=lambda kv: -kv[1])[:3]
    print(f"Days dropped by alignment (top 3): {worst}")

    pbo_map = compute_pbo(matrix)
    library_pbo = next(iter(pbo_map.values()))
    assert all(v == library_pbo for v in pbo_map.values())

    diag = cscv_diagnostics(matrix)
    if diag["pbo"] != library_pbo:
        raise SystemExit(f"Diagnostics PBO {diag['pbo']} != compute_pbo {library_pbo} — split loops have diverged")

    print(f"\n## LIBRARY PBO (CSCV, S=16, {diag['n_splits']} splits, N={len(matrix)}): {library_pbo}")
    print("(PBO ≥ 0.5 ⇒ the in-sample-best strategy is expected to fall below the OOS median — library overfit)\n")

    print("| strategy | joint-window Sharpe | IS-best in splits | median OOS rank quantile when best |")
    print("|---|---|---|---|")
    rows = sorted(diag["per_strategy"].items(), key=lambda kv: -kv[1]["joint_window_sharpe"])
    for sid, d in rows:
        q = d["median_oos_rank_quantile"]
        print(
            f"| {sid} | {d['joint_window_sharpe']:+.3f} | {d['is_best_count']}/{diag['n_splits']} | {q if q is not None else '—'} |"
        )

    print("\n## Sensitivity to S (partition count)")
    print("| S | splits | PBO |")
    print("|---|---|---|")
    for s in (8, 12, 16):
        pbo_s = next(iter(compute_pbo(matrix, s_partitions=s).values()))
        print(f"| {s} | {math.comb(s, s // 2)} | {pbo_s} |")


if __name__ == "__main__":
    main()
