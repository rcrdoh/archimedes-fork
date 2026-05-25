"""Migrate existing strategies to the unified strategy_passports table.

Reads from:
  1. Curated strategy files (via LocalStrategyProvider)
  2. Existing StrategyRecord rows (fusion/architect outputs)

Writes to:
  strategy_passports + passport_paper_refs tables

Idempotent: re-runs skip existing records (by ID match).

Usage:
    python -m archimedes.scripts.migrate_to_unified_passport_store [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def migrate(dry_run: bool = False) -> dict[str, int]:
    """Run the migration. Returns counts."""
    from archimedes.db import get_session, init_db
    from archimedes.models.strategy_passport_record import (
        StrategyPassportRecord,
    )
    from archimedes.services.passport_loader import ingest_passport
    from archimedes.services.strategy_provider import default_provider

    # Ensure tables exist
    init_db()

    provider = default_provider()
    curated = provider.list_strategies()
    logger.info("Found %d curated strategies from file provider", len(curated))

    # Also load StrategyRecord rows (fusion/architect)
    from archimedes.models.strategy_store import StrategyRecord

    counts = {"curated": 0, "fusion": 0, "architect": 0, "skipped": 0, "errors": 0}

    with get_session() as session:
        # 1. Ingest curated strategies
        for strategy in curated:
            if dry_run:
                existing = session.query(StrategyPassportRecord).filter_by(id=strategy.id).first()
                if existing:
                    counts["skipped"] += 1
                    logger.info("  [DRY RUN] would skip %s (exists)", strategy.id)
                else:
                    counts["curated"] += 1
                    logger.info("  [DRY RUN] would ingest curated %s: %s", strategy.id, strategy.paper_title)
                continue

            try:
                ingest_passport(session, strategy, generation_method="curated", force_update=True)
                counts["curated"] += 1
            except Exception as exc:
                logger.error("Failed to ingest curated %s: %s", strategy.id, exc)
                counts["errors"] += 1

        # 2. Ingest StrategyRecord rows (fusion/architect)
        try:
            store_records = session.query(StrategyRecord).all()
        except Exception:
            store_records = []
            logger.warning("No strategy_store table found — skipping fusion/architect migration")

        for record in store_records:
            method = record.generation_method or "fusion"
            if dry_run:
                counts[method if method in counts else "fusion"] += 1
                logger.info("  [DRY RUN] would ingest %s %s: %s", method, record.id, record.strategy_name)
                continue

            try:
                # Build a minimal StrategyPassport from the StrategyRecord
                from archimedes.models.paper_ref import PaperRef
                from archimedes.models.strategy import StrategyPassport, StrategyStatus

                source_papers = json.loads(record.source_papers) if record.source_papers else []
                papers = [
                    PaperRef(
                        arxiv_id=p.get("arxiv_id"),
                        title=p.get("title", ""),
                        authors=p.get("authors", []),
                    )
                    for p in source_papers
                ]

                rigor = json.loads(record.rigor_verdict) if record.rigor_verdict else {}

                passport = StrategyPassport(
                    id=record.id,
                    papers=papers,
                    methodology_summary=record.thesis or "",
                    asset_universe=json.loads(record.asset_universe) if record.asset_universe else [],
                    status=StrategyStatus(record.status) if record.status else StrategyStatus.CANDIDATE,
                    regime_tag="regime_neutral",
                    passes_rigor_gate=bool(rigor.get("passing", False)),
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )

                ingest_passport(session, passport, generation_method=method)
                counts[method if method in counts else "fusion"] += 1
            except Exception as exc:
                logger.error("Failed to ingest %s %s: %s", method, record.id, exc)
                counts["errors"] += 1

        if not dry_run:
            session.commit()

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m archimedes.scripts.migrate_to_unified_passport_store",
        description="Migrate strategies to unified strategy_passports table.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without writing")
    args = parser.parse_args()

    counts = migrate(dry_run=args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{prefix}Migration results:")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(f"  total: {sum(counts.values())}")

    return 0 if counts["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
