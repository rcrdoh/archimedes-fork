"""Email encryption at rest using Fernet (symmetric encryption).

Uses a key derived from the ``EMAIL_ENCRYPTION_KEY`` env var. If the env var
is not set, a deterministic key is generated from a fixed secret — this is
acceptable for the hackathon MVP (no real user data in production).

The Fernet key must be a URL-safe base64-encoded 32-byte value.
```

Security model:
  - Email is encrypted before storage and decrypted on read.
  - The DB column stores the Fernet token as a string.
  - If the key is rotated, existing tokens become unreadable — a migration
    script would need to re-encrypt. For v1, the key is fixed.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet

# Local-dev fallback — production startup rejects missing EMAIL_ENCRYPTION_KEY
# (fail-closed in main.py when PUBLIC_DOMAIN is set). This fallback only runs
# in local dev / CI where no real user data is at risk.
_LOCAL_DEV_FALLBACK = "archimedes-local-dev-only-not-for-production"


def _derive_key() -> bytes:
    """Derive a Fernet key from env var or local-dev fallback."""
    secret = os.getenv("EMAIL_ENCRYPTION_KEY", _LOCAL_DEV_FALLBACK)
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
