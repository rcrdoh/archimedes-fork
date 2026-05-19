"""FastAPI route-layer tests — TestClient against real routes, mocked chain.

Tests HTTP status + response-schema shape for the judge-facing API surface.
Hermetic: no testnet, no Circle SDK, no Anthropic — chain client is mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from archimedes.db import get_session, init_db
from archimedes.models.backtest_store import BacktestResultRecord
from archimedes.services.backtest_mapper import (
    AnalyticsArtifactModel,
    canonical_artifact_hash,
    map_artifact_to_backtest_result,
)
from archimedes.services.backtest_repository import insert_backtest_if_missing

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "analytics_artifact_buy_hold.json"


@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path, monkeypatch):
    """Point the DB at a temp SQLite so we don't pollute the real one."""
    db_path = tmp_path / "test_archimedes.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    init_db()
    yield


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with mocked chain client (no testnet calls)."""
    with patch("archimedes.chain.client.chain_client") as mock_chain, \
         patch("archimedes.chain.executor.chain_executor") as mock_executor:
        mock_chain.is_connected = AsyncMock(return_value=False)
        mock_chain.send_transaction = AsyncMock(return_value="0xmock_tx_hash")
        # ConfigService reads contract addresses from chain_client
        mock_chain.usdc_address = "0x3600000000000000000000000000000000000000"
        mock_chain.synthetic_factory_address = ""
        mock_chain.amm_router_address = "0xd5b829f9d364a8bbe1caf6c8b19cb05371b178f4"
        mock_chain.vault_factory_address = "0xca873414070844aeb98b0bf1051f81969c79cc32"
        mock_chain.reasoning_trace_registry_address = "0x42d8a23edb897cbee203e9fa197eb05ab5106ca6"
        mock_chain.asset_registry_address = "0x2d44550711137916df6175587d17886281a0fbc7"
        mock_chain.price_oracle_address = "0xe1c9f2b11be97097223a66a188fca541e07873a6"
        mock_chain.rpc_url = "https://rpc.testnet.arc.network"
        mock_chain.chain_id = 5042002
        mock_chain.get_all_synthetic_tokens = AsyncMock(return_value=[])
        mock_executor.get_all_vaults = AsyncMock(return_value=[])
        mock_executor.get_vault_metrics = AsyncMock(return_value={"total_aum_usdc": 0.0})

        from archimedes.main import app
        tc = TestClient(app)
        yield tc


@pytest.fixture()
def seeded_db():
    """Seed the temp DB with the buy-hold fixture artifact."""
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    artifact = AnalyticsArtifactModel.model_validate(payload)

    from archimedes.services.strategy_provider import default_provider
    provider = default_provider()
    strategies = provider.list_strategies()
    buy_hold = next(
        (s for s in strategies if "Buy-and-Hold" in s.paper_title or "Baseline" in s.paper_title),
        None,
    )
    if buy_hold is None:
        pytest.skip("Buy-and-Hold strategy not found")

    mapped, operation = map_artifact_to_backtest_result(
        artifact,
        strategy_id=buy_hold.id,
    )
    content_hash = canonical_artifact_hash(payload)

    with get_session() as session:
        insert_backtest_if_missing(
            session,
            strategy_id=buy_hold.id,
            content_hash=content_hash,
            result=mapped,
            run_id=artifact.run_id,
            operation=operation,
            artifact_json=FIXTURE_PATH.read_text(encoding="utf-8"),
        )
        session.commit()
    return buy_hold.id


class TestRootAndHealth:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Archimedes"
        assert "docs" in data

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "archimedes-backend"
        assert "status" in data


class TestStrategyRoutes:
    def test_list_strategies(self, client, seeded_db):
        resp = client.get("/api/strategies/")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategies" in data
        assert len(data["strategies"]) >= 1
        s = data["strategies"][0]
        assert "id" in s
        assert "paper_title" in s
        assert "sharpe_ratio" in s
        assert s["is_backtest_placeholder"] is False

    def test_get_strategy_signals(self, client):
        resp = client.get("/api/strategies/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategies" in data
        assert "strategy_count" in data

    def test_get_single_strategy(self, client, seeded_db):
        # Get the list first to find a valid ID
        list_resp = client.get("/api/strategies/")
        strategies = list_resp.json()["strategies"]
        if not strategies:
            pytest.skip("No strategies available")
        sid = strategies[0]["id"]

        resp = client.get(f"/api/strategies/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == sid


class TestRiskRoutes:
    def test_risk_profiles(self, client):
        resp = client.get("/api/risk/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "bands" in data
        assert len(data["bands"]) >= 4
        labels = [b["label"] for b in data["bands"]]
        assert "conservative" in labels
        assert "aggressive" in labels

    def test_portfolio_risk(self, client, seeded_db):
        resp = client.get("/api/risk/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategy_count" in data
        assert "avg_sharpe" in data
        assert "worst_max_dd" in data
        assert "actual_risk_profile" in data
        assert "strategies" in data


class TestSelectionBiasRoutes:
    def test_rigor_gate(self, client, seeded_db):
        resp = client.get("/api/selection-bias/gate")
        assert resp.status_code == 200
        data = resp.json()
        assert "strategies" in data
        assert "total" in data
        assert "passing" in data
        assert "failing" in data
        for s in data["strategies"]:
            assert "strategy_id" in s
            assert "passes_all" in s
            assert "gate_details" in s

    def test_rigor_gate_single_strategy(self, client, seeded_db):
        # Get a strategy ID from the full gate
        gate_resp = client.get("/api/selection-bias/gate")
        strategies = gate_resp.json()["strategies"]
        if not strategies:
            pytest.skip("No strategies in gate")
        sid = strategies[0]["strategy_id"]

        resp = client.get(f"/api/selection-bias/gate/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy_id"] == sid
        assert "passes_all" in data

    def test_rigor_gate_404(self, client):
        resp = client.get("/api/selection-bias/gate/nonexistent-id")
        assert resp.status_code == 404


class TestConfigRoutes:
    def test_contracts(self, client):
        # ConfigService reads contract addresses from chain_client.settings
        # which is initialized at import time — requires deeper mocking.
        # The /api/config/contracts endpoint is tested live on EC2.
        pytest.skip("Requires chain_client.settings module-level init mocking")


class TestAssetRoutes:
    def test_list_assets(self, client):
        # AssetService reads from on-chain via chain_client — requires deeper mocking.
        # The /api/assets/ endpoint is tested live on EC2.
        pytest.skip("Requires chain_client.settings module-level init mocking")


class TestRegimeRoutes:
    def test_current_regime(self, client):
        resp = client.get("/api/regime/current")
        assert resp.status_code == 200
        data = resp.json()
        assert "regime" in data
        assert "confidence" in data


class TestAgentRoutes:
    def test_agent_status(self, client):
        resp = client.get("/api/agent/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "alive" in data
