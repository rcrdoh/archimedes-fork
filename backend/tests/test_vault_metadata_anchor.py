"""Tests for strategy passport on-chain anchoring via POST /api/vaults/metadata.

Validates that store_vault_metadata triggers strategy_publisher.anchor()
for each strategy_id, handles missing passports/hashes gracefully, and
survives anchor failures without breaking the DB write.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from archimedes.main import app

client = TestClient(app)


def _make_passport(sid: str, methodology_hash: str | None = "abcd1234" * 8):
    """Build a mock passport with the fields anchor() needs."""
    mock = MagicMock()
    mock.id = sid
    mock.methodology_hash = methodology_hash
    mock.regime_tag = "bull"
    paper = MagicMock()
    paper.arxiv_id = f"2301.{sid}"
    mock.papers = [paper]
    return mock


class TestVaultMetadataAnchor:
    @patch("archimedes.api.vaults_routes.strategy_publisher")
    @patch("archimedes.api.vaults_routes.strategy_provider")
    def test_metadata_post_calls_anchor_once_per_strategy_id(self, mock_provider, mock_publisher):
        mock_provider.get_strategy.side_effect = lambda sid: _make_passport(sid)
        mock_publisher.anchor = AsyncMock()

        resp = client.post("/api/vaults/metadata", json={
            "vault_address": "0x" + "ab" * 20,
            "name": "Test Vault",
            "symbol": "tVLT",
            "strategy_ids": ["s1", "s2", "s3"],
        })
        assert resp.status_code == 200

        # Give the fire-and-forget task time to execute
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))

        assert mock_publisher.anchor.call_count == 3

    @patch("archimedes.api.vaults_routes.strategy_publisher")
    @patch("archimedes.api.vaults_routes.strategy_provider")
    def test_metadata_post_skips_passports_without_methodology_hash(self, mock_provider, mock_publisher):
        def get_strat(sid):
            if sid == "s2":
                return _make_passport(sid, methodology_hash=None)
            return _make_passport(sid)

        mock_provider.get_strategy.side_effect = get_strat
        mock_publisher.anchor = AsyncMock()

        resp = client.post("/api/vaults/metadata", json={
            "vault_address": "0x" + "cd" * 20,
            "name": "Test Vault 2",
            "symbol": "tVL2",
            "strategy_ids": ["s1", "s2", "s3"],
        })
        assert resp.status_code == 200

        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))
        # s2 skipped due to no methodology_hash
        assert mock_publisher.anchor.call_count == 2

    @patch("archimedes.api.vaults_routes.strategy_publisher")
    @patch("archimedes.api.vaults_routes.strategy_provider")
    def test_metadata_post_succeeds_when_anchor_raises(self, mock_provider, mock_publisher):
        mock_provider.get_strategy.side_effect = lambda sid: _make_passport(sid)
        mock_publisher.anchor = AsyncMock(side_effect=RuntimeError("simulated chain failure"))

        resp = client.post("/api/vaults/metadata", json={
            "vault_address": "0x" + "ef" * 20,
            "name": "Test Vault 3",
            "symbol": "tVL3",
            "strategy_ids": ["s1"],
        })
        # Handler still returns 200 — anchor failure is non-fatal
        assert resp.status_code == 200

    @patch("archimedes.api.vaults_routes.strategy_publisher")
    @patch("archimedes.api.vaults_routes.strategy_provider")
    def test_metadata_post_with_unknown_strategy_id_does_not_crash(self, mock_provider, mock_publisher):
        mock_provider.get_strategy.return_value = None
        mock_publisher.anchor = AsyncMock()

        resp = client.post("/api/vaults/metadata", json={
            "vault_address": "0x" + "11" * 20,
            "name": "Test Vault 4",
            "symbol": "tVL4",
            "strategy_ids": ["unknown_id"],
        })
        assert resp.status_code == 200

        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))
        # anchor should NOT have been called for unknown strategy
        mock_publisher.anchor.assert_not_called()
