"""Unit coverage for the VaultMonitor class methods.

Mocks `chain_executor` + `AgentStateStore` so no live network/Redis fires.
Targets the snapshot loop, the get_vault_health composition, and the
get_all_vault_status fanout.

Added 2026-05-24 as part of the #147 coverage-gate lift.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from archimedes.services.vault_monitor import VaultMonitor


def _vault_metrics(addr: str) -> dict:
    return {
        "total_aum_usdc": 1000.0,
        "share_price_usdc": 1.0,
        "tier": 1,
        "paused": False,
        "is_agent_assisted": True,
        "vault_address": addr,
    }


def _build_monitor(state_overrides: dict | None = None) -> VaultMonitor:
    """Build a VaultMonitor with an AsyncMock-stubbed state store."""
    state_overrides = state_overrides or {}
    mon = VaultMonitor.__new__(VaultMonitor)  # bypass __init__ → no Redis client
    state = MagicMock()
    state.save_vault_snapshot = AsyncMock()
    state.get_vault_snapshots = AsyncMock(return_value=state_overrides.get("snapshots", []))
    state.get_last_rebalance = AsyncMock(return_value=state_overrides.get("last_rebalance"))
    state.get_heartbeat = AsyncMock(return_value=state_overrides.get("heartbeat"))
    state.get_events = AsyncMock(return_value=state_overrides.get("events", []))
    state.close = AsyncMock()
    mon.state = state
    return mon


class TestSnapshotAllVaults:
    @pytest.mark.asyncio
    async def test_chain_failure_returns_empty(self) -> None:
        mon = _build_monitor()
        with patch("archimedes.services.vault_monitor.chain_executor") as ce:
            ce.get_all_vaults = AsyncMock(side_effect=RuntimeError("rpc"))
            snaps = await mon.snapshot_all_vaults()
        assert snaps == []

    @pytest.mark.asyncio
    async def test_happy_path_collects_per_vault(self) -> None:
        mon = _build_monitor()
        with patch("archimedes.services.vault_monitor.chain_executor") as ce:
            ce.get_all_vaults = AsyncMock(return_value=["0xA", "0xB"])
            ce.get_vault_metrics = AsyncMock(side_effect=lambda addr: _vault_metrics(addr))
            snaps = await mon.snapshot_all_vaults()
        assert len(snaps) == 2
        assert {s["vault_address"] for s in snaps} == {"0xA", "0xB"}
        # State store called once per successful snapshot
        assert mon.state.save_vault_snapshot.await_count == 2

    @pytest.mark.asyncio
    async def test_per_vault_failure_is_isolated(self) -> None:
        mon = _build_monitor()
        with patch("archimedes.services.vault_monitor.chain_executor") as ce:
            ce.get_all_vaults = AsyncMock(return_value=["0xA", "0xB"])

            def metrics(addr):
                if addr == "0xA":
                    raise RuntimeError("bad vault")
                return _vault_metrics(addr)

            ce.get_vault_metrics = AsyncMock(side_effect=metrics)
            snaps = await mon.snapshot_all_vaults()
        assert [s["vault_address"] for s in snaps] == ["0xB"]


class TestGetVaultHealth:
    @pytest.mark.asyncio
    async def test_no_snapshots_yields_zero_trend(self) -> None:
        mon = _build_monitor()
        health = await mon.get_vault_health("0xV")
        assert health["aum_trend_pct"] == 0.0
        assert health["snapshot_count"] == 0
        assert health["latest_snapshot"] is None

    @pytest.mark.asyncio
    async def test_aum_trend_computed_from_snapshots(self) -> None:
        snapshots = [{"aum_usdc": 1100.0}] + [{"aum_usdc": 1000.0}] * 12
        mon = _build_monitor({"snapshots": snapshots})
        health = await mon.get_vault_health("0xV")
        # (1100 - 1000)/1000 * 100 = 10.0%
        assert health["aum_trend_pct"] == 10.0
        assert health["snapshot_count"] == 13

    @pytest.mark.asyncio
    async def test_alive_heartbeat_marks_agent_alive(self) -> None:
        recent = datetime.now(UTC).isoformat()
        mon = _build_monitor({"heartbeat": recent})
        health = await mon.get_vault_health("0xV")
        assert health["agent_alive"] is True

    @pytest.mark.asyncio
    async def test_stale_heartbeat_marks_agent_dead(self) -> None:
        old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        mon = _build_monitor({"heartbeat": old})
        health = await mon.get_vault_health("0xV")
        assert health["agent_alive"] is False

    @pytest.mark.asyncio
    async def test_malformed_heartbeat_marks_agent_dead(self) -> None:
        mon = _build_monitor({"heartbeat": "not-iso"})
        health = await mon.get_vault_health("0xV")
        assert health["agent_alive"] is False

    @pytest.mark.asyncio
    async def test_last_rebalance_age_in_seconds(self) -> None:
        ts = datetime.now(UTC) - timedelta(minutes=5)
        mon = _build_monitor({"last_rebalance": ts})
        health = await mon.get_vault_health("0xV")
        assert health["rebalance_age_seconds"] is not None
        # ~300s with some slack for execution time
        assert 290 < health["rebalance_age_seconds"] < 360
        assert health["last_rebalance"]  # ISO string

    @pytest.mark.asyncio
    async def test_sharpe_drift_marked_unavailable(self) -> None:
        # Until per-strategy backtest sharpe is wired, drift is honest
        # about being unavailable rather than computing from a hard-coded baseline.
        mon = _build_monitor()
        health = await mon.get_vault_health("0xV")
        assert health["sharpe_drift"]["available"] is False

    @pytest.mark.asyncio
    async def test_events_filtered_to_vault(self) -> None:
        events = [
            {"type": "rebalance", "data": {"address": "0xV"}},  # match by address
            {"type": "rebalance", "data": {"address": "0xOTHER"}},  # filtered
            {"type": "regime_change", "data": {}},  # included by type
        ]
        mon = _build_monitor({"events": events})
        health = await mon.get_vault_health("0xV")
        # 0xV rebalance + regime_change → 2 events; other vault excluded
        kinds = [e["type"] for e in health["recent_events"]]
        assert "regime_change" in kinds
        assert any(e.get("data", {}).get("address") == "0xV" for e in health["recent_events"])


class TestGetAllVaultStatus:
    @pytest.mark.asyncio
    async def test_chain_failure_returns_empty(self) -> None:
        mon = _build_monitor()
        with patch("archimedes.services.vault_monitor.chain_executor") as ce:
            ce.get_all_vaults = AsyncMock(side_effect=RuntimeError())
            assert await mon.get_all_vault_status() == []

    @pytest.mark.asyncio
    async def test_per_vault_error_recorded_not_raised(self) -> None:
        mon = _build_monitor()
        with patch("archimedes.services.vault_monitor.chain_executor") as ce:
            ce.get_all_vaults = AsyncMock(return_value=["0xA", "0xB"])

            async def health(v):
                if v == "0xA":
                    raise RuntimeError("boom")
                return {"vault_address": v, "agent_alive": True}

            mon.get_vault_health = health
            results = await mon.get_all_vault_status()
        assert any(r.get("error") for r in results)
        assert any(r.get("vault_address") == "0xB" for r in results)
