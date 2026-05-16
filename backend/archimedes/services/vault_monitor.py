"""Vault monitoring service — tracks metrics over time.

Provides:
- Periodic snapshot collection (called from agent_runner tick)
- Vault health assessment (AUM trends, rebalance staleness, oracle freshness)
- API helpers for the monitoring dashboard and SSE stream
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from archimedes.chain.executor import chain_executor
from archimedes.services.redis_state import AgentStateStore

logger = logging.getLogger(__name__)


class VaultMonitor:
    """Collects and serves vault monitoring data."""

    def __init__(self) -> None:
        self.state = AgentStateStore()

    async def snapshot_all_vaults(self) -> list[dict]:
        """Snapshot metrics for every vault. Called once per agent tick."""
        snapshots: list[dict] = []
        try:
            vaults = await chain_executor.get_all_vaults()
        except Exception as e:
            logger.warning("Cannot fetch vaults for monitoring: %s", e)
            return snapshots

        for vault_addr in vaults:
            try:
                metrics = await chain_executor.get_vault_metrics(vault_addr)
                snapshot = {
                    "vault_address": vault_addr,
                    "aum_usdc": metrics["total_aum_usdc"],
                    "share_price": metrics["share_price_usdc"],
                    "tier": metrics["tier"],
                    "paused": metrics["paused"],
                    "is_agent_assisted": metrics["is_agent_assisted"],
                }
                await self.state.save_vault_snapshot(vault_addr, snapshot)
                snapshots.append(snapshot)
            except Exception as e:
                logger.debug("Snapshot failed for %s: %s", vault_addr[:10], e)

        return snapshots

    async def get_vault_health(self, vault_address: str) -> dict:
        """Compute health indicators for a single vault."""
        snapshots = await self.state.get_vault_snapshots(vault_address, count=50)
        last_rebalance = await self.state.get_last_rebalance(vault_address)
        heartbeat = await self.state.get_heartbeat()
        events = await self.state.get_events(count=10)

        # AUM trend (latest vs 1h ago — ~12 snapshots at 5min interval)
        aum_trend = 0.0
        if len(snapshots) >= 2:
            latest_aum = snapshots[0].get("aum_usdc", 0)
            old_aum = snapshots[min(11, len(snapshots) - 1)].get("aum_usdc", 0)
            if old_aum > 0:
                aum_trend = ((latest_aum - old_aum) / old_aum) * 100

        # Rebalance staleness
        rebalance_age_seconds = None
        if last_rebalance:
            rebalance_age_seconds = (
                datetime.now(timezone.utc) - last_rebalance
            ).total_seconds()

        # Agent alive?
        agent_alive = False
        if heartbeat:
            try:
                hb_time = datetime.fromisoformat(heartbeat)
                age = (datetime.now(timezone.utc) - hb_time).total_seconds()
                agent_alive = age < 600  # alive if heartbeat < 10min old
            except Exception:
                pass

        return {
            "vault_address": vault_address,
            "agent_alive": agent_alive,
            "last_heartbeat": heartbeat,
            "last_rebalance": last_rebalance.isoformat() if last_rebalance else None,
            "rebalance_age_seconds": rebalance_age_seconds,
            "aum_trend_pct": round(aum_trend, 4),
            "snapshot_count": len(snapshots),
            "latest_snapshot": snapshots[0] if snapshots else None,
            "recent_events": [
                e for e in events
                if e.get("data", {}).get("address", "").lower() == vault_address.lower()
                or e.get("type") in ("regime_change", "agent_error")
            ][:5],
        }

    async def get_all_vault_status(self) -> list[dict]:
        """Health summary across all vaults — for the monitoring dashboard."""
        try:
            vaults = await chain_executor.get_all_vaults()
        except Exception:
            return []

        results = []
        for v in vaults:
            try:
                health = await self.get_vault_health(v)
                results.append(health)
            except Exception:
                results.append({"vault_address": v, "error": True})
        return results

    async def close(self) -> None:
        await self.state.close()


# Module-level singleton
vault_monitor = VaultMonitor()
