"""Visitor-insight capture helper — geography + device from a request (#787).

Derives the visitor's country (CloudFront-Viewer-Country) and device class
(CloudFront device headers, falling back to a User-Agent sniff) and records them
via ``VisitorInsightsStore``. Called from the telemetry middleware, which already
classifies human-vs-agent and has the anonymous ``visitor_id`` on request state.

Humans only: agent/crawler traffic is skipped so the geography reflects real
visitors, not datacenter crawler IPs. Fail-safe — never raises into the request.
"""

from __future__ import annotations

import logging

from starlette.requests import Request

logger = logging.getLogger(__name__)


def _device_class(request: Request) -> str:
    """Best-effort device class: prefer CloudFront's device headers, else UA sniff."""
    h = request.headers
    if h.get("cloudfront-is-tablet-viewer", "").lower() == "true":
        return "tablet"
    if h.get("cloudfront-is-mobile-viewer", "").lower() == "true":
        return "mobile"
    if h.get("cloudfront-is-smarttv-viewer", "").lower() == "true":
        return "tv"
    if h.get("cloudfront-is-desktop-viewer", "").lower() == "true":
        return "desktop"
    # Fallback (no CloudFront headers — local/dev, or before the TF change lands):
    ua = h.get("user-agent", "").lower()
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "mobi" in ua or "android" in ua or "iphone" in ua:
        return "mobile"
    if ua:
        return "desktop"
    return "unknown"


async def record_visitor_insight(request: Request, is_agent: bool) -> None:
    """Record this request's visitor geography + device (humans only). Never raises."""
    if is_agent:
        return
    try:
        visitor_id = getattr(request.state, "visitor_id", "") or ""
        if not visitor_id:
            return
        country = request.headers.get("cloudfront-viewer-country")
        device = _device_class(request)

        from archimedes.services.visitor_insights_store import VisitorInsightsStore

        store = VisitorInsightsStore()
        try:
            await store.record(country, device, visitor_id)
        finally:
            await store.close()
    except Exception as exc:
        logger.debug("record_visitor_insight failed: %s", exc)
