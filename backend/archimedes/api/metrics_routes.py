"""Metrics routes — public human-vs-agent traction counter (issue #428).

Exposes ``GET /api/metrics`` with the live cumulative human/agent request
counts maintained by the telemetry middleware. This is the read side of the
hackathon win-condition instrument; the write side is
``api/telemetry_middleware.py`` + ``services/telemetry_store.py``.

# TODO(T-observability): Phase 2 — Prometheus ``/metrics`` exposition endpoint
# and an arc-canteen async task that mirrors these counts onto the traction
# dashboard. Intentionally out of scope for this app-layer MVP to keep it tight.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from archimedes.models.telemetry import MetricsResponse
from archimedes.services.telemetry_store import TelemetryStore

metrics_router = APIRouter(prefix="/api", tags=["metrics"])


@metrics_router.get("/metrics", response_model=MetricsResponse)
async def get_metrics() -> MetricsResponse:
    """Return the live human-vs-agent traction counts.

    Fail-safe: ``TelemetryStore.get_counts`` returns ``(0, 0)`` when Redis is
    unreachable, so this endpoint always responds 200 with a well-formed shape.
    """
    store = TelemetryStore()
    try:
        human_count, agent_count = await store.get_counts()
    finally:
        await store.close()

    return MetricsResponse(
        human_count=human_count,
        agent_count=agent_count,
        total_requests=human_count + agent_count,
        timestamp=datetime.now(UTC).isoformat(),
    )
