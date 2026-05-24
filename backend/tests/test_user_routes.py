"""Tests for user profile API — WelcomeProfileModal backend."""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from archimedes.models.user_profile import UserProfile
from archimedes.db import get_session


@pytest.fixture
def client():
    """Create a test client with a fresh in-memory DB."""
    from archimedes.models.chat import Base
    from archimedes.db import engine
    Base.metadata.create_all(bind=engine)
    from archimedes.main import app
    tc = TestClient(app)
    yield tc


class TestUserProfileRoutes:
    """GET and POST /api/user/profile."""

    def test_get_profile_returns_404_for_unknown_wallet(self, client):
        """Unknown wallet should return 404."""
        res = client.get("/api/user/profile/0x0000000000000000000000000000000000000001")
        assert res.status_code == 404

    def test_create_profile_with_display_name(self, client):
        """POST creates a profile and returns it."""
        wallet = "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        res = client.post("/api/user/profile", json={
            "wallet_address": wallet,
            "display_name": "Alice",
            "marketing_opt_in": False,
        })
        assert res.status_code == 200
        data = res.json()
        assert data["display_name"] == "Alice"
        assert data["wallet_address"] == wallet.lower()

    def test_get_profile_after_create(self, client):
        """GET returns the profile after POST creates it."""
        wallet = "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        client.post("/api/user/profile", json={
            "wallet_address": wallet,
            "display_name": "Bob",
        })
        res = client.get(f"/api/user/profile/{wallet}")
        assert res.status_code == 200
        assert res.json()["display_name"] == "Bob"

    def test_create_profile_with_all_fields(self, client):
        """POST with every field populated."""
        wallet = "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        res = client.post("/api/user/profile", json={
            "wallet_address": wallet,
            "display_name": "Charlie",
            "email": "charlie@example.com",
            "interests": ["Equities", "Crypto"],
            "attribution": "Twitter",
            "marketing_opt_in": True,
        })
        assert res.status_code == 200
        data = res.json()
        assert data["display_name"] == "Charlie"
        assert data["email"] == "charlie@example.com"
        assert data["interests"] == ["Equities", "Crypto"]
        assert data["attribution"] == "Twitter"
        assert data["marketing_opt_in"] is True

    def test_update_existing_profile(self, client):
        """POST to an existing profile updates fields."""
        wallet = "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        client.post("/api/user/profile", json={
            "wallet_address": wallet,
            "display_name": "Original",
        })
        res = client.post("/api/user/profile", json={
            "wallet_address": wallet,
            "display_name": "Updated",
            "marketing_opt_in": True,
        })
        assert res.status_code == 200
        assert res.json()["display_name"] == "Updated"
        assert res.json()["marketing_opt_in"] is True

    def test_create_profile_minimal_fields(self, client):
        """POST with only wallet address (all optional fields null)."""
        wallet = "0x0000000000000000000000000000000000000002"
        res = client.post("/api/user/profile", json={
            "wallet_address": wallet,
        })
        assert res.status_code == 200
        data = res.json()
        assert data["display_name"] is None
        assert data["email"] is None
        assert data["marketing_opt_in"] is False

    def test_invalid_wallet_address_rejected(self, client):
        """POST with invalid wallet address returns validation error."""
        res = client.post("/api/user/profile", json={
            "wallet_address": "not-a-wallet",
            "display_name": "Test",
        })
        assert res.status_code == 422

    def test_get_profile_case_insensitive(self, client):
        """GET finds profile regardless of wallet case."""
        wallet = "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
        client.post("/api/user/profile", json={
            "wallet_address": wallet,
            "display_name": "CaseTest",
        })
        # Query with lowercase
        res = client.get(f"/api/user/profile/{wallet.lower()}")
        assert res.status_code == 200
        assert res.json()["display_name"] == "CaseTest"
        # Query with original mixed case
        res2 = client.get(f"/api/user/profile/{wallet}")
        assert res2.status_code == 200
