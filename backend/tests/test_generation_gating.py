"""Tests for the SIWE gate on expensive LLM-generation endpoints.

The gate (``gate_generation``) is controlled by REQUIRE_SIWE_FOR_GENERATION and
defaults OFF so enabling it is an explicit, post-verification flip — it can never
silently break the live Generate flow on deploy. These tests exercise the
dependency in isolation against a minimal app (no Redis / job store needed),
minting a session cookie with the same in-process HMAC key the verifier uses.
"""

import time

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from archimedes.api.auth_siwe import _COOKIE_NAME, _sign_session, gate_generation


def _make_client() -> TestClient:
    app = FastAPI()

    @app.post("/g")
    async def _g(wallet: str | None = Depends(gate_generation)):
        return {"wallet": wallet}

    return TestClient(app)


def test_gate_off_allows_anonymous(monkeypatch):
    """Default (flag unset): anonymous callers pass through, wallet is None."""
    monkeypatch.delenv("REQUIRE_SIWE_FOR_GENERATION", raising=False)
    resp = _make_client().post("/g")
    assert resp.status_code == 200
    assert resp.json()["wallet"] is None


def test_gate_off_attributes_session_when_present(monkeypatch):
    """Flag off but a valid session present: best-effort attribution, still 200."""
    monkeypatch.delenv("REQUIRE_SIWE_FOR_GENERATION", raising=False)
    wallet = "0x" + "ab" * 20
    client = _make_client()
    client.cookies.set(_COOKIE_NAME, _sign_session(wallet, time.time()))
    resp = client.post("/g")
    assert resp.status_code == 200
    assert resp.json()["wallet"] == wallet.lower()


def test_gate_on_blocks_anonymous(monkeypatch):
    """Flag on: anonymous callers are rejected with 401."""
    monkeypatch.setenv("REQUIRE_SIWE_FOR_GENERATION", "true")
    resp = _make_client().post("/g")
    assert resp.status_code == 401


def test_gate_on_allows_valid_session(monkeypatch):
    """Flag on: a valid SIWE session cookie is accepted and returns the wallet."""
    monkeypatch.setenv("REQUIRE_SIWE_FOR_GENERATION", "1")
    wallet = "0x" + "cd" * 20
    client = _make_client()
    client.cookies.set(_COOKIE_NAME, _sign_session(wallet, time.time()))
    resp = client.post("/g")
    assert resp.status_code == 200
    assert resp.json()["wallet"] == wallet.lower()


def test_gate_on_rejects_tampered_session(monkeypatch):
    """Flag on: a cookie with a bad signature is rejected (401)."""
    monkeypatch.setenv("REQUIRE_SIWE_FOR_GENERATION", "yes")
    client = _make_client()
    client.cookies.set(_COOKIE_NAME, '{"wallet":"0xdeadbeef","iat":9999999999}|deadbeef')
    resp = client.post("/g")
    assert resp.status_code == 401
