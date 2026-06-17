"""User profile API — optional profile keyed by wallet address.

Endpoints:
  GET  /api/user/profile/{wallet}   — retrieve profile (404 if not set)
  POST /api/user/profile             — create or update profile

Wallet IS the identity.

Security (Issue #181):
  - Email is encrypted at rest via Fernet (services/email_crypto.py).
  - Email / display_name / marketing_opt_in are only echoed to the owner wallet.
  - Anonymous GET returns only public-safe fields.
  - All log output routes through log_scrubber to prevent PII leakage.
"""

from __future__ import annotations

import json
import logging

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.orm import Session

from archimedes.api.limiter import limiter
from archimedes.api.user_schemas import UserProfileCreate, UserProfileResponse
from archimedes.db import get_session
from archimedes.models.user_profile import UserProfile
from archimedes.services.email_crypto import decrypt_email, encrypt_email
from archimedes.services.log_scrubber import sanitize_log_value, scrub_profile

logger = logging.getLogger(__name__)

user_router = APIRouter(prefix="/api/user", tags=["user"])

# Public-safe fields returned to anonymous callers.
PUBLIC_FIELDS = ("wallet_address", "interests", "attribution")


def _profile_to_response(p: UserProfile, *, owner: bool = False) -> UserProfileResponse:
    """Build a response from a UserProfile ORM object.

    When *owner* is False (anonymous caller), PII fields are stripped.
    When *owner* is True (caller matches the profile wallet), full data
    is returned with email decrypted.
    """
    interests = json.loads(p.interests) if p.interests else None

    if not owner:
        return UserProfileResponse(
            wallet_address=p.wallet_address,
            display_name=None,
            email=None,
            interests=interests,
            attribution=p.attribution,
            marketing_opt_in=False,  # default-safe
        )

    try:
        email = decrypt_email(p.email)
    except InvalidToken:
        # Ciphertext can't be decrypted with the current EMAIL_ENCRYPTION_KEY
        # (e.g. a key rotation left old tokens unreadable). Degrade to a null
        # email rather than 500ing the whole profile for this wallet.
        logger.warning("decrypt_email failed for wallet=%s: InvalidToken", p.wallet_address)
        email = None

    return UserProfileResponse(
        wallet_address=p.wallet_address,
        display_name=p.display_name,
        email=email,
        interests=interests,
        attribution=p.attribution,
        marketing_opt_in=p.marketing_opt_in,
    )


def _extract_caller_wallet_siwe(request: Request) -> str | None:
    """Extract wallet from SIWE session ONLY (cryptographic proof).

    Used for PII access — email and display_name are ONLY returned
    when this function returns a verified wallet.
    """
    from archimedes.api.auth_siwe import get_verified_wallet

    return get_verified_wallet(request)


@user_router.get("/profile/{wallet}", response_model=UserProfileResponse)
async def get_profile(wallet: str, request: Request):
    """Retrieve a wallet's profile. Returns 404 if not set.

    PII fields (email, display_name, marketing_opt_in) are only included
    when the caller holds a verified SIWE session for the requested
    profile wallet. The X-Wallet-Address header is not used for this
    check — it is forgeable (see Issue #402).
    """
    session: Session = get_session()
    try:
        wallet_lower = wallet.lower()
        profile = session.query(UserProfile).filter(UserProfile.wallet_address == wallet_lower).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        # PII requires SIWE session — header spoofing cannot access email/name
        is_owner = _extract_caller_wallet_siwe(request) == wallet_lower
        response = _profile_to_response(profile, owner=is_owner)

        logger.info(
            "get_profile: wallet=%s owner=%s data=%s",
            sanitize_log_value(wallet_lower),
            is_owner,
            scrub_profile(response.model_dump()),
        )
        return response
    finally:
        session.close()


@user_router.post("/profile", response_model=UserProfileResponse)
@limiter.limit("1/minute")
async def upsert_profile(payload: UserProfileCreate, request: Request, response: Response):  # noqa: ARG001 — response param threaded for downstream cookie/header setting; not used in current body
    """Create or update a wallet's profile. All fields optional except wallet.

    Email is encrypted at rest before storage. Caller must hold a valid SIWE
    session matching `payload.wallet_address` — prevents one wallet from
    writing another wallet's profile. The X-Wallet-Address header fallback
    was dropped per Issue #402 because it is forgeable.
    """
    caller = _extract_caller_wallet_siwe(request)
    if caller is None:
        raise HTTPException(status_code=403, detail="Forbidden: SIWE session required for profile writes")
    wallet = payload.wallet_address.lower()
    if caller != wallet:
        raise HTTPException(status_code=403, detail="Forbidden: SIWE session wallet does not match payload wallet")

    session: Session = get_session()
    try:
        profile = session.query(UserProfile).filter(UserProfile.wallet_address == wallet).first()

        interests_json = json.dumps(payload.interests) if payload.interests else "[]"
        encrypted_email = encrypt_email(payload.email)

        if profile:
            # Update existing
            if payload.display_name is not None:
                profile.display_name = payload.display_name
            if payload.email is not None:
                profile.email = encrypted_email
            profile.interests = interests_json
            if payload.attribution is not None:
                profile.attribution = payload.attribution
            profile.marketing_opt_in = payload.marketing_opt_in
        else:
            # Create new
            profile = UserProfile(
                wallet_address=wallet,
                display_name=payload.display_name,
                email=encrypted_email,
                interests=interests_json,
                attribution=payload.attribution,
                marketing_opt_in=payload.marketing_opt_in,
            )
            session.add(profile)

        session.commit()
        session.refresh(profile)

        logger.info(
            "upsert_profile: wallet=%s data=%s",
            sanitize_log_value(wallet),
            scrub_profile(
                {
                    "wallet_address": sanitize_log_value(wallet),
                    "email": payload.email,
                    "display_name": payload.display_name,
                    "marketing_opt_in": payload.marketing_opt_in,
                }
            ),
        )

        return _profile_to_response(profile, owner=True)
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        # Do NOT include PII in error messages
        logger.error("upsert_profile failed for wallet=%s: %s", sanitize_log_value(wallet), type(e).__name__)
        raise HTTPException(status_code=500, detail="Profile update failed") from e
    finally:
        session.close()
