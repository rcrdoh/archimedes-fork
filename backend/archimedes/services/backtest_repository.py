"""Persistence helpers for backtest_results table."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from archimedes.models.backtest import BacktestResult
from archimedes.models.backtest_store import BacktestResultRecord


def insert_backtest_if_missing(
    session: Session,
    *,
    strategy_id: str,
    content_hash: str,
    result: BacktestResult,
    run_id: str | None = None,
    operation: str | None = None,
    artifact_json: str | None = None,
) -> tuple[BacktestResultRecord, bool]:
    """Insert row if strategy_id+content_hash missing. Returns (row, inserted)."""
    existing = (
        session.query(BacktestResultRecord)
        .filter(
            BacktestResultRecord.strategy_id == strategy_id,
            BacktestResultRecord.content_hash == content_hash,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing, False

    row = BacktestResultRecord.from_backtest_result(
        strategy_id=strategy_id,
        content_hash=content_hash,
        result=result,
        run_id=run_id,
        operation=operation,
        artifact_json=artifact_json,
    )
    session.add(row)
    session.flush()
    return row, True


def latest_backtests_by_strategy(
    session: Session,
    strategy_ids: Iterable[str],
) -> dict[str, BacktestResultRecord]:
    """Fetch latest row per strategy_id."""
    ids = [sid for sid in strategy_ids]
    if not ids:
        return {}

    rows = (
        session.query(BacktestResultRecord)
        .filter(BacktestResultRecord.strategy_id.in_(ids))
        .order_by(
            BacktestResultRecord.strategy_id.asc(),
            BacktestResultRecord.created_at.desc(),
            BacktestResultRecord.id.desc(),
        )
        .all()
    )

    latest: dict[str, BacktestResultRecord] = {}
    for row in rows:
        if row.strategy_id not in latest:
            latest[row.strategy_id] = row
    return latest
