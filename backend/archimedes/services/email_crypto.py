"""Email encryption at rest using Fernet (symmetric encryption).

Uses a key derived from the ``EMAIL_ENCRYPTION_KEY`` env var. If the env var
is not set, a *random per-process* key is generated at startup — emails
encrypted in one dev session cannot be decrypted in another. This is
intentional: dev data is disposable, and it means there is no fixed fallback
secret that could decrypt a deployment that merely forgot to set the env var.

The Fernet key must be a URL-safe base64-encoded 32-byte value.

Security model:
  - Email is encrypted before storage and decrypted on read.
  - The DB column stores the Fernet token as a string.
  - If the key is rotated, existing tokens become unreadable — a migration
    script would need to re-encrypt. For v1, the key is fixed (per deployment).
  - Production startup rejects a missing EMAIL_ENCRYPTION_KEY (fail-closed in
    main.py when PUBLIC_DOMAIN is set), so the random fallback only ever runs
    in local dev / CI where no real user data is at risk.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


def _derive_key() -> bytes:
    """Derive a Fernet key from env var, or a random per-process key in dev.

    With ``EMAIL_ENCRYPTION_KEY`` set the key is deterministic (so tokens
    survive restarts). Unset, we generate a fresh random key — there is no
    fixed, publicly-known fallback secret.
    """
    secret = os.getenv("EMAIL_ENCRYPTION_KEY", "").strip()
    if not secret:
        logger.warning(
            "EMAIL_ENCRYPTION_KEY is not set — using a random per-process key. "
            "Encrypted emails will NOT survive a process restart. Set "
            "EMAIL_ENCRYPTION_KEY for any persistent deployment."
        )
        return Fernet.generate_key()
    # Fernet requires a URL-safe base64-encoded 32-byte key
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_derive_key())
    return _fernet


def encrypt_email(plaintext: str | None) -> str | None:
    """Encrypt an email address. Returns None if input is None."""
    if plaintext is None:
        return None
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_email(token: str | None) -> str | None:
    """Decrypt an email address. Returns None if input is None."""
    if token is None:
        return None
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
