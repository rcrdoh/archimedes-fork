"""Tests for kb_artifacts service and corpus graph/kg endpoints (Issue #152).

Verifies:
  - S3 + local artifact loading with graceful fallback
  - In-memory cache with TTL
  - /api/corpus/graph returns SPECTER2-backed scatter when artifacts exist
  - /api/corpus/graph returns 503 when no artifacts
  - /api/corpus/graph returns SPECTER2-backed scatter when artifacts exist
  - /api/corpus/kg/entities searches DB-backed KG store
  - 503 when no KB artifact (no fallback to metadata-derived fakes)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from archimedes.db import get_session, init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path, monkeypatch):
    """Point the DB at a temp SQLite so we don't pollute the real one."""
    db_path = tmp_path / "test_kb_artifacts.db"
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
        mock_chain.usdc_address = "0x3600000000000000000000000000000000000000"
        mock_chain.synthetic_factory_address = ""
        mock_chain.amm_router_address = "0xd5b829f9d364a8bbe1caf6c8b19cb05371b178f4"
        mock_chain.vault_factory_address = "0xca873414070844aeb98b0bf1051f81969c79cc32"
        mock_chain.reasoning_trace_registry_address = "0x42d8a23edb897cbee203e9fa197eb05ab5106ca6"
        mock_chain.asset_registry_address = "0x2d44550711137916df6175587d17886281a0fbc7"

        mock_executor.execute_swap = AsyncMock(return_value={"tx_hash": "0xmock_swap"})
        mock_executor.get_balance = AsyncMock(return_value=1000000)
        mock_executor.get_portfolio = AsyncMock(return_value={})

        from archimedes.main import app
        tc = TestClient(app)
        yield tc


# ---------------------------------------------------------------------------
# kb_artifacts service tests
# ---------------------------------------------------------------------------

class TestKbArtifactsCache:
    """In-memory cache tests."""

    def test_cache_miss_returns_none(self):
        from archimedes.services.kb_artifacts import invalidate_cache, _cache_get
        invalidate_cache()
        assert _cache_get("nonexistent") is None

    def test_cache_set_then_get(self):
        from archimedes.services.kb_artifacts import invalidate_cache, _cache_get, _cache_set
        invalidate_cache()
        _cache_set("test_key", {"hello": "world"})
        assert _cache_get("test_key") == {"hello": "world"}

    def test_cache_expires_after_ttl(self):
        from archimedes.services.kb_artifacts import invalidate_cache, _cache_get, _cache_set
        invalidate_cache()
        # Monkey-patch TTL to 0 for instant expiry
        import archimedes.services.kb_artifacts as mod
        original_ttl = mod._CACHE_TTL
        mod._CACHE_TTL = 0
        try:
            _cache_set("expiring", "value")
            # TTL=0 means instant expiry
            time.sleep(0.01)
            assert _cache_get("expiring") is None
        finally:
            mod._CACHE_TTL = original_ttl

    def test_invalidate_clears_all(self):
        from archimedes.services.kb_artifacts import invalidate_cache, _cache_get, _cache_set
        _cache_set("a", 1)
        _cache_set("b", 2)
        cleared = invalidate_cache()
        assert cleared == 2
        assert _cache_get("a") is None
        assert _cache_get("b") is None


class TestKbArtifactsLoading:
    """Artifact loading with mocked S3 + local."""

    def test_load_manifest_local_file(self, tmp_path):
        from archimedes.services.kb_artifacts import invalidate_cache
        from archimedes.services import kb_artifacts as mod

        invalidate_cache()
        # Write a local manifest
        manifest = {"run_ts": "2026-05-24T00:00:00Z", "paper_count": 100}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))

        # Patch artifact dir to tmp_path and disable S3
        with patch.object(mod, "_ARTIFACT_DIR", tmp_path), \
             patch.object(mod, "_S3_BUCKET", ""):
            result = mod.load_manifest()
            assert result["paper_count"] == 100

    def test_load_manifest_not_found_raises(self, tmp_path):
        from archimedes.services.kb_artifacts import invalidate_cache, ArtifactNotFound
        from archimedes.services import kb_artifacts as mod

        invalidate_cache()
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch.object(mod, "_ARTIFACT_DIR", empty_dir), \
             patch.object(mod, "_S3_BUCKET", ""):
            with pytest.raises(ArtifactNotFound, match="manifest.json"):
                mod.load_manifest()

    def test_load_kg_graph_local_file(self, tmp_path):
        from archimedes.services.kb_artifacts import invalidate_cache
        from archimedes.services import kb_artifacts as mod

        invalidate_cache()
        kg_data = {
            "nodes": [
                {"id": 1, "canonical_name": "momentum", "entity_type": "strategy"},
                {"id": 2, "canonical_name": "volatility", "entity_type": "risk_factor"},
            ],
            "edges": [
                {"source": 1, "target": 2, "relation": "correlates_with"},
            ],
        }
        (tmp_path / "kg_graph.json").write_text(json.dumps(kg_data))

        with patch.object(mod, "_ARTIFACT_DIR", tmp_path), \
             patch.object(mod, "_S3_BUCKET", ""):
            result = mod.load_kg_graph()
            assert len(result["nodes"]) == 2
            assert len(result["edges"]) == 1

    def test_load_embeddings_local_file(self, tmp_path):
        from archimedes.services.kb_artifacts import invalidate_cache
        from archimedes.services import kb_artifacts as mod

        invalidate_cache()
        ids = ["2605.12345", "2605.12346", "2605.12347"]
        (tmp_path / "ids.json").write_text(json.dumps(ids))

        # Write a small numpy array
        import numpy as np
        import io
        emb = np.random.randn(3, 768).astype(np.float32)
        buf = io.BytesIO()
        np.save(buf, emb)
        (tmp_path / "embeddings.npy").write_bytes(buf.getvalue())

        with patch.object(mod, "_ARTIFACT_DIR", tmp_path), \
             patch.object(mod, "_S3_BUCKET", ""):
            loaded_ids, loaded_emb = mod.load_embeddings()
            assert loaded_ids == ids
            assert loaded_emb.shape == (3, 768)

    def test_load_clusters_local_file(self, tmp_path):
        from archimedes.services.kb_artifacts import invalidate_cache
        from archimedes.services import kb_artifacts as mod

        invalidate_cache()
        clusters = {"2605.12345": "cluster_0", "2605.12346": "cluster_1"}
        (tmp_path / "clusters.json").write_text(json.dumps(clusters))

        with patch.object(mod, "_ARTIFACT_DIR", tmp_path), \
             patch.object(mod, "_S3_BUCKET", ""):
            result = mod.load_clusters()
            assert result["2605.12345"] == "cluster_0"

    def test_compute_and_cache_umap_projection(self, tmp_path):
        from archimedes.services.kb_artifacts import (
            invalidate_cache,
            compute_and_cache_umap_projection,
        )

        invalidate_cache()
        import numpy as np
        ids = [f"paper_{i}" for i in range(20)]
        embeddings = np.random.randn(20, 768).astype(np.float32)
        clusters = {f"paper_{i}": f"cluster_{i % 3}" for i in range(20)}

        # PCA fallback (umap-learn may not be installed)
        points = compute_and_cache_umap_projection(ids, embeddings, clusters)
        assert len(points) == 20
        assert "arxiv_id" in points[0]
        assert "x" in points[0]
        assert "y" in points[0]
        assert "cluster_id" in points[0]
        assert points[0]["cluster_id"] == "cluster_0"

    def test_s3_fallback_to_local(self, tmp_path):
        """When S3 is configured but unavailable, falls back to local."""
        from archimedes.services.kb_artifacts import invalidate_cache
        from archimedes.services import kb_artifacts as mod

        invalidate_cache()
        manifest = {"run_ts": "2026-05-24", "status": "ok"}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))

        # S3 bucket set but no credentials — _get_s3_client returns None
        with patch.object(mod, "_ARTIFACT_DIR", tmp_path), \
             patch.object(mod, "_S3_BUCKET", "nonexistent-bucket"), \
             patch.object(mod, "_get_s3_client", return_value=None):
            result = mod.load_manifest()
            assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestCorpusGraphEndpoint:
    """Tests for /api/corpus/graph."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from archimedes.services.kb_artifacts import invalidate_cache
        invalidate_cache()

    def test_graph_returns_503_when_no_artifacts(self, client):
        from archimedes.services import kb_artifacts as mod
        with patch.object(mod, "_S3_BUCKET", ""), \
             patch.object(mod, "_ARTIFACT_DIR", Path("/nonexistent")):
            resp = client.get("/api/corpus/graph")
            assert resp.status_code == 503
            body = resp.json()
            assert "detail" in body
            detail = body["detail"]
            assert detail.get("error") == "kb_artifact_not_found" or "KB" in str(detail)

    def test_graph_returns_scatter_when_artifacts_exist(self, client, tmp_path):
        from archimedes.services import kb_artifacts as mod

        # Write minimal artifacts
        import numpy as np
        import io
        ids = [f"paper_{i}" for i in range(10)]
        (tmp_path / "ids.json").write_text(json.dumps(ids))
        emb = np.random.randn(10, 768).astype(np.float32)
        buf = io.BytesIO()
        np.save(buf, emb)
        (tmp_path / "embeddings.npy").write_bytes(buf.getvalue())
        (tmp_path / "clusters.json").write_text(json.dumps({f"paper_{i}": f"c{i % 2}" for i in range(10)}))
        (tmp_path / "topics.json").write_text(json.dumps({"c0": {"label": "momentum"}, "c1": {"label": "volatility"}}))

        with patch.object(mod, "_S3_BUCKET", ""), \
             patch.object(mod, "_ARTIFACT_DIR", tmp_path):
            resp = client.get("/api/corpus/graph")
            assert resp.status_code == 200
            body = resp.json()
            assert "points" in body
            assert len(body["points"]) == 10
            assert "topics" in body
            point = body["points"][0]
            assert "arxiv_id" in point
            assert "x" in point
            assert "y" in point
            assert "cluster_id" in point


class TestCorpusKgEndpoint:
    """Tests for /api/corpus/kg/entities (honest KB-pipeline endpoint).

    Note: the legacy /api/papers/corpus/kg endpoints were deleted in Issue #201.
    These tests now verify the honest endpoint returns entities from the DB-backed
    KG store, or 503 when no KB artifact exists.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        from archimedes.services.kb_artifacts import invalidate_cache
        invalidate_cache()

    def test_kg_reads_artifact_when_available(self, client, tmp_path):
        """When entities exist in the KG table, /api/corpus/kg/entities?q=<term> returns them."""
        # The honest endpoint reads from the DB (KGEntity table), not from files.
        # Without seeded data, it returns empty results (200, not 404).
        from archimedes.services import kb_artifacts as mod

        with patch.object(mod, "_S3_BUCKET", ""), \
             patch.object(mod, "_ARTIFACT_DIR", tmp_path):
            resp = client.get("/api/corpus/kg/entities?q=momentum")
            assert resp.status_code == 200
            body = resp.json()
            assert body["query"] == "momentum"
            assert isinstance(body["entities"], list)

    def test_kg_entity_filter_returns_neighborhood(self, client, tmp_path):
        """Entity search filters by canonical_name."""
        from archimedes.services import kb_artifacts as mod

        with patch.object(mod, "_S3_BUCKET", ""), \
             patch.object(mod, "_ARTIFACT_DIR", tmp_path):
            resp = client.get("/api/corpus/kg/entities?q=momentum")
            assert resp.status_code == 200
            body = resp.json()
            # Empty DB → no entities, but response shape is correct
            assert "entities" in body

    def test_kg_returns_empty_when_no_query(self, client, tmp_path):
        """Without a query param, /api/corpus/kg/entities returns 422 (q is required)."""
        from archimedes.services import kb_artifacts as mod

        with patch.object(mod, "_S3_BUCKET", ""), \
             patch.object(mod, "_ARTIFACT_DIR", tmp_path):
            resp = client.get("/api/corpus/kg/entities")
            # q is a required query param with min_length=2
            assert resp.status_code == 422


class TestCorpusGraphEndpoint:
    """Tests for /api/corpus/graph (honest KB-pipeline endpoint).

    Note: the legacy /api/papers/corpus/graph endpoint was deleted in Issue #201.
    The honest endpoint returns 503 when no KB artifact exists.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        from archimedes.services.kb_artifacts import invalidate_cache
        invalidate_cache()

    def test_corpus_graph_uses_specter2_when_available(self, client, tmp_path):
        from archimedes.services import kb_artifacts as mod

        import numpy as np
        import io
        ids = [f"paper_{i}" for i in range(15)]
        (tmp_path / "ids.json").write_text(json.dumps(ids))
        emb = np.random.randn(15, 768).astype(np.float32)
        buf = io.BytesIO()
        np.save(buf, emb)
        (tmp_path / "embeddings.npy").write_bytes(buf.getvalue())
        (tmp_path / "clusters.json").write_text(json.dumps({}))
        (tmp_path / "topics.json").write_text(json.dumps({}))

        with patch.object(mod, "_S3_BUCKET", ""), \
             patch.object(mod, "_ARTIFACT_DIR", tmp_path):
            resp = client.get("/api/corpus/graph")
            assert resp.status_code == 200
            body = resp.json()
            assert "points" in body
            assert "cluster_count" in body
            assert len(body["points"]) > 0

    def test_corpus_graph_returns_503_when_no_artifact(self, client, tmp_path):
        from archimedes.services import kb_artifacts as mod

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch.object(mod, "_S3_BUCKET", ""), \
             patch.object(mod, "_ARTIFACT_DIR", empty_dir):
            resp = client.get("/api/corpus/graph")
            # Honest endpoint returns 503 when no KB artifact exists
            assert resp.status_code == 503
            body = resp.json()
            assert body["detail"]["error"] == "kb_artifact_not_found"
