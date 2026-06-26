"""Container manager — creates isolated Docker containers for published strategies.

When a strategy is published from Tab 1, the Publish flow:
1. Deploys a new isolated container running a Type 2 Agent instance
2. The new container starts with an empty vault<>strategy reference
3. Inside setup, a new vault is created on chain (same as passport button)
4. The vault<>strategy mapping is created pointing the new vault at the strategy
5. Rebalance → execute steps run in the isolated container
6. The container exposes an event endpoint for Type 3 Agents to subscribe to

Uses the Docker SDK for Python (docker-py).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "archimedes_default")
DOCKER_COMPOSE_PROJECT = os.getenv("DOCKER_COMPOSE_PROJECT", "archimedes")
IMAGE_TAG = os.getenv("PUBLISHED_AGENT_IMAGE", "archimedes-backend:latest")
BACKEND_INTERNAL_URL = os.getenv("BACKEND_INTERNAL_URL", "http://backend:8000")

# Available Docker client
_docker_client: Any = None


def _get_docker_client():
    """Get or create the Docker client."""
    global _docker_client  # noqa: PLW0603
    if _docker_client is None:
        try:
            import docker
            _docker_client = docker.from_env()
        except Exception as e:
            logger.warning("Docker SDK not available: %s", e)
            return None
    return _docker_client


async def create_published_container(
    strategy_id: str,
    vault_address: str,
    container_name: str | None = None,
) -> dict[str, Any]:
    """Create a new isolated container for a published strategy.

    Args:
        strategy_id: The strategy identifier to publish.
        vault_address: The address of the new vault created for this container.
        container_name: Optional custom container name.

    Returns:
        Dict with container_id, container_name, and status.

    Raises:
        RuntimeError: If Docker is not available or container creation fails.
    """
    client = _get_docker_client()
    if client is None:
        logger.info("Docker not available — simulating container creation for strategy %s", strategy_id)
        return {
            "container_id": "simulated",
            "container_name": container_name or f"published-{strategy_id[:12]}",
            "status": "simulated",
            "vault_address": vault_address,
        }

    name = container_name or f"published-{strategy_id[:12]}"
    # Sanitize: Docker container names allow [a-zA-Z0-9_.-]
    name = "".join(c if c.isalnum() or c in "._-" else "-" for c in name)

    env_vars = {
        "DATABASE_URL": os.getenv("DATABASE_URL", ""),
        "REDIS_URL": os.getenv("REDIS_URL", "redis://redis:6379/0"),
        "AGENT_INTERVAL_SECONDS": os.getenv("PUBLISHED_AGENT_INTERVAL_SECONDS", "300"),
        "AGENT_DRY_RUN": os.getenv("AGENT_DRY_RUN", "false"),
        "AGENT_VAULT_ADDRESSES": vault_address,
        "PUBLISHED_STRATEGY_ID": strategy_id,
        "PUBLISHED_VAULT_ADDRESS": vault_address,
        "ARC_VAULT_FACTORY_ADDRESS": os.getenv("ARC_VAULT_FACTORY_ADDRESS", ""),
        "ARC_AMM_ROUTER_ADDRESS": os.getenv("ARC_AMM_ROUTER_ADDRESS", ""),
        "ARC_REASONING_TRACE_REGISTRY_ADDRESS": os.getenv("ARC_REASONING_TRACE_REGISTRY_ADDRESS", ""),
        "ARC_ASSET_REGISTRY_ADDRESS": os.getenv("ARC_ASSET_REGISTRY_ADDRESS", ""),
        "EVENT_PUBLISH_URL": f"{BACKEND_INTERNAL_URL}/api/market/events/push",
    }

    try:
        container = client.containers.run(
            image=IMAGE_TAG,
            command=["python", "-m", "archimedes.chain.agent_runner"],
            name=name,
            network=DOCKER_NETWORK,
            environment=env_vars,
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            labels={
                "archimedes.type": "published-agent",
                "archimedes.strategy": strategy_id,
                "archimedes.vault": vault_address,
            },
        )
        logger.info("Created published container %s (id=%s)", name, container.short_id)
        return {
            "container_id": container.id,
            "container_name": name,
            "status": "created",
            "vault_address": vault_address,
        }
    except Exception as e:
        logger.error("Failed to create container %s: %s", name, e)
        raise RuntimeError(f"Container creation failed: {e}") from e


async def create_replicator_container(
    subscription_id: int,
    vault_address: str,
    publisher_endpoint: str,
) -> dict[str, Any]:
    """Create a Type 3 Agent container for a subscription.

    Args:
        subscription_id: DB subscription ID.
        vault_address: The subscriber's vault address.
        publisher_endpoint: The publisher's event feed URL.

    Returns:
        Dict with container_id, container_name, and status.
    """
    client = _get_docker_client()
    if client is None:
        logger.info("Docker not available — simulating replicator container for sub %d", subscription_id)
        return {
            "container_id": "simulated",
            "container_name": f"replicator-{subscription_id}",
            "status": "simulated",
            "vault_address": vault_address,
        }

    name = f"replicator-{subscription_id}"

    env_vars = {
        "DATABASE_URL": os.getenv("DATABASE_URL", ""),
        "REDIS_URL": os.getenv("REDIS_URL", "redis://redis:6379/0"),
        "AGENT_INTERVAL_SECONDS": os.getenv("AGENT_INTERVAL_SECONDS", "300"),
        "PUBLISH_ENDPOINT": publisher_endpoint,
        "SUBSCRIPTION_ID": str(subscription_id),
        "AGENT_VAULT_ADDRESSES": vault_address,
        "MARKET_FUNDING_THRESHOLD": os.getenv("MARKET_FUNDING_THRESHOLD", "10.0"),
        "ARC_VAULT_FACTORY_ADDRESS": os.getenv("ARC_VAULT_FACTORY_ADDRESS", ""),
        "ARC_AMM_ROUTER_ADDRESS": os.getenv("ARC_AMM_ROUTER_ADDRESS", ""),
    }

    try:
        container = client.containers.run(
            image=IMAGE_TAG,
            command=["python", "-m", "archimedes.chain.agent_replicator"],
            name=name,
            network=DOCKER_NETWORK,
            environment=env_vars,
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            labels={
                "archimedes.type": "replicator",
                "archimedes.subscription": str(subscription_id),
                "archimedes.vault": vault_address,
            },
        )
        logger.info("Created replicator container %s (id=%s)", name, container.short_id)
        return {
            "container_id": container.id,
            "container_name": name,
            "status": "created",
            "vault_address": vault_address,
        }
    except Exception as e:
        logger.error("Failed to create replicator container %s: %s", name, e)
        raise RuntimeError(f"Replicator container creation failed: {e}") from e


async def stop_container(container_name: str) -> bool:
    """Stop and remove a container by name."""
    client = _get_docker_client()
    if client is None:
        logger.info("Docker not available — simulating container stop for %s", container_name)
        return True

    try:
        container = client.containers.get(container_name)
        container.stop(timeout=10)
        container.remove()
        logger.info("Stopped and removed container %s", container_name)
        return True
    except Exception as e:
        logger.warning("Failed to stop container %s: %s", container_name, e)
        return False
