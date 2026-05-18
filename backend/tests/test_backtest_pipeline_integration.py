"""Integration test: analytics-engine → DB → passport → risk end-to-end.

Verifies that the full backtest pipeline produces real (non-placeholder)
metrics including selection-bias rigor gate fields.
"""

from __future__ import annotations

from archimedes.db import get_session, init_db
from archimedes.models.backtest_store import BacktestResultRecord
from archimedes.services.strategy_provider import default_provider


def test_backtest_pipeline_e2e():
    """Exercise the full pipeline: strategies have persisted backtest results
    with rigor gate fields populated."""
    init_db()
    provider = default_provider()
    strategies = provider.list_strategies()

    assert len(strategies) >= 4, f"Expected >= 4 strategies, got {len(strategies)}"

    strategy_ids = [s.id for s in strategies]

    with get_session() as session:
        rows = (
            session.query(BacktestResultRecord)
            .filter(BacktestResultRecord.strategy_id.in_(strategy_ids))
            .all()
        )

    # Every strategy should have a persisted backtest row
    rows_by_id = {r.strategy_id: r for r in rows}
    for s in strategies:
        assert s.id in rows_by_id, f"No backtest row for {s.paper_title}"

    # Every row should have real metrics (not zero/None defaults)
    for s in strategies:
        row = rows_by_id[s.id]
        assert row.sharpe_ratio > 0, f"{s.paper_title}: Sharpe should be > 0, got {row.sharpe_ratio}"
        assert row.cagr > 0, f"{s.paper_title}: CAGR should be > 0"
        assert row.max_drawdown > 0, f"{s.paper_title}: MaxDD should be > 0"

    # At least some rows should have rigor gate fields populated
    with_rigor = [r for r in rows if r.deflated_sharpe_ratio is not None]
    assert len(with_rigor) >= 2, f"Expected >= 2 rows with DSR, got {len(with_rigor)}"

    # Verify DSR p-value is in valid range
    for r in with_rigor:
        assert 0 <= r.dsr_p_value <= 1, f"DSR p-value out of range: {r.dsr_p_value}"

    # Verify PBO score is in valid range
    with_pbo = [r for r in rows if r.pbo_score is not None]
    for r in with_pbo:
        assert 0 <= r.pbo_score <= 1, f"PBO score out of range: {r.pbo_score}"

    # Verify the provider returns real backtest results
    for s in strategies:
        bt = provider.get_backtest_result(s.id)
        assert bt is not None, f"No BacktestResult for {s.paper_title}"
        assert bt.sharpe_ratio > 0, f"BacktestResult Sharpe should be > 0"
        assert bt.deflated_sharpe_ratio is not None, f"DSR not populated for {s.paper_title}"
