"""Unit coverage for the at-rest email encryption helpers."""

from __future__ import annotations

import pytest
from archimedes.services import email_crypto
from archimedes.services.email_crypto import (
    _derive_key,
    decrypt_email,
    encrypt_email,
)


@pytest.fixture(autouse=True)
def _reset_fernet_singleton():
    """The module memoizes the Fernet instance — reset between tests."""
    email_crypto._fernet = None
    yield
    email_crypto._fernet = None


def test_derive_key_returns_url_safe_base64(monkeypatch) -> None:
    key = _derive_key()
    # Fernet keys are 44 bytes when base64-encoded
    assert isinstance(key, bytes)
    assert len(key) == 44

    # Deterministic when EMAIL_ENCRYPTION_KEY is set
    monkeypatch.setenv("EMAIL_ENCRYPTION_KEY", "stable-secret")
    assert _derive_key() == _derive_key()


def test_derive_key_random_when_env_unset(monkeypatch) -> None:
    # No fixed fallback secret: each derivation is a fresh random key.
    monkeypatch.delenv("EMAIL_ENCRYPTION_KEY", raising=False)
    assert _derive_key() != _derive_key()


def test_encrypt_decrypt_roundtrip() -> None:
    plaintext = "alice@example.com"
    token = encrypt_email(plaintext)
    assert token is not None
    assert token != plaintext  # encrypted
    assert decrypt_email(token) == plaintext


def test_encrypt_none_returns_none() -> None:
    assert encrypt_email(None) is None


def test_decrypt_none_returns_none() -> None:
    assert decrypt_email(None) is None


def test_different_plaintexts_produce_different_tokens() -> None:
    t1 = encrypt_email("alice@example.com")
    t2 = encrypt_email("bob@example.com")
    assert t1 != t2


def test_env_var_changes_key(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_ENCRYPTION_KEY", "test-key-override")
    custom_key = _derive_key()
    monkeypatch.delenv("EMAIL_ENCRYPTION_KEY", raising=False)
    default_key = _derive_key()
    assert custom_key != default_key


# ── Fail-closed in production (issue #753) ────────────────────────────────


def test_derive_key_fails_closed_in_production_without_key(monkeypatch) -> None:
    """Prod context (PUBLIC_DOMAIN set, no dev opt-in) + no key → raise.

    Refusing the random-key fallback prevents encrypting real PII with an
    ephemeral key that cannot be decrypted after a restart.
    """
    monkeypatch.delenv("EMAIL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("PUBLIC_DOMAIN", "https://archimedes-arc.com")
    with pytest.raises(RuntimeError, match="EMAIL_ENCRYPTION_KEY"):
        _derive_key()


def test_encrypt_fails_closed_in_production_without_key(monkeypatch) -> None:
    """The fail-closed guard also fires through the public encrypt entrypoint."""
    monkeypatch.delenv("EMAIL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("PUBLIC_DOMAIN", "https://archimedes-arc.com")
    with pytest.raises(RuntimeError, match="EMAIL_ENCRYPTION_KEY"):
        encrypt_email("alice@example.com")


def test_derive_key_dev_path_works_without_key_no_public_domain(monkeypatch) -> None:
    """Local dev (no PUBLIC_DOMAIN, no key) still gets a random key — no raise."""
    monkeypatch.delenv("EMAIL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("PUBLIC_DOMAIN", raising=False)
    monkeypatch.delenv("TESTING", raising=False)
    key = _derive_key()  # must not raise
    assert isinstance(key, bytes)
    assert len(key) == 44


def test_derive_key_testing_optin_overrides_production_marker(monkeypatch) -> None:
    """TESTING=1 keeps the dev path working even if PUBLIC_DOMAIN is set."""
    monkeypatch.delenv("EMAIL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("PUBLIC_DOMAIN", "https://archimedes-arc.com")
    monkeypatch.setenv("TESTING", "1")
    key = _derive_key()  # must not raise — TESTING is the explicit dev opt-in
    assert isinstance(key, bytes)
    assert len(key) == 44


def test_production_with_key_still_works(monkeypatch) -> None:
    """Prod with the key set is the normal, deterministic, non-raising path."""
    monkeypatch.setenv("PUBLIC_DOMAIN", "https://archimedes-arc.com")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("EMAIL_ENCRYPTION_KEY", "a-real-prod-secret")
    token = encrypt_email("alice@example.com")
    assert decrypt_email(token) == "alice@example.com"
