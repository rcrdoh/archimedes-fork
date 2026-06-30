"""Container spawner — wraps the Docker SDK for marketplace publisher/subscriber agents.

All Docker calls are isolated in this module so tests can mock at the boundary.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Shared environment keys forwarded to every spawned container ──────────

_SHARED_ENV_KEYS = [
    "ARC_RPC_URL",
    "ARC_AGENT_PRIVATE_KEY",
    "CIRCLE_API_KEY",
    "CIRCLE_ENTITY_SECRET",
    "WALLET_ID",
    "REDIS_URL",
    "ARC_VAULT_FACTORY_ADDRESS",
    "ARC_AMM_ROUTER_ADDRESS",
    "ARC_REASONING_TRACE_REGISTRY_ADDRESS",
    "ARC_PAYMENT_SPLITTER_ADDRESS",
    "ARC_SUBSCRIPTION_MANAGER_ADDRESS",
    "ARC_USDC_ADDRESS",
    "AGENT_INTERVAL_SECONDS",
    "AGENT_DRY_RUN",
]


# ── Custom exceptions ────────────────────────────────────────────────────


class ContainerSpawnError(RuntimeError):
    """Generic container spawn failure."""


class ContainerAlreadyRunningError(ContainerSpawnError):
    """A publisher/subscriber for this strategy is already running."""


class PublisherNotRunningError(ContainerSpawnError):
    """No running publisher exists for this strategy."""


class DockerUnavailableError(ContainerSpawnError):
    """Docker socket is not available."""


# ── Naming helpers ───────────────────────────────────────────────────────


def _publisher_name(strategy_id: str) -> str:
    slug = strategy_id.replace("_", "-").lower()[:40]
    return f"archimedes-publisher-{slug}"


def _subscriber_name(strategy_id: str, subscriber_wallet: str) -> str:
    slug = strategy_id.replace("_", "-").lower()[:30]
    wallet_short = subscriber_wallet.lower()[-8:]
    return f"archimedes-subscriber-{slug}-{wallet_short}"


# ── Path / network helpers ───────────────────────────────────────────────


def _repo_root() -> Path:
    """Walk up from this file to find the repository root (has docker-compose.yml)."""
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "docker-compose.yml").exists():
            return parent
    return p.parents[4]  # fallback heuristic


def _abis_host_path() -> str:
    """Absolute host path for contracts/abis/ volume mount."""
    override = os.environ.get("COMPOSE_PROJECT_DIR")
    if override:
        return str(Path(override).resolve() / "contracts" / "abis")
    return str(_repo_root() / "contracts" / "abis")


def _strategies_host_path() -> str:
    """Absolute host path for analytics-engine/strategies/ volume mount."""
    override = os.environ.get("COMPOSE_PROJECT_DIR")
    if override:
        return str(Path(override).resolve() / "analytics-engine" / "strategies")
    return str(_repo_root() / "analytics-engine" / "strategies")


def _docker_network() -> str:
    """Docker network name for spawned containers to join."""
    override = os.environ.get("DOCKER_COMPOSE_NETWORK")
    if override:
        return override
    project = os.environ.get("COMPOSE_PROJECT_NAME", "archimedes-fork")
    return f"{project}_default"


def _build_env(extra: dict[str, str]) -> dict[str, str]:
    """Build environment dict from shared keys + extra vars.

    Shared keys are read from the current process environment; missing
    keys are silently skipped.
    """
    env = {}
    for key in _SHARED_ENV_KEYS:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    env.update(extra)
    return env


# ── Spawn functions ──────────────────────────────────────────────────────


def spawn_publisher(
    strategy_id: str,
    creator_wallet: str,
    pool_id: str,
    vault_address: str = "",
    platform_wallet: str = "",
) -> dict:
    """Spawn a publisher agent container for a strategy.

    Returns dict with keys: container_id, container_name, publisher_endpoint, vault_address.
    Raises ContainerAlreadyRunningError if a publisher for this strategy_id
    already has status='running' in the DB.
    Raises DockerUnavailableError if Docker socket is not available.
    """
    container_name = _publisher_name(strategy_id)
    resolved_platform = platform_wallet or os.environ.get("PLATFORM_WALLET", "")

    env = _build_env(
        {
            "PUBLISHER_STRATEGY_ID": strategy_id,
            "PUBLISHER_VAULT_ADDRESS": vault_address,
            "PUBLISHER_POOL_ID": pool_id,
            "CREATOR_ADDRESS": creator_wallet,
            "PLATFORM_WALLET": resolved_platform,
            "PUBLISHER_HOST": "0.0.0.0",
            "PUBLISHER_PORT": "8080",
        }
    )

    try:
        import docker
        from docker.errors import DockerException
    except ImportError:
        raise ContainerSpawnError("docker package not installed") from None

    try:
        client = docker.from_env()
    except DockerException as exc:
        raise DockerUnavailableError(f"Docker socket unavailable: {exc}") from exc

    abis_path = _abis_host_path()
    strategies_path = _strategies_host_path()
    network = _docker_network()

    logger.info("Spawning publisher container '%s' (strategy=%s)", container_name, strategy_id)

    container = client.containers.run(
        image="archimedes-fork-publisher",
        name=container_name,
        environment=env,
        detach=True,
        remove=False,
        network=network,
        volumes={
            abis_path: {"bind": "/contracts/abis", "mode": "ro"},
            strategies_path: {"bind": "/app/analytics-engine/strategies", "mode": "ro"},
        },
    )
    container.reload()

    return {
        "container_id": container.short_id,
        "container_name": container_name,
        "publisher_endpoint": f"http://{container_name}:8080",
        "vault_address": vault_address,
    }


def spawn_subscriber(
    strategy_id: str,
    subscriber_wallet: str,
    pool_id: str,
    sub_id: str,
    publisher_container_name: str,
    initial_deposit_usdc: int = 10_000_000,
) -> dict:
    """Spawn a subscriber agent container.

    publisher_container_name is used to construct PUBLISHER_ENDPOINT.
    Returns dict with keys: container_id, container_name.
    Raises DockerUnavailableError if Docker socket is not available.
    """
    container_name = _subscriber_name(strategy_id, subscriber_wallet)

    env = _build_env(
        {
            "SUBSCRIBER_WALLET_ADDRESS": subscriber_wallet,
            "SUBSCRIBER_SUB_ID": sub_id,
            "SUBSCRIBER_POOL_ID": pool_id,
            "PUBLISHER_ENDPOINT": f"http://{publisher_container_name}:8080",
            "INITIAL_DEPOSIT_USDC": str(initial_deposit_usdc),
            "SUBSCRIBER_HOST": "0.0.0.0",
            "SUBSCRIBER_ADVERTISE_HOST": container_name,
            "SUBSCRIBER_PORT": "8081",
        }
    )

    try:
        import docker
        from docker.errors import DockerException
    except ImportError:
        raise ContainerSpawnError("docker package not installed") from None

    try:
        client = docker.from_env()
    except DockerException as exc:
        raise DockerUnavailableError(f"Docker socket unavailable: {exc}") from exc

    abis_path = _abis_host_path()
    network = _docker_network()

    logger.info(
        "Spawning subscriber container '%s' (strategy=%s, wallet=%s)",
        container_name,
        strategy_id,
        subscriber_wallet,
    )

    container = client.containers.run(
        image="archimedes-fork-subscriber",
        name=container_name,
        environment=env,
        detach=True,
        remove=False,
        network=network,
        volumes={
            abis_path: {"bind": "/contracts/abis", "mode": "ro"},
        },
    )
    container.reload()

    return {
        "container_id": container.short_id,
        "container_name": container_name,
    }


def stop_container(container_name: str) -> None:
    """Stop and remove a container by name."""
    try:
        import docker
        from docker.errors import DockerException, NotFound
    except ImportError:
        raise ContainerSpawnError("docker package not installed") from None

    try:
        client = docker.from_env()
    except DockerException as exc:
        raise DockerUnavailableError(f"Docker socket unavailable: {exc}") from exc

    try:
        container = client.containers.get(container_name)
        container.stop(timeout=10)
        container.remove()
        logger.info("Stopped and removed container '%s'", container_name)
    except NotFound:
        logger.warning("Container '%s' not found — already removed", container_name)
    except DockerException as exc:
        raise ContainerSpawnError(f"Failed to stop container {container_name}: {exc}") from exc
