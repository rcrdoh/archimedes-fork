"""Type 3 Agent — Replicator (copy-trade subscriber agent).

Reuses the Type 2 Agent's bootstrap and vault-availability gating pattern
(Style 2 from agent_runner.py: CLI entrypoint, asyncio loop, vault discovery,
vault<>strategy mapping lookup, threshold gating).

Replaces the Type 2 operational loop (evaluate signals → rebalance → execute)
with: subscribe to publisher endpoint → check vault → follow/replicate actions
→ track consumption for billing/metering.

Run as a standalone process:
    python -m archimedes.chain.agent_replicator

Env:
    AGENT_INTERVAL_SECONDS  — tick interval in seconds (default: 300 = 5 min)
    AGENT_VAULT_ADDRESSES   — comma-separated vault addresses to manage
    PUBLISH_ENDPOINT        — the Type 2 publisher's event endpoint to subscribe to
    SUBSCRIPTION_ID         — the DB subscription ID for metering
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

import aiohttp

from archimedes.db import get_session
from archimedes.models.market import Subscription, SubscriptionAction

# Reuse Type 2 Agent's vault-availability gating logic by importing the
# same chain client and executor patterns.
# The vault check is the SAME gating condition as Type 2:
#   1. Read vault balance from on-chain
#   2. Check against funding threshold
#   3. Only proceed if threshold is met
from archimedes.chain.client import chain_client
from archimedes.chain.executor import chain_executor
from archimedes.models.chat import VaultMetadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

INTERVAL = int(os.getenv("AGENT_INTERVAL_SECONDS", "300"))
EXPLICIT_VAULTS = os.getenv("AGENT_VAULT_ADDRESSES", "")
PUBLISH_ENDPOINT = os.getenv("PUBLISH_ENDPOINT", "")
SUBSCRIPTION_ID = int(os.getenv("SUBSCRIPTION_ID", "0"))

# Default threshold (same as market_routes global default)
_GLOBAL_FUNDING_THRESHOLD = float(os.getenv("MARKET_FUNDING_THRESHOLD", "10.0"))


async def _check_vault_threshold(vault_address: str, threshold: float) -> bool:
    """Check if vault balance meets funding threshold.

    Reuses the same vault-reading pattern as Type 2 Agent's
    _get_managed_vaults() / read_portfolio() flow.
    """
    try:
        vault = chain_executor.loader.vault(vault_address)
        total_assets = await vault.functions.totalAssets().call()
        balance_usdc = total_assets / 1e6  # USDC has 6 decimals
        meets = balance_usdc >= threshold
        logger.debug(
            "Vault %s balance=%.2f USDC threshold=%.2f meets=%s",
            vault_address[:10],
            balance_usdc,
            threshold,
            meets,
        )
        return meets
    except Exception as e:
        logger.warning("Cannot check vault %s balance: %s", vault_address[:10], e)
        return False


async def _get_vault_strategy_ids(vault_address: str) -> list[str] | None:
    """Lookup vault<>strategy mapping from off-chain DB.

    EXACTLY the same pattern as Type 2 Agent's _get_vault_strategy_ids().
    """
    session = get_session()
    try:
        meta = (
            session.query(VaultMetadata)
            .filter(VaultMetadata.vault_address == vault_address)
            .first()
        )
        if meta is None:
            return None
        return meta.get_strategy_ids()
    finally:
        session.close()


async def _fetch_publisher_events(endpoint: str, since: str | None = None) -> list[dict[str, Any]]:
    """Fetch events from the publisher's event endpoint.

    The publisher (Type 2 Agent in the isolated container) exposes an HTTP
    endpoint that returns recent actions/events. This is the subscription
    contract between Type 2 and Type 3 agents.

    Expected response format:
        {"events": [{"type": "...", "data": {...}, "timestamp": "..."}]}
    """
    params = {}
    if since:
        params["since"] = since
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    return body.get("events", [])
                else:
                    logger.warning("Publisher endpoint returned %d", resp.status)
                    return []
    except Exception as e:
        logger.debug("Cannot fetch publisher events: %s", e)
        return []


async def _replicate_action(event: dict[str, Any], subscription_id: int) -> None:
    """Replicate a single action from the publisher.

    In production, this would execute the same on-chain operation the
    publisher performed (e.g., trade, rebalance). Currently a stub
    that records the action for metering.

    Args:
        event: The publisher event to replicate.
        subscription_id: The DB subscription ID for tracking.
    """
    action_type = event.get("type", "unknown")
    action_data = event.get("data", {})

    logger.info(
        "[SUB %d] Replicating action: %s (data: %s)",
        subscription_id,
        action_type,
        json.dumps(action_data)[:100],
    )

    # Record metering/consumption
    session = get_session()
    try:
        action = SubscriptionAction(
            subscription_id=subscription_id,
            action_type=action_type,
            action_data=json.dumps({
                "event": action_data,
                "replicated_at": datetime.now(UTC).isoformat(),
            }),
        )
        session.add(action)
        session.commit()
    except Exception as e:
        logger.warning("Failed to record action %s: %s", action_type, e)
    finally:
        session.close()


async def _update_subscription_status(subscription_id: int, status: str) -> None:
    """Update subscription status in DB."""
    session = get_session()
    try:
        sub = session.query(Subscription).filter(Subscription.id == subscription_id).first()
        if sub:
            sub.status = status
            session.commit()
    except Exception as e:
        logger.warning("Failed to update subscription %d status: %s", subscription_id, e)
    finally:
        session.close()


class ReplicatorAgent:
    """Type 3 Agent — replicates publisher actions for copy-trading.

    Bootstrap pattern mirrors Type 2 Agent's StrategyRunner:
    - CLI entrypoint via `python -m archimedes.chain.agent_replicator`
    - Main loop with configurable interval
    - Vault discovery/management (same gating)
    - Vault<>strategy mapping lookup (same DB query)

    The operational loop differs:
    - Instead of signal evaluation → rebalance → execute,
      it: subscribe to publisher endpoint → check vault threshold →
      follow/replicate actions → track consumption.
    """

    def __init__(self) -> None:
        self._publisher_endpoint = PUBLISH_ENDPOINT
        self._subscription_id = SUBSCRIPTION_ID
        self._known_vaults: set[str] = set()
        self._last_event_timestamp: str | None = None
        self._vault_addresses: list[str] = []

        # Resolve vault addresses from env or subscription
        self._resolve_vaults()

    def _resolve_vaults(self) -> None:
        """Resolve managed vault addresses.

        Mirrors Type 2 Agent's _get_managed_vaults() pattern.
        """
        if EXPLICIT_VAULTS:
            self._vault_addresses = [v.strip() for v in EXPLICIT_VAULTS.split(",") if v.strip()]
            self._known_vaults = set(self._vault_addresses)
            return

        # Try to get vault from subscription record
        if self._subscription_id > 0:
            session = get_session()
            try:
                sub = session.query(Subscription).filter(Subscription.id == self._subscription_id).first()
                if sub and sub.vault_address:
                    self._vault_addresses = [sub.vault_address]
                    self._known_vaults = {sub.vault_address}
            finally:
                session.close()

    async def tick(self) -> None:
        """One tick of the replicator loop.

        The Type 2 Agent tick does: signals → rebalance → execute.
        This tick does: subscribe → check vault → follow → track.
        """
        tick_id = uuid.uuid4().hex[:8]

        if not self._publisher_endpoint:
            logger.debug("[tick %s] No publisher endpoint configured — skipping", tick_id)
            return

        if not self._vault_addresses:
            logger.debug("[tick %s] No vaults configured — skipping", tick_id)
            return

        # Step 1: Subscribe/fetch events from publisher
        events = await _fetch_publisher_events(
            self._publisher_endpoint,
            since=self._last_event_timestamp,
        )

        if not events:
            logger.debug("[tick %s] No new events from publisher", tick_id)
            return

        logger.info("[tick %s] Received %d events from publisher", tick_id, len(events))

        # Step 2+3: For each vault, check threshold and replicate
        for vault_addr in self._vault_addresses:
            # Look up threshold from subscription
            threshold = _GLOBAL_FUNDING_THRESHOLD
            vault_strategy_ids = await _get_vault_strategy_ids(vault_addr)

            if vault_strategy_ids is None:
                logger.debug(
                    "[tick %s] Vault %s has no strategy mapping — skipping (legacy vault)",
                    tick_id,
                    vault_addr[:10],
                )
                continue

            # Check vault availability (same gating as Type 2 Agent)
            meets_threshold = await _check_vault_threshold(vault_addr, threshold)

            if not meets_threshold:
                logger.info(
                    "[tick %s] Vault %s under threshold (%.2f USDC) — pausing operations",
                    tick_id,
                    vault_addr[:10],
                    threshold,
                )
                await _update_subscription_status(self._subscription_id, "paused")
                continue

            # Threshold met — ensure active status
            await _update_subscription_status(self._subscription_id, "active")

            # Step 4: Replicate each event
            for event in events:
                event_type = event.get("type", "unknown")

                # Only replicate trade/rebalance events, not heartbeats
                if event_type in ("trade", "rebalance", "allocation"):
                    await _replicate_action(event, self._subscription_id)

                # Update tracker timestamp
                ts = event.get("timestamp")
                if ts and (self._last_event_timestamp is None or ts > self._last_event_timestamp):
                    self._last_event_timestamp = ts

        logger.info(
            "[tick %s] Processed %d events across %d vault(s)",
            tick_id,
            len(events),
            len(self._vault_addresses),
        )


async def run() -> None:
    """Main replicator loop — mirrors Type 2 Agent's run() pattern."""
    logger.info("Archimedes Replicator Agent (Type 3) starting")
    logger.info("  interval: %ds", INTERVAL)
    logger.info("  publisher_endpoint: %s", PUBLISH_ENDPOINT or "(not configured)")
    logger.info("  subscription_id: %d", SUBSCRIPTION_ID)
    logger.info("  chain_connected: %s", await chain_client.is_connected())

    agent = ReplicatorAgent()

    while True:
        await agent.tick()
        logger.info("Sleeping %ds until next tick", INTERVAL)
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
