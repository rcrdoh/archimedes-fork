"""Funnel middleware + emit helper — anonymous visitor id for the funnel (#787).

Two pieces, both fail-safe so they can never turn a request into a 5xx:

1. ``ensure_visitor_id_middleware`` — guarantees every visitor carries a stable,
   anonymous ``archimedes_vid`` cookie and exposes it as ``request.state.visitor_id``.
   The id is a random opaque token (no PII, no wallet linkage); it exists only so
   the funnel can join ``landed → generation_started → wallet_connected →
   vault_deployed`` for the *same* browser and report distinct-visitor drop-off.
   The cookie is HttpOnly: the SPA never needs to read it (it rides along on the
   same-origin beacon POST automatically), and the server-side emit points read
   it off ``request.state``.

2. ``record_funnel(request, stage)`` — the helper the route handlers call at the
   three server-authoritative transitions (generation start, SIWE verify, vault
   deploy). Reads the visitor id off ``request.state`` and writes one HLL entry
   via ``FunnelStore``. Swallows everything — instrumentation must be invisible
   to the request it measures.
"""

from __future__ import annotations

import logging
import os
import secrets

from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_VID_COOKIE = "archimedes_vid"
_VID_TTL_SECONDS = 180 * 24 * 60 * 60  # 180 days — a "returning visitor" horizon.


def _cookie_is_secure() -> bool:
    """Secure cookies in production (HTTPS), plain in local dev (HTTP).

    Mirrors how the app distinguishes prod from local: ``PUBLIC_DOMAIN`` is set
    only in the deployed environment. A Secure cookie would never be stored over
    local http, which would silently disable funnel tracking in dev.
    """
    return bool(os.getenv("PUBLIC_DOMAIN"))


async def ensure_visitor_id_middleware(request: Request, call_next):
    """Attach a stable anonymous visitor id; set the cookie if it's new.

    Fail-safe: any error here is swallowed so the request proceeds untouched.
    """
    new_vid: str | None = None
    try:
        vid = request.cookies.get(_VID_COOKIE)
        if not vid:
            vid = secrets.token_hex(16)
            new_vid = vid
        request.state.visitor_id = vid
    except Exception as exc:
        logger.debug("visitor-id middleware setup failed: %s", exc)

    response: Response = await call_next(request)

    if new_vid is not None:
        try:
            response.set_cookie(
                key=_VID_COOKIE,
                value=new_vid,
                httponly=True,
                secure=_cookie_is_secure(),
                samesite="lax",  # same-origin SPA; lax is sufficient and works on top-level nav
                max_age=_VID_TTL_SECONDS,
                path="/",
            )
        except Exception as exc:
            logger.debug("visitor-id cookie set failed: %s", exc)

    return response


async def record_funnel(request: Request, stage: str) -> None:
    """Record a server-authoritative funnel transition for this request's visitor.

    Reads ``request.state.visitor_id`` (set by the middleware) and writes one HLL
    entry. Never raises — a telemetry write must not affect the user's action.
    """
    try:
        visitor_id = getattr(request.state, "visitor_id", "") or ""
        if not visitor_id:
            return
        from archimedes.services.funnel_store import FunnelStore

        store = FunnelStore()
        try:
            await store.record(stage, visitor_id)
        finally:
            await store.close()
    except Exception as exc:
        logger.debug("record_funnel failed for stage %s: %s", stage, exc)
