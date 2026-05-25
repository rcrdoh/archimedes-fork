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


def test_derive_key_returns_url_safe_base64() -> None:
    key = _derive_key()
    # Fernet keys are 44 bytes when base64-encoded
    assert isinstance(key, bytes)
    assert len(key) == 44

    # Deterministic when the env is identical
    key2 = _derive_key()
    assert key == key2


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
