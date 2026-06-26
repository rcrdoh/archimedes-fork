"""Email encryption at rest using Fernet (symmetric encryption).

Uses a key derived from the ``EMAIL_ENCRYPTION_KEY`` env var. If the env var
is not set, a *random per-process* key is generated — emails encrypted in one
dev session cannot be decrypted in another. This is intentional for dev: dev
data is disposable, and there is no fixed fallback secret that could decrypt a
deployment that merely forgot to set the env var.

The Fernet key must be a URL-safe base64-encoded 32-byte value.

Security model:
  - Email is encrypted before storage and decrypted on read.
  - The DB column stores the Fernet token as a string.
  - If the key is rotated, existing tokens become unreadable — a migration
    script would need to re-encrypt. For v1, the key is fixed (per deployment).
  - **Fail-closed in production at the crypto layer (issue #753).** In a
    production context (``PUBLIC_DOMAIN`` set) with no explicit dev opt-in,
    a missing ``EMAIL_ENCRYPTION_KEY`` raises rather than silently falling
    back to a random per-process key. The random-key fallback would otherwise
    encrypt real PII with a key that does not survive a restart (silent data
    loss) and is enforced nowhere. ``main.py`` keeps an equivalent boot-time
    check for an earlier, clearer fatal message — this module-level guard is
    defense-in-depth so the protection travels with the module to *any* entry
    point (worker, ops script, direct service import), not just the FastAPI
    app-boot path.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


def _is_dev_context() -> bool:
    """True when the random-key fallback is acceptable (local dev / CI / tests).

    The fallback is allowed only when this is NOT a production deployment.
    Production is signalled by ``PUBLIC_DOMAIN`` (the same marker ``main.py``
    uses). An explicit ``TESTING`` opt-in (the repo convention, see
    ``api/limiter.py``) keeps the dev/CI path working even if a test sets
    ``PUBLIC_DOMAIN`` to exercise production wiring.
    """
    if os.getenv("TESTING"):
        return True
    return not os.getenv("PUBLIC_DOMAIN")


def _derive_key() -> bytes:
    """Derive a Fernet key from env var, or a random per-process key in dev.

    With ``EMAIL_ENCRYPTION_KEY`` set the key is deterministic (so tokens
    survive restarts). Unset:
      - in a dev/CI/test context → a fresh random key (data is disposable).
      - in production (``PUBLIC_DOMAIN`` set, no ``TESTING`` opt-in) → raise.
        Encrypting real PII with an ephemeral random key would silently lose
        data on restart and is enforced nowhere; we fail closed instead
        (issue #753). This guard travels with the module, so it holds for any
        entry point — not just the FastAPI app-boot check in ``main.py``.
    """
    secret = os.getenv("EMAIL_ENCRYPTION_KEY", "").strip()
    if not secret:
        if not _is_dev_context():
            raise RuntimeError(
                "FATAL: EMAIL_ENCRYPTION_KEY must be set in production "
                "(PUBLIC_DOMAIN is configured). Refusing to encrypt PII with a "
                "random per-process key that cannot be decrypted after restart. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
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
