"""Tests for marketplace API routes — hermetic, no Docker daemon needed."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

_WALLET_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_WALLET_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path, monkeypatch):
    """Point the DB at a temp SQLite so we don't pollute the real one."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # Recreate engine + session to pick up the monkeypatched DATABASE_URL
    import archimedes.db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_module.engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    db_module.SessionLocal = sessionmaker(
        bind=db_module.engine, autocommit=False, autoflush=False
    )
    from archimedes.db import init_db
    init_db()
    yield


@pytest.fixture
def app():
    from archimedes.main import app
    return app


@pytest.fixture
def client(app):
    """FastAPI TestClient with all service dependencies mocked."""
    patches = [
        patch("archimedes.api.marketplace_routes.spawn_publisher"),
        patch("archimedes.api.marketplace_routes.spawn_subscriber"),
        patch("archimedes.api.marketplace_routes.stop_container"),
    ]
    for p in patches:
        p.start()
    from archimedes.api.marketplace_routes import spawn_publisher, spawn_subscriber, stop_container

    spawn_publisher.return_value = {
        "container_id": "pub123",
        "container_name": "archimedes-publisher-s1",
        "publisher_endpoint": "http://archimedes-publisher-s1:8080",
        "vault_address": "0x0000000000000000000000000000000000000001",
    }
    spawn_subscriber.return_value = {
        "container_id": "sub123",
        "container_name": "archimedes-subscriber-s1-12345678",
        "sub_id": "0x" + "aa" * 32,
        "publisher_endpoint": "http://archimedes-publisher-s1:8080",
    }
    stop_container.return_value = None

    from fastapi.testclient import TestClient
    tc = TestClient(app)
    yield tc
    for p in patches:
        p.stop()


@pytest.fixture
def auth_client(client):
    """Client with Wallet A cookie set."""
    from archimedes.api.auth_siwe import _COOKIE_NAME, _sign_session
    client.cookies.update({_COOKIE_NAME: _sign_session(_WALLET_A.lower(), time.time())})
    return client


# ── Helper: insert publisher row ──────────────────────────────────────────


def _insert_publisher(
    strategy_id: str = "s1",
    wallet: str = _WALLET_A,
    container_name: str = "archimedes-publisher-s1",
    pool_id: str = "0x" + "ff" * 32,
    status: str = "running",
    vault_address: str = "0xvault",
):
    from archimedes.db import get_session
    from archimedes.models.marketplace import MarketplaceContainer
    db = get_session()
    try:
        row = MarketplaceContainer(
            container_id="cid_" + strategy_id,
            container_name=container_name,
            role="publisher",
            strategy_id=strategy_id,
            creator_wallet=wallet,
            pool_id=pool_id,
            vault_address=vault_address,
            status=status,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _insert_subscriber(
    strategy_id: str = "s1",
    wallet: str = _WALLET_A,
    sub_id: str = "0x" + "aa" * 32,
    status: str = "running",
):
    from archimedes.db import get_session
    from archimedes.models.marketplace import MarketplaceContainer
    db = get_session()
    try:
        wallet_short = wallet.lower()[-8:]
        row = MarketplaceContainer(
            container_id="cid_sub_" + wallet_short,
            container_name=f"archimedes-subscriber-{strategy_id}-{wallet_short}",
            role="subscriber",
            strategy_id=strategy_id,
            subscriber_wallet=wallet,
            sub_id=sub_id,
            status=status,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


# ── Tests: publish ────────────────────────────────────────────────────────


class TestPublish:
    def test_publish_returns_201(self, auth_client):
        res = auth_client.post(
            "/api/marketplace/publish",
            json={
                "strategy_id": "s1",
                "pool_id": "0x" + "ff" * 32,
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["strategy_id"] == "s1"
        assert body["container_id"] == "pub123"
        assert body["status"] == "spawned"

    def test_publish_409_if_already_running(self, auth_client):
        _insert_publisher()
        res = auth_client.post(
            "/api/marketplace/publish",
            json={
                "strategy_id": "s1",
                "pool_id": "0x" + "ff" * 32,
            },
        )
        assert res.status_code == 409

    def test_publish_db_row_persisted(self, auth_client):
        res = auth_client.post(
            "/api/marketplace/publish",
            json={
                "strategy_id": "s1",
                "pool_id": "0x" + "ff" * 32,
                "vault_address": "0x0000000000000000000000000000000000000001",
            },
        )
        assert res.status_code == 201
        from archimedes.db import get_session
        from archimedes.models.marketplace import MarketplaceContainer
        db = get_session()
        try:
            row = db.query(MarketplaceContainer).filter_by(strategy_id="s1").first()
            assert row is not None
            assert row.role == "publisher"
            assert row.vault_address == "0x0000000000000000000000000000000000000001"
        finally:
            db.close()

    def test_docker_unavailable_returns_503(self, auth_client):
        from archimedes.services.container_spawner import DockerUnavailableError
        from archimedes.api.marketplace_routes import spawn_publisher as mock_sp
        mock_sp.side_effect = DockerUnavailableError("no docker")
        res = auth_client.post(
            "/api/marketplace/publish",
            json={
                "strategy_id": "s1",
                "pool_id": "0x" + "ff" * 32,
            },
        )
        assert res.status_code == 503
        mock_sp.side_effect = None


# ── Tests: subscribe ──────────────────────────────────────────────────────


class TestSubscribe:
    def test_subscribe_404_if_no_publisher(self, auth_client):
        res = auth_client.post(
            "/api/marketplace/subscribe",
            json={
                "strategy_id": "s1",
                "pool_id": "0x" + "ff" * 32,
                "sub_id": "0x" + "aa" * 32,
            },
        )
        assert res.status_code == 404

    def test_subscribe_returns_201(self, auth_client):
        _insert_publisher()
        res = auth_client.post(
            "/api/marketplace/subscribe",
            json={
                "strategy_id": "s1",
                "pool_id": "0x" + "ff" * 32,
                "sub_id": "0x" + "aa" * 32,
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["strategy_id"] == "s1"
        assert body["sub_id"] == "0x" + "aa" * 32
        assert body["status"] == "spawned"

    def test_subscribe_409_if_already_subscribed(self, auth_client):
        _insert_publisher()
        _insert_subscriber()
        res = auth_client.post(
            "/api/marketplace/subscribe",
            json={
                "strategy_id": "s1",
                "pool_id": "0x" + "ff" * 32,
                "sub_id": "0x" + "bb" * 32,
            },
        )
        assert res.status_code == 409

    def test_subscribe_503_on_docker_error(self, auth_client):
        from archimedes.services.container_spawner import DockerUnavailableError
        from archimedes.api.marketplace_routes import spawn_subscriber as mock_ss
        _insert_publisher()
        mock_ss.side_effect = DockerUnavailableError("no docker")
        res = auth_client.post(
            "/api/marketplace/subscribe",
            json={
                "strategy_id": "s1",
                "pool_id": "0x" + "ff" * 32,
                "sub_id": "0x" + "aa" * 32,
            },
        )
        assert res.status_code == 503
        mock_ss.side_effect = None


# ── Tests: stop publish ───────────────────────────────────────────────────


class TestStopPublish:
    def test_stop_publisher_403_wrong_wallet(self, auth_client):
        _insert_publisher(wallet=_WALLET_B)
        res = auth_client.delete("/api/marketplace/publish/s1")
        assert res.status_code == 403

    def test_stop_publisher_404(self, auth_client):
        res = auth_client.delete("/api/marketplace/publish/nonexistent")
        assert res.status_code == 404

    def test_stop_publisher_success(self, auth_client):
        _insert_publisher()
        res = auth_client.delete("/api/marketplace/publish/s1")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "stopped"


# ── Tests: stop subscribe ─────────────────────────────────────────────────


class TestStopSubscribe:
    def test_stop_sub_success(self, auth_client):
        _insert_subscriber(wallet=_WALLET_A)
        res = auth_client.delete("/api/marketplace/subscribe/s1")
        assert res.status_code == 200

    def test_stop_sub_404(self, auth_client):
        res = auth_client.delete("/api/marketplace/subscribe/nonexistent")
        assert res.status_code == 404


# ── Tests: published list ─────────────────────────────────────────────────


class TestPublishedList:
    def test_no_auth_required(self, client):
        _insert_publisher()
        res = client.get("/api/marketplace/published")
        assert res.status_code == 200

    def test_publisher_centric_shape(self, client):
        _insert_publisher()
        _insert_subscriber(strategy_id="s1", wallet=_WALLET_A)
        _insert_subscriber(strategy_id="s1", wallet=_WALLET_B)
        res = client.get("/api/marketplace/published")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert len(body["strategies"]) == 1
        entry = body["strategies"][0]
        assert entry["strategy_id"] == "s1"
        assert entry["active_subscriber_count"] == 2
        assert len(entry["subscribers"]) == 2

    def test_default_running_only(self, client):
        _insert_publisher(strategy_id="s1", status="running")
        _insert_publisher(
            strategy_id="s2",
            wallet=_WALLET_B,
            container_name="archimedes-publisher-s2",
            pool_id="0x" + "ee" * 32,
            status="stopped",
        )
        res = client.get("/api/marketplace/published")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1

    def test_status_all_includes_stopped(self, client):
        _insert_publisher(strategy_id="s1", status="running")
        _insert_publisher(
            strategy_id="s2",
            wallet=_WALLET_B,
            container_name="archimedes-publisher-s2",
            pool_id="0x" + "ee" * 32,
            status="stopped",
        )
        res = client.get("/api/marketplace/published?status=all")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 2


# ── Tests: published detail ───────────────────────────────────────────────


class TestPublishedDetail:
    def test_detail_200(self, client):
        _insert_publisher(vault_address="0xvault123")
        res = client.get("/api/marketplace/published/s1")
        assert res.status_code == 200
        body = res.json()
        assert body["strategy_id"] == "s1"
        assert body["vault_address"] == "0xvault123"

    def test_detail_404(self, client):
        res = client.get("/api/marketplace/published/nonexistent")
        assert res.status_code == 404


# ── Tests: my subscriptions ───────────────────────────────────────────────


class TestMySubscriptions:
    def test_requires_auth(self, client):
        res = client.get("/api/marketplace/my-subscriptions")
        assert res.status_code == 401

    def test_scoped_to_caller(self, client):
        _insert_subscriber(strategy_id="s1", wallet=_WALLET_A)
        _insert_subscriber(
            strategy_id="s2",
            wallet=_WALLET_B,
            sub_id="0x" + "bb" * 32,
        )
        from archimedes.api.auth_siwe import _COOKIE_NAME, _sign_session
        client.cookies.update({_COOKIE_NAME: _sign_session(_WALLET_A.lower(), time.time())})
        res = client.get("/api/marketplace/my-subscriptions")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["subscriptions"][0]["sub_id"] == "0x" + "aa" * 32
