"""Tests for SIWE (Sign-In with Ethereum) session authentication.

Target: backend/archimedes/api/auth_siwe.py
Goal: ≥85% coverage on the target module.

Hermetic: no .env, no Redis, no Postgres, no network. All external deps mocked.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest
from archimedes.api.auth_siwe import (
    _COOKIE_NAME,
    _NONCE_TTL_SECONDS,
    _SESSION_TTL_SECONDS,
    _pending_nonces,
    _sign_session,
    _verify_session,
    get_verified_wallet,
    require_verified_wallet,
)
from httpx import ASGITransport, AsyncClient

# ── Unit tests for session token functions ─────────────────────


class TestSignSession:
    def test_produces_pipe_separated_token(self):
        token = _sign_session("0xabc", time.time())
        assert "|" in token
        payload_str, sig = token.rsplit("|", 1)
        payload = json.loads(payload_str)
        assert payload["wallet"] == "0xabc"
        assert "iat" in payload
        assert len(sig) == 64  # SHA-256 hex

    def test_lowercases_wallet(self):
        token = _sign_session("0xABC", time.time())
        payload = json.loads(token.rsplit("|", 1)[0])
        assert payload["wallet"] == "0xabc"

    def test_different_wallets_different_tokens(self):
        now = time.time()
        t1 = _sign_session("0xaaa", now)
        t2 = _sign_session("0xbbb", now)
        assert t1 != t2


class TestVerifySession:
    def test_valid_token_returns_wallet(self):
        token = _sign_session("0xdef", time.time())
        assert _verify_session(token) == "0xdef"

    def test_tampered_payload_returns_none(self):
        token = _sign_session("0xdef", time.time())
        # Tamper with the payload
        payload_str, sig = token.rsplit("|", 1)
        tampered = payload_str.replace("0xdef", "0xevil")
        assert _verify_session(f"{tampered}|{sig}") is None

    def test_tampered_signature_returns_none(self):
        token = _sign_session("0xdef", time.time())
        payload_str, _ = token.rsplit("|", 1)
        assert _verify_session(f"{payload_str}|{'0' * 64}") is None

    def test_expired_token_returns_none(self):
        old_time = time.time() - _SESSION_TTL_SECONDS - 1
        token = _sign_session("0xdef", old_time)
        assert _verify_session(token) is None

    def test_garbage_token_returns_none(self):
        assert _verify_session("not-a-token") is None
        assert _verify_session("") is None
        assert _verify_session("a|b|c") is None

    def test_just_expired_returns_none(self):
        # Token issued exactly at the TTL boundary
        boundary = time.time() - _SESSION_TTL_SECONDS - 0.001
        token = _sign_session("0xdef", boundary)
        assert _verify_session(token) is None

    def test_fresh_token_returns_wallet(self):
        token = _sign_session("0xdef", time.time() - 60)  # 1 min ago
        assert _verify_session(token) == "0xdef"


# ── Unit tests for request-level functions ─────────────────────


class TestGetVerifiedWallet:
    def test_returns_none_without_cookie(self):
        request = MagicMock()
        request.cookies = {}
        assert get_verified_wallet(request) is None

    def test_returns_wallet_with_valid_cookie(self):
        token = _sign_session("0x1234", time.time())
        request = MagicMock()
        request.cookies = {_COOKIE_NAME: token}
        assert get_verified_wallet(request) == "0x1234"

    def test_returns_none_with_invalid_cookie(self):
        request = MagicMock()
        request.cookies = {_COOKIE_NAME: "garbage"}
        assert get_verified_wallet(request) is None


class TestRequireVerifiedWallet:
    def test_raises_401_without_session(self):
        request = MagicMock()
        request.cookies = {}
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            require_verified_wallet(request)
        assert exc_info.value.status_code == 401

    def test_returns_wallet_with_valid_session(self):
        token = _sign_session("0xabcd", time.time())
        request = MagicMock()
        request.cookies = {_COOKIE_NAME: token}
        assert require_verified_wallet(request) == "0xabcd"


# ── Endpoint integration tests ─────────────────────────────────


@pytest.mark.asyncio
async def test_nonce_endpoint_returns_nonce():
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/auth/nonce")
    assert resp.status_code == 200
    data = resp.json()
    assert "nonce" in data
    assert len(data["nonce"]) == 32  # 16 bytes hex
    assert "domain" in data
    assert data["expiry_seconds"] == _NONCE_TTL_SECONDS


@pytest.mark.asyncio
async def test_session_endpoint_unauthenticated():
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/auth/session")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is False
    assert data["wallet"] is None


@pytest.mark.asyncio
async def test_session_endpoint_authenticated():
    from archimedes.main import app

    token = _sign_session("0xdeadbeef" + "0" * 32, time.time())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/auth/session", cookies={_COOKIE_NAME: token})
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is True
    assert data["wallet"] == "0xdeadbeef" + "0" * 32


@pytest.mark.asyncio
async def test_logout_clears_cookie():
    from archimedes.main import app

    token = _sign_session("0xdeadbeef" + "0" * 32, time.time())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/auth/logout", cookies={_COOKIE_NAME: token})
    assert resp.status_code == 200
    assert resp.json()["status"] == "logged_out"
    # Cookie should be deleted (set to empty or max_age=0)
    cookie_header = resp.headers.get("set-cookie", "")
    assert _COOKIE_NAME in cookie_header


@pytest.mark.asyncio
async def test_verify_rejects_missing_fields():
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/auth/verify", json={"message": "", "signature": ""})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_verify_rejects_unknown_nonce():
    from archimedes.main import app

    message = "archimedes-arc.app wants you to sign in\n0xabcdef1234567890abcdef1234567890abcdef12\nNonce: nonexistentnonce12345678"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/auth/verify", json={"message": message, "signature": "0xfake"})
    assert resp.status_code == 401
    assert "Nonce" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_verify_rejects_expired_nonce():
    from archimedes.main import app

    # Plant an expired nonce
    nonce = "expired_nonce_123456"
    _pending_nonces[nonce] = time.time() - 1  # already expired

    message = f"archimedes-arc.app wants you to sign in\n0xabcdef1234567890abcdef1234567890abcdef12\nNonce: {nonce}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/auth/verify", json={"message": message, "signature": "0xfake"})
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_verify_with_valid_signature():
    """Full SIWE flow: nonce → sign → verify → session cookie."""
    from archimedes.main import app
    from eth_account import Account
    from eth_account.messages import encode_defunct

    # Create a test wallet
    acct = Account.create()
    wallet = acct.address.lower()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Step 1: Get nonce
        nonce_resp = await client.get("/api/auth/nonce")
        assert nonce_resp.status_code == 200
        nonce_data = nonce_resp.json()

        # Step 2: Construct and sign SIWE message
        message = (
            f"{nonce_data['domain']} wants you to sign in with your Ethereum account:\n"
            f"{wallet}\n\n"
            f"Sign in to Archimedes.\n\n"
            f"URI: https://{nonce_data['domain']}\n"
            f"Version: 1\n"
            f"Chain ID: 5042002\n"
            f"Nonce: {nonce_data['nonce']}\n"
            f"Issued At: 2026-05-26T00:00:00Z"
        )
        signable = encode_defunct(text=message)
        signed = acct.sign_message(signable)

        # Step 3: Verify
        verify_resp = await client.post(
            "/api/auth/verify",
            json={"message": message, "signature": signed.signature.hex()},
        )
        assert verify_resp.status_code == 200
        data = verify_resp.json()
        assert data["status"] == "authenticated"
        assert data["wallet"] == wallet
        assert data["expires_in"] == _SESSION_TTL_SECONDS

        # Step 4: Session cookie should be set
        cookie_header = verify_resp.headers.get("set-cookie", "")
        assert _COOKIE_NAME in cookie_header
        assert "httponly" in cookie_header.lower()
        assert "samesite=strict" in cookie_header.lower()


@pytest.mark.asyncio
async def test_verify_rejects_wrong_signer():
    """Signature from wallet A cannot authenticate as wallet B."""
    from archimedes.main import app
    from eth_account import Account
    from eth_account.messages import encode_defunct

    acct_real = Account.create()
    acct_fake = "0x" + "1" * 40  # claimed wallet (not the signer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        nonce_resp = await client.get("/api/auth/nonce")
        nonce_data = nonce_resp.json()

        # Message claims acct_fake but signed by acct_real
        message = (
            f"{nonce_data['domain']} wants you to sign in with your Ethereum account:\n"
            f"{acct_fake}\n\n"
            f"Nonce: {nonce_data['nonce']}\n"
            f"Issued At: 2026-05-26T00:00:00Z"
        )
        signable = encode_defunct(text=message)
        signed = acct_real.sign_message(signable)

        verify_resp = await client.post(
            "/api/auth/verify",
            json={"message": message, "signature": signed.signature.hex()},
        )
        assert verify_resp.status_code == 401
        assert "does not match" in verify_resp.json()["detail"]


@pytest.mark.asyncio
async def test_nonce_is_single_use():
    """A nonce consumed by one verify attempt cannot be reused."""
    from archimedes.main import app
    from eth_account import Account
    from eth_account.messages import encode_defunct

    acct = Account.create()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        nonce_resp = await client.get("/api/auth/nonce")
        nonce_data = nonce_resp.json()

        message = (
            f"{nonce_data['domain']} wants you to sign in with your Ethereum account:\n"
            f"{acct.address.lower()}\n\n"
            f"Nonce: {nonce_data['nonce']}\n"
            f"Issued At: 2026-05-26T00:00:00Z"
        )
        signable = encode_defunct(text=message)
        signed = acct.sign_message(signable)
        payload = {"message": message, "signature": signed.signature.hex()}

        # First verify: should succeed
        resp1 = await client.post("/api/auth/verify", json=payload)
        assert resp1.status_code == 200

        # Second verify with same nonce: should fail
        resp2 = await client.post("/api/auth/verify", json=payload)
        assert resp2.status_code == 401
        assert "Nonce" in resp2.json()["detail"]
