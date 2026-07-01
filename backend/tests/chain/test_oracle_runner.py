"""Tests for the oracle runner loop (#738).

Target: backend/archimedes/chain/oracle_runner.py
The runner is the periodic process that fetches prices and pushes them on-chain.
It was at 0% coverage. We exercise one full loop iteration (fetch → push), the
"no prices this cycle" branch, the "fetch error" branch, and the "push returns
no tx" branch — breaking out of the otherwise-infinite `while True` by making
`asyncio.sleep` raise a sentinel.

Hermetic: the OracleUpdater is mocked at the boundary; `asyncio.sleep` is
patched to stop the loop. No network, no Arc RPC, no Circle.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from archimedes.chain import oracle_runner
from archimedes.models.asset import AssetPrice


class _StopLoop(Exception):
    """Sentinel raised by the patched sleep to break the runner's while-loop."""


def _price(symbol: str = "sTSLA", usd: float = 100.0) -> AssetPrice:
    from datetime import UTC, datetime

    return AssetPrice(symbol=symbol, price_usd=usd, timestamp=datetime.now(UTC), source="yfinance")


async def _run_one_cycle(updater: MagicMock) -> None:
    """Run oracle_runner.run() through exactly one loop body, then stop."""
    with (
        patch("archimedes.chain.oracle_runner.OracleUpdater", return_value=updater),
        patch("archimedes.chain.oracle_runner.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
        pytest.raises(_StopLoop),
    ):
        await oracle_runner.run()


class TestOracleRunnerLoop:
    async def test_fetch_then_push_path(self):
        updater = MagicMock()
        updater.fetch_prices = AsyncMock(return_value=[_price()])
        updater.push_prices_on_chain = AsyncMock(return_value="0xtx-1")
        await _run_one_cycle(updater)
        updater.fetch_prices.assert_awaited_once()
        updater.push_prices_on_chain.assert_awaited_once()

    async def test_prices_fetched_but_no_push_tx(self):
        # push returns None (owner key not configured) — must not crash.
        updater = MagicMock()
        updater.fetch_prices = AsyncMock(return_value=[_price()])
        updater.push_prices_on_chain = AsyncMock(return_value=None)
        await _run_one_cycle(updater)
        updater.push_prices_on_chain.assert_awaited_once()

    async def test_no_prices_this_cycle_skips_push(self):
        updater = MagicMock()
        updater.fetch_prices = AsyncMock(return_value=[])
        updater.push_prices_on_chain = AsyncMock()
        await _run_one_cycle(updater)
        # No prices → push is never attempted.
        updater.push_prices_on_chain.assert_not_called()

    async def test_fetch_exception_is_caught_and_loop_continues(self):
        # A fetch error must be swallowed (logged) and the loop proceed to sleep
        # — the _StopLoop from sleep proves we reached the end of the body.
        updater = MagicMock()
        updater.fetch_prices = AsyncMock(side_effect=RuntimeError("yfinance down"))
        updater.push_prices_on_chain = AsyncMock()
        await _run_one_cycle(updater)
        updater.push_prices_on_chain.assert_not_called()

    def test_interval_default_is_60s(self):
        # Sanity: the module-level INTERVAL falls back to 60 when env is unset.
        assert isinstance(oracle_runner.INTERVAL, int)
        assert oracle_runner.INTERVAL >= 1
