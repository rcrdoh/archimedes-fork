"""CLI entry-point for the StockBench benchmark run.

Usage:
    python -m archimedes.scripts.stockbench_run --seeds 3 --horizon-days 90

Runs the ArchimedesStockBenchAgent (Phase 2 adapter) through the StockBench
harness (Chen et al. 2026, arXiv 2510.02209) for N seeds and emits a JSON
result file to docs/benchmarks/stockbench-results.json.

Phase 3 requirements (not yet met — see issue #218):
  - `pip install stockbench` (upstream harness package)
  - StockBench API key in STOCKBENCH_API_KEY env var (or harness runs offline
    against the bundled synthetic market fixture)

Until the harness package is available, this script runs in --dry-run mode:
it exercises the adapter's observe→decide→act→verify loop against a synthetic
market fixture so the adapter wiring can be validated without the harness.

Author: Önder Akkaya
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

_RESULTS_DIR = Path(__file__).parents[4] / "docs" / "benchmarks"
_RESULTS_FILE = _RESULTS_DIR / "stockbench-results.json"


# ── Synthetic fixture for --dry-run / Phase 2 validation ─────────────────────


def _synthetic_episode(horizon_days: int, seed: int) -> list[dict]:
    """Generate a synthetic market episode for adapter wiring validation.

    Returns `horizon_days` market state dicts with plausible but randomized
    prices, VIX, and post_state metrics. Not suitable for reporting benchmark
    numbers — used only to validate the adapter's four-step loop.
    """
    import random

    rng = random.Random(seed)
    episode = []
    price = 100.0
    vix = 18.0
    portfolio_value = 1.0
    peak = 1.0
    cumulative = 0.0

    for t in range(horizon_days):
        # Simulate daily price and VIX moves
        price *= 1.0 + rng.gauss(0.0003, 0.015)
        vix = max(10.0, vix + rng.gauss(0.0, 0.5))

        period_return = rng.gauss(0.0003, 0.015)
        portfolio_value *= 1.0 + period_return
        peak = max(peak, portfolio_value)
        cumulative = portfolio_value - 1.0
        drawdown = (portfolio_value - peak) / peak

        episode.append(
            {
                "t": t,
                "timestamp": datetime.now(UTC).isoformat(),
                "prices": {"sSPY": price, "sGLD": rng.uniform(160.0, 200.0)},
                "vix": vix,
                "sp500_ma50": price * rng.uniform(0.97, 1.03),
                "sp500_ma200": price * rng.uniform(0.94, 1.06),
                # post_state fields (harness would emit these)
                "period_return": period_return,
                "cumulative_return": cumulative,
                "max_drawdown": drawdown,
                "sortino_ratio": None,
                "z_score_composite": None,
                "period_start": None,
                "training_end": None,
            }
        )
    return episode


# ── Main run ──────────────────────────────────────────────────────────────────


def run_benchmark(
    seeds: int,
    horizon_days: int,
    risk_profile: str,
    dry_run: bool,
) -> dict:
    """Run the benchmark for `seeds` seeds and return the aggregate summary."""
    from archimedes.benchmarks.stockbench_adapter import ArchimedesStockBenchAgent

    seed_results = []

    for seed in range(seeds):
        logger.info("=== Seed %d / %d (horizon=%dd, profile=%s) ===", seed + 1, seeds, horizon_days, risk_profile)

        agent = ArchimedesStockBenchAgent(
            risk_profile=risk_profile,
            seed=seed,
            horizon_days=horizon_days,
        )

        if dry_run:
            episode = _synthetic_episode(horizon_days=horizon_days, seed=seed)
            harness_available = False
        else:
            try:
                import stockbench  # type: ignore[import]

                harness = stockbench.Harness(
                    horizon_days=horizon_days,
                    seed=seed,
                )
                episode = list(harness.episode())
                harness_available = True
            except ImportError:
                logger.warning("stockbench package not installed — falling back to dry-run fixture")
                episode = _synthetic_episode(horizon_days=horizon_days, seed=seed)
                harness_available = False

        for step_data in episode:
            obs = agent.observe(step_data)
            action_set = agent.decide(obs)
            allocation = agent.act(action_set)

            post_state = harness.step(allocation.allocations) if harness_available else step_data  # type: ignore[possibly-undefined]

            agent.verify(post_state)

        summary = agent.episode_summary()
        summary["harness_available"] = harness_available
        seed_results.append(summary)
        logger.info(
            "Seed %d done: cumret=%.2f%% mdd=%.2f%% sortino=%s",
            seed,
            summary.get("cumulative_return", 0) * 100,
            summary.get("max_drawdown", 0) * 100,
            f"{summary.get('sortino_ratio', 0):.2f}" if summary.get("sortino_ratio") else "n/a",
        )

    # Aggregate across seeds
    def _mean(key: str) -> float | None:
        vals = [r[key] for r in seed_results if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    def _std(key: str) -> float | None:
        import math

        vals = [r[key] for r in seed_results if r.get(key) is not None]
        if len(vals) < 2:
            return None
        m = sum(vals) / len(vals)
        return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))

    return {
        "run_metadata": {
            "seeds": seeds,
            "horizon_days": horizon_days,
            "risk_profile": risk_profile,
            "dry_run": dry_run,
            "generated_at": datetime.now(UTC).isoformat(),
            "paper_reference": "Chen et al. (2026) arXiv:2510.02209",
            "adapter_version": "Phase 2 stub",
            "note": (
                "dry-run results use a synthetic fixture and are NOT reportable. "
                "Phase 3 requires stockbench package + credentials."
            )
            if dry_run
            else "live harness results",
        },
        "aggregate": {
            "cumulative_return_mean": _mean("cumulative_return"),
            "cumulative_return_std": _std("cumulative_return"),
            "max_drawdown_mean": _mean("max_drawdown"),
            "sortino_ratio_mean": _mean("sortino_ratio"),
            "z_score_composite_mean": _mean("z_score_composite"),
            "dsr_p_value_mean": _mean("dsr_p_value"),
            "pbo_mean": _mean("pbo"),
        },
        "per_seed": seed_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Archimedes StockBench benchmark adapter.")
    parser.add_argument("--seeds", type=int, default=3, help="Number of random seeds (default: 3)")
    parser.add_argument("--horizon-days", type=int, default=90, help="Episode length in days (default: 90)")
    parser.add_argument(
        "--risk-profile",
        default="moderate",
        choices=["fixed_income", "conservative", "moderate", "aggressive", "hyper_risky"],
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Use synthetic fixture instead of live harness (Phase 2 validation only)"
    )
    parser.add_argument("--output", default=str(_RESULTS_FILE), help=f"Output JSON path (default: {_RESULTS_FILE})")
    args = parser.parse_args(argv)

    # Add backend to sys.path if running directly
    backend_src = Path(__file__).parents[2]
    if str(backend_src) not in sys.path:
        sys.path.insert(0, str(backend_src))

    results = run_benchmark(
        seeds=args.seeds,
        horizon_days=args.horizon_days,
        risk_profile=args.risk_profile,
        dry_run=args.dry_run,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    logger.info("Results written to %s", out_path)

    if results["run_metadata"]["dry_run"]:
        logger.warning("DRY-RUN: results are from synthetic fixture — not reportable")
        logger.warning("Phase 3 (real harness) requires: pip install stockbench + STOCKBENCH_API_KEY")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
