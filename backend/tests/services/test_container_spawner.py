"""Hermetic tests for container_spawner — mocks docker at the boundary."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import DockerException

from archimedes.services.container_spawner import (
    DockerUnavailableError,
    _publisher_name,
    _subscriber_name,
    spawn_publisher,
    spawn_subscriber,
    stop_container,
)


# ── _publisher_name ───────────────────────────────────────────────────────


def test_publisher_name_slugifies_strategy_id():
    """Assert _publisher_name output is lowercase, no underscores."""
    name = _publisher_name("My_Fancy_Strategy_v1")
    assert name == "archimedes-publisher-my-fancy-strategy-v1"
    assert name.islower()
    assert "_" not in name


def test_publisher_name_truncates_long_ids():
    """Assert _publisher_name truncates to fit in 128 chars."""
    long_id = "x_y" * 50  # 150 chars with underscores
    name = _publisher_name(long_id)
    assert len(name) <= 128
    assert name.startswith("archimedes-publisher-")


# ── _subscriber_name ─────────────────────────────────────────────────────


def test_subscriber_name_includes_wallet_suffix():
    """Assert _subscriber_name appends last 8 hex chars of wallet."""
    name = _subscriber_name("strategy_a", "0xAbCdEf1234567890")
    assert "strategy-a" in name
    assert "7890" in name  # last 8 chars of lowercase wallet


# ── spawn_publisher ──────────────────────────────────────────────────────


@patch("docker.from_env")
def test_spawn_publisher_returns_correct_env(mock_from_env):
    """Assert PUBLISHER_STRATEGY_ID, REDIS_URL, PUBLISHER_PORT in env."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_from_env.return_value = mock_client
    mock_client.containers.run.return_value = mock_container

    with patch.dict(os.environ, {"REDIS_URL": "redis://redis:6379"}, clear=True):
        result = spawn_publisher(
            strategy_id="my_strategy",
            creator_wallet="0x1234",
            pool_id="0x" + "ff" * 32,
            vault_address="0x5678",
        )

    # Verify containers.run was called
    assert mock_client.containers.run.called
    _, kwargs = mock_client.containers.run.call_args

    env = kwargs["environment"]
    assert env["PUBLISHER_STRATEGY_ID"] == "my_strategy"
    assert env["REDIS_URL"] == "redis://redis:6379"
    assert env["PUBLISHER_PORT"] == "8080"
    assert env["PUBLISHER_HOST"] == "0.0.0.0"
    assert env["CREATOR_ADDRESS"] == "0x1234"

    assert result["container_id"] == "abc123"
    assert result["container_name"] == "archimedes-publisher-my-strategy"
    assert result["publisher_endpoint"] == "http://archimedes-publisher-my-strategy:8080"
    assert result["vault_address"] == "0x5678"


@patch("docker.from_env")
def test_spawn_publisher_injects_shared_env(mock_from_env):
    """Assert shared env vars are forwarded into container env."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.short_id = "def456"
    mock_from_env.return_value = mock_client
    mock_client.containers.run.return_value = mock_container

    with patch.dict(
        os.environ,
        {
            "ARC_RPC_URL": "https://rpc.testnet.arc.network",
            "ARC_USDC_ADDRESS": "0xusdc",
            "AGENT_INTERVAL_SECONDS": "60",
        },
        clear=True,
    ):
        result = spawn_publisher(
            strategy_id="s1",
            creator_wallet="0x1234",
            pool_id="0x" + "aa" * 32,
        )

    _, kwargs = mock_client.containers.run.call_args
    env = kwargs["environment"]
    assert env["ARC_RPC_URL"] == "https://rpc.testnet.arc.network"
    assert env["ARC_USDC_ADDRESS"] == "0xusdc"
    assert env["AGENT_INTERVAL_SECONDS"] == "60"
    assert result["container_id"] == "def456"


@patch("docker.from_env")
def test_spawn_publisher_uses_correct_image_and_network(mock_from_env):
    """Assert image=archimedes-fork-publisher and network set."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.short_id = "ghi789"
    mock_from_env.return_value = mock_client
    mock_client.containers.run.return_value = mock_container

    spawn_publisher(
        strategy_id="s1",
        creator_wallet="0x1234",
        pool_id="0x" + "bb" * 32,
    )

    _, kwargs = mock_client.containers.run.call_args
    assert kwargs["image"] == "archimedes-fork-publisher"
    assert "network" in kwargs


@patch("docker.from_env")
def test_spawn_publisher_volume_mounts(mock_from_env):
    """Assert abis and strategies volumes are mounted."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.short_id = "vol123"
    mock_from_env.return_value = mock_client
    mock_client.containers.run.return_value = mock_container

    spawn_publisher(
        strategy_id="s1",
        creator_wallet="0x1234",
        pool_id="0x" + "cc" * 32,
    )

    _, kwargs = mock_client.containers.run.call_args
    volumes = kwargs["volumes"]
    assert any("/contracts/abis" in str(v) for v in volumes.keys())
    assert any(
        "/analytics-engine/strategies" in str(v) or "strategies" in str(v)
        for v in volumes.keys()
    )


@patch("docker.from_env")
def test_spawn_publisher_raises_docker_unavailable(mock_from_env):
    """When docker.from_env() raises, spawn_publisher raises DockerUnavailableError."""
    mock_from_env.side_effect = DockerException("socket not found")

    with pytest.raises(DockerUnavailableError):
        spawn_publisher(
            strategy_id="s1",
            creator_wallet="0x1234",
            pool_id="0x" + "dd" * 32,
        )


# ── spawn_subscriber ──────────────────────────────────────────────────────


@patch("docker.from_env")
def test_spawn_subscriber_injects_advertise_host(mock_from_env):
    """Assert SUBSCRIBER_ADVERTISE_HOST == container_name in env."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.short_id = "sub123"
    mock_from_env.return_value = mock_client
    mock_client.containers.run.return_value = mock_container

    result = spawn_subscriber(
        strategy_id="my_strategy",
        subscriber_wallet="0xWallet1234567890",
        pool_id="0x" + "ee" * 32,
        sub_id="0x" + "ff" * 32,
        publisher_container_name="archimedes-publisher-my-strategy",
    )

    _, kwargs = mock_client.containers.run.call_args
    env = kwargs["environment"]
    expected_name = result["container_name"]
    assert env["SUBSCRIBER_ADVERTISE_HOST"] == expected_name
    assert env["SUBSCRIBER_HOST"] == "0.0.0.0"
    assert env["SUBSCRIBER_PORT"] == "8081"


@patch("docker.from_env")
def test_spawn_subscriber_sets_publisher_endpoint(mock_from_env):
    """Assert PUBLISHER_ENDPOINT uses publisher container name."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.short_id = "sub456"
    mock_from_env.return_value = mock_client
    mock_client.containers.run.return_value = mock_container

    spawn_subscriber(
        strategy_id="s1",
        subscriber_wallet="0xWallet1234567890",
        pool_id="0x" + "ee" * 32,
        sub_id="0x" + "ff" * 32,
        publisher_container_name="archimedes-publisher-my-strategy",
    )

    _, kwargs = mock_client.containers.run.call_args
    env = kwargs["environment"]
    assert env["PUBLISHER_ENDPOINT"] == "http://archimedes-publisher-my-strategy:8080"


@patch("docker.from_env")
def test_spawn_subscriber_image_and_network(mock_from_env):
    """Assert subscriber uses correct image and network."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.short_id = "sub789"
    mock_from_env.return_value = mock_client
    mock_client.containers.run.return_value = mock_container

    spawn_subscriber(
        strategy_id="s1",
        subscriber_wallet="0xWallet1234567890",
        pool_id="0x" + "ee" * 32,
        sub_id="0x" + "ff" * 32,
        publisher_container_name="pub-name",
    )

    _, kwargs = mock_client.containers.run.call_args
    assert kwargs["image"] == "archimedes-fork-subscriber"
    assert "network" in kwargs


@patch("docker.from_env")
def test_spawn_subscriber_raises_docker_unavailable(mock_from_env):
    """When docker.from_env() raises, spawn_subscriber raises DockerUnavailableError."""
    mock_from_env.side_effect = DockerException("socket not found")

    with pytest.raises(DockerUnavailableError):
        spawn_subscriber(
            strategy_id="s1",
            subscriber_wallet="0x1234",
            pool_id="0x" + "ee" * 32,
            sub_id="0x" + "ff" * 32,
            publisher_container_name="pub-name",
        )


# ── stop_container ────────────────────────────────────────────────────────


@patch("docker.from_env")
def test_stop_container_calls_stop_and_remove(mock_from_env):
    """Assert stop_container stops and removes the container."""
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_from_env.return_value = mock_client
    mock_client.containers.get.return_value = mock_container

    stop_container("archimedes-publisher-s1")

    mock_client.containers.get.assert_called_once_with("archimedes-publisher-s1")
    mock_container.stop.assert_called_once_with(timeout=10)
    mock_container.remove.assert_called_once()
