"""Route-level tests for chat identity binding — issue #524 (audit #28).

POST /api/vaults/{address}/chat used to trust the body-supplied
wallet_address outright. The hybrid model under test:

  - Valid SIWE session  → message attributed to the session wallet,
    stored/returned with verified=True; a contradicting body wallet → 403.
  - No session          → post still accepted (open chat), but explicitly
    verified=False so attribution is never silently trusted.

Hermetic: uses the shared SQLAlchemy engine (sqlite fallback, no Postgres /
Redis / Anthropic). SIWE sessions are real signed cookies via the
`_siwe_cookies` precedent from test_user_routes.py — no header spoofing.
"""

from __future__ import annotations

import time

import pytest
from archimedes.api.auth_siwe import _COOKIE_NAME, _sign_session
from fastapi.testclient import TestClient

# Distinct vaults per test so message assertions don't bleed across tests
# sharing the same sqlite file.
_VAULT_SESSION = "0x00000000000000000000000000000000000005aa"
_VAULT_MISMATCH = "0x00000000000000000000000000000000000005ab"
_VAULT_ANON = "0x00000000000000000000000000000000000005ac"
_VAULT_READ = "0x00000000000000000000000000000000000005ad"

_W_SESSION = "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"  # checksum-case on purpose
_W_OTHER = "0x9999999999999999999999999999999999999999"
_W_BODY = "0x7777777777777777777777777777777777777777"


def _siwe_cookies(wallet: str) -> dict[str, str]:
    """Build a valid SIWE session cookie for `wallet` (test_user_routes precedent)."""
    return {_COOKIE_NAME: _sign_session(wallet, time.time())}


@pytest.fixture
def client():
    """Test client with tables created on the shared (sqlite) engine."""
    from archimedes.db import engine
    from archimedes.models.chat import Base

    Base.metadata.create_all(bind=engine)

    from archimedes.main import app

    return TestClient(app)


class TestSiweBoundIdentity:
    """(a) Session present → attribution comes from the session, verified=True."""

    def test_session_wallet_wins_and_marks_verified(self, client):
        res = client.post(
            f"/api/vaults/{_VAULT_SESSION}/chat",
            json={"message": "posting with a session, no body wallet"},
            cookies=_siwe_cookies(_W_SESSION),
        )
        assert res.status_code == 200, res.text
        msg = res.json()["message"]
        assert msg["wallet_address"] == _W_SESSION.lower()
        assert msg["verified"] is True

    def test_matching_body_wallet_is_accepted(self, client):
        """A body wallet that agrees with the session (any case) is fine."""
        res = client.post(
            f"/api/vaults/{_VAULT_SESSION}/chat",
            json={"wallet_address": _W_SESSION, "message": "body matches session"},
            cookies=_siwe_cookies(_W_SESSION),
        )
        assert res.status_code == 200, res.text
        msg = res.json()["message"]
        assert msg["wallet_address"] == _W_SESSION.lower()
        assert msg["verified"] is True


class TestMismatchRejected:
    """(b) Session present + contradicting body wallet → 403, nothing stored."""

    def test_mismatched_body_wallet_403(self, client):
        before = client.get(f"/api/vaults/{_VAULT_MISMATCH}/chat/count").json()["message_count"]
        res = client.post(
            f"/api/vaults/{_VAULT_MISMATCH}/chat",
            json={"wallet_address": _W_OTHER, "message": "impersonation attempt"},
            cookies=_siwe_cookies(_W_SESSION),
        )
        assert res.status_code == 403
        assert "SIWE" in res.json()["detail"]
        after = client.get(f"/api/vaults/{_VAULT_MISMATCH}/chat/count").json()["message_count"]
        assert after == before  # rejected post must not be persisted


class TestAnonymousUnverified:
    """(c) No session → accepted (open chat) but explicitly verified=False."""

    def test_no_session_accepted_as_unverified(self, client):
        res = client.post(
            f"/api/vaults/{_VAULT_ANON}/chat",
            json={"wallet_address": _W_BODY, "message": "anonymous post"},
        )
        assert res.status_code == 200, res.text
        msg = res.json()["message"]
        assert msg["wallet_address"] == _W_BODY.lower()
        assert msg["verified"] is False

    def test_no_session_no_wallet_still_422(self, client):
        """Without a session the body wallet remains required + regex-validated."""
        res = client.post(f"/api/vaults/{_VAULT_ANON}/chat", json={"message": "who am I?"})
        assert res.status_code == 422

        res = client.post(
            f"/api/vaults/{_VAULT_ANON}/chat",
            json={"wallet_address": "garbage", "message": "still no"},
        )
        assert res.status_code == 422


class TestReadEndpointsRegression:
    """(d) Existing read endpoints keep working and surface the verified flag."""

    def test_list_and_count_surface_verified(self, client):
        # Delta-based, message-specific assertions — the shared sqlite engine
        # (sqlite:///./archimedes_chat.db) persists rows across runs, so an
        # absolute `total == 2` is brittle on re-run. Mirror the before/after
        # pattern used in TestMismatchRejected above.
        before = client.get(f"/api/vaults/{_VAULT_READ}/chat/count").json()["message_count"]

        client.post(
            f"/api/vaults/{_VAULT_READ}/chat",
            json={"message": "verified one"},
            cookies=_siwe_cookies(_W_SESSION),
        )
        client.post(
            f"/api/vaults/{_VAULT_READ}/chat",
            json={"wallet_address": _W_BODY, "message": "unverified one"},
        )

        res = client.get(f"/api/vaults/{_VAULT_READ}/chat")
        assert res.status_code == 200
        data = res.json()
        by_text = {m["message"]: m for m in data["messages"]}
        assert by_text["verified one"]["verified"] is True
        assert by_text["verified one"]["wallet_address"] == _W_SESSION.lower()
        assert by_text["unverified one"]["verified"] is False
        assert by_text["unverified one"]["wallet_address"] == _W_BODY.lower()

        count = client.get(f"/api/vaults/{_VAULT_READ}/chat/count")
        assert count.status_code == 200
        assert count.json()["message_count"] == before + 2


_VAULT_AI = "0x00000000000000000000000000000000000005ae"


class TestArchimedesMentionBudgetGate:
    """Audit 2026-06-14: an @archimedes mention triggers a paid Claude
    completion. That AI-triggering branch is gated behind the same
    REQUIRE_SIWE_FOR_GENERATION flag as the generation endpoints — default OFF
    keeps chat open; ON requires a verified session to spend tokens.

    The AI generator is stubbed so the "allowed" paths stay hermetic (no real
    Anthropic call); the 401 path fires before post_message is even reached.
    """

    @pytest.fixture(autouse=True)
    def _stub_ai(self, monkeypatch):
        from archimedes.services.chat_service import chat_service

        monkeypatch.setattr(chat_service, "_generate_ai_response", lambda *a, **k: None)

    def test_mention_blocked_without_session_when_flag_on(self, client, monkeypatch):
        monkeypatch.setenv("REQUIRE_SIWE_FOR_GENERATION", "true")
        res = client.post(
            f"/api/vaults/{_VAULT_AI}/chat",
            json={"wallet_address": _W_BODY, "message": "hey @archimedes rebalance me"},
        )
        assert res.status_code == 401, res.text
        assert "sign in" in res.json()["detail"].lower()

    def test_mention_allowed_with_session_when_flag_on(self, client, monkeypatch):
        monkeypatch.setenv("REQUIRE_SIWE_FOR_GENERATION", "true")
        res = client.post(
            f"/api/vaults/{_VAULT_AI}/chat",
            json={"message": "@archimedes status please"},
            cookies=_siwe_cookies(_W_SESSION),
        )
        assert res.status_code == 200, res.text

    def test_mention_open_when_flag_off(self, client, monkeypatch):
        monkeypatch.delenv("REQUIRE_SIWE_FOR_GENERATION", raising=False)
        res = client.post(
            f"/api/vaults/{_VAULT_AI}/chat",
            json={"wallet_address": _W_BODY, "message": "@archimedes hello (open mode)"},
        )
        assert res.status_code == 200, res.text

    def test_non_mention_never_gated_even_when_flag_on(self, client, monkeypatch):
        monkeypatch.setenv("REQUIRE_SIWE_FOR_GENERATION", "true")
        res = client.post(
            f"/api/vaults/{_VAULT_AI}/chat",
            json={"wallet_address": _W_BODY, "message": "just chatting, no mention"},
        )
        assert res.status_code == 200, res.text
