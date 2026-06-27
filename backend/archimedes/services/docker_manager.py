"""Docker Manager — programmatic container lifecycle for the Copy Trading Market.

Provides helpers to start and stop Docker containers for:
- Type 2 Agents (publishers): agent-pub-<id>
- Type 3 Agents (replicators for publish flow): agent-rep-<id>
- Type 3 Agents (subscribers): agent-sub-<id>

Uses the Docker SDK for Python (docker-py). All environment variables from
the running backend process are forwarded to spawned containers so they
share the same DB, Redis, and chain configuration.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ─── Docker client helpers ───────────────────────────────────

_docker_client: Any = None


def _get_docker() -> Any | None:
    """Get or create the Docker client.

    Returns None if Docker is not available (e.g. socket not mounted),
    in which case container operations are silently skipped.
    """
    global _docker_client  # noqa: PLW0603
    if _docker_client is None:
        try:
            import docker  # type: ignore[import-untyped]

            _docker_client = docker.from_env()
            _docker_client.ping()
            logger.info("Docker client connected successfully")
        except Exception as exc:
            logger.warning("Docker not available — %s. Container operations skipped.", exc)
            return None
    return _docker_client


def _resolve_network() -> str:
    """Resolve the Docker bridge network name.

    Priority:
    1. DOCKER_NETWORK env var (explicit override)
    2. DOCKER_COMPOSE_PROJECT env var → <project>_default
    3. Fallback: 'archimedes_default'
    """
    explicit = os.getenv("DOCKER_NETWORK")
    if explicit:
        return explicit
    project = os.getenv("DOCKER_COMPOSE_PROJECT", "archimedes")
    return f"{project}_default"


def _backend_env() -> dict[str, str]:
    """Return all environment variables from the running backend process.

    This ensures spawned containers inherit DB, Redis, chain addresses, etc.
    """
    return dict(os.environ)


def _image_tag() -> str:
    """Return the Docker image tag for spawned agent containers."""
    return os.getenv("PUBLISHED_AGENT_IMAGE", "archimedes-backend:latest")


def _remove_existing(name: str) -> None:
    """If a container with *name* exists, stop and remove it (idempotent)."""
    client = _get_docker()
    if client is None:
        return
    try:
        existing = client.containers.get(name)
        logger.info("Removing existing container %s (id=%s)", name, existing.short_id)
        existing.stop(timeout=10)
        existing.remove()
    except Exception:
        pass  # container does not exist — nothing to remove


# ─── Publisher agent (Type 2) ───────────────────────────────


def start_publisher_agent(
    published_strategy_id: int,
    vault_address: str,
    creator_address: str,
    strategy_id: str,
) -> dict[str, Any]:
    """Start a Type 2 Agent container for a published strategy.

    Container name: agent-pub-<published_strategy_id>

    Returns dict with container_id, container_name, status.
    """
    client = _get_docker()
    if client is None:
        logger.info(
            "Docker unavailable — simulated publisher for published_strategy_id=%d",
            published_strategy_id,
        )
        return {
            "container_id": "simulated",
            "container_name": f"agent-pub-{published_strategy_id}",
            "status": "simulated",
        }

    name = f"agent-pub-{published_strategy_id}"
    publish_endpoint = f"http://{name}:8001/events"

    _remove_existing(name)

    env = _backend_env()
    env.update({
        "PUBLISHED_STRATEGY_ID": str(published_strategy_id),
        "AGENT_VAULT_ADDRESSES": vault_address,
        "PUBLISH_ENDPOINT": publish_endpoint,
        "AGENT_DRY_RUN": "false",
        "PUBLISHED_VAULT_ADDRESS": vault_address,
        "PUBLISHED_VAULT_CREATOR_ADDRESS": creator_address,
    })

    try:
        container = client.containers.run(
            image=_image_tag(),
            command=["python", "-m", "archimedes.chain.agent_runner"],
            name=name,
            network=_resolve_network(),
            environment=env,
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            labels={
                "archimedes.type": "published-agent",
                "archimedes.published_strategy_id": str(published_strategy_id),
                "archimedes.strategy": strategy_id,
                "archimedes.vault": vault_address,
            },
        )
        logger.info("Started publisher container %s (id=%s)", name, container.short_id)
        return {
            "container_id": container.id,
            "container_name": name,
            "status": "created",
        }
    except Exception as exc:
        logger.error("Failed to start publisher container %s: %s", name, exc)
        raise RuntimeError(f"Publisher container creation failed: {exc}") from exc


# ─── Publish-flow replicator (Type 3, one per published strategy) ──


def start_replicator_agent(
    published_strategy_id: int,
    vault_address: str,
    strategy_id: str,
    publish_endpoint: str,
) -> dict[str, Any]:
    """Start a Type 3 Agent container for a published strategy's replicator.

    This is the replicator that the *publisher* owns — it monitors the
    publisher's event feed and replicates trades into the publisher's vault.
    (Subscribers get their own per-subscription replicators via
    start_subscriber_replicator.)

    Container name: agent-rep-<published_strategy_id>

    Returns dict with container_id, container_name, status.
    """
    client = _get_docker()
    if client is None:
        logger.info(
            "Docker unavailable — simulated replicator for published_strategy_id=%d",
            published_strategy_id,
        )
        return {
            "container_id": "simulated",
            "container_name": f"agent-rep-{published_strategy_id}",
            "status": "simulated",
        }

    name = f"agent-rep-{published_strategy_id}"
    _remove_existing(name)

    env = _backend_env()
    env.update({
        "PUBLISHED_STRATEGY_ID": str(published_strategy_id),
        "PUBLISH_ENDPOINT": publish_endpoint,
        "SUBSCRIPTION_ID": "0",
        "AGENT_VAULT_ADDRESSES": vault_address,
    })

    try:
        container = client.containers.run(
            image=_image_tag(),
            command=["python", "-m", "archimedes.chain.agent_replicator"],
            name=name,
            network=_resolve_network(),
            environment=env,
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            labels={
                "archimedes.type": "publish-replicator",
                "archimedes.published_strategy_id": str(published_strategy_id),
                "archimedes.strategy": strategy_id,
                "archimedes.vault": vault_address,
            },
        )
        logger.info("Started publish-replicator container %s (id=%s)", name, container.short_id)
        return {
            "container_id": container.id,
            "container_name": name,
            "status": "created",
        }
    except Exception as exc:
        logger.error("Failed to start publish-replicator container %s: %s", name, exc)
        raise RuntimeError(f"Publish replicator container creation failed: {exc}") from exc


# ─── Subscriber replicator (Type 3, one per subscription) ───


def start_subscriber_replicator(
    subscription_id: int,
    published_strategy_id: int,
    vault_address: str,
    publish_endpoint: str,
) -> dict[str, Any]:
    """Start a Type 3 Agent container for a subscriber's subscription.

    Container name: agent-sub-<subscription_id>

    Returns dict with container_id, container_name, status.
    """
    client = _get_docker()
    if client is None:
        logger.info(
            "Docker unavailable — simulated subscriber replicator for subscription_id=%d",
            subscription_id,
        )
        return {
            "container_id": "simulated",
            "container_name": f"agent-sub-{subscription_id}",
            "status": "simulated",
        }

    name = f"agent-sub-{subscription_id}"
    _remove_existing(name)

    env = _backend_env()
    env.update({
        "SUBSCRIPTION_ID": str(subscription_id),
        "PUBLISHED_STRATEGY_ID": str(published_strategy_id),
        "PUBLISH_ENDPOINT": publish_endpoint,
        "AGENT_VAULT_ADDRESSES": vault_address,
    })

    try:
        container = client.containers.run(
            image=_image_tag(),
            command=["python", "-m", "archimedes.chain.agent_replicator"],
            name=name,
            network=_resolve_network(),
            environment=env,
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            labels={
                "archimedes.type": "subscriber-replicator",
                "archimedes.subscription_id": str(subscription_id),
                "archimedes.published_strategy_id": str(published_strategy_id),
                "archimedes.vault": vault_address,
            },
        )
        logger.info("Started subscriber replicator container %s (id=%s)", name, container.short_id)
        return {
            "container_id": container.id,
            "container_name": name,
            "status": "created",
        }
    except Exception as exc:
        logger.error("Failed to start subscriber replicator container %s: %s", name, exc)
        raise RuntimeError(f"Subscriber replicator container creation failed: {exc}") from exc


# ─── Container teardown ─────────────────────────────────────


def stop_container(container_name: str) -> bool:
    """Stop and remove a container by name.

    Returns True on success (or if container doesn't exist), False on error.
    """
    client = _get_docker()
    if client is None:
        logger.info("Docker unavailable — simulated stop for %s", container_name)
        return True

    try:
        container = client.containers.get(container_name)
        container.stop(timeout=10)
        container.remove()
        logger.info("Stopped and removed container %s", container_name)
        return True
    except Exception as exc:
        logger.warning("Failed to stop/remove container %s: %s", container_name, exc)
        return False


def is_container_running(container_name: str) -> bool:
    """Check whether a container with *name* exists and is running."""
    client = _get_docker()
    if client is None:
        return False
    try:
        container = client.containers.get(container_name)
        return container.status == "running"
    except Exception:
        return False
