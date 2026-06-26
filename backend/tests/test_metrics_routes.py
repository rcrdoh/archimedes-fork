"""HTTP-layer tests for the /api/metrics traction endpoint (issue #428).

Mocks the Redis boundary (``TelemetryStore.get_counts``) so the test is
hermetic — no live Redis. Asserts the response shape and the derived total.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_counts_and_total():
    from archimedes.main import app

    with patch(
        "archimedes.services.telemetry_store.TelemetryStore.get_counts",
        new=AsyncMock(return_value=(7, 3)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/metrics")

    assert resp.status_code == 200
    data = resp.json()
    assert data["human_count"] == 7
    assert data["agent_count"] == 3
    assert data["total_requests"] == 10
    assert isinstance(data["timestamp"], str) and data["timestamp"]


@pytest.mark.asyncio
async def test_metrics_endpoint_shape_keys_present():
    from archimedes.main import app

    with patch(
        "archimedes.services.telemetry_store.TelemetryStore.get_counts",
        new=AsyncMock(return_value=(0, 0)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/metrics")

    assert resp.status_code == 200
    data = resp.json()
    for key in ("human_count", "agent_count", "total_requests", "timestamp"):
        assert key in data, f"missing {key} in {list(data.keys())}"
    # Zero state is well-formed, not an error.
    assert data["total_requests"] == 0


@pytest.mark.asyncio
async def test_metrics_endpoint_degrades_to_zero_when_redis_down():
    """When Redis is unreachable, get_counts returns (0, 0) and the endpoint still 200s."""
    from archimedes.main import app
    from archimedes.services.telemetry_store import TelemetryStore

    # Patch the underlying client accessor to fail; get_counts swallows → (0, 0).
    with patch.object(
        TelemetryStore,
        "_get_redis",
        new=AsyncMock(side_effect=ConnectionError("redis down")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/metrics")

    assert resp.status_code == 200
    data = resp.json()
    assert data["human_count"] == 0
    assert data["agent_count"] == 0
    assert data["total_requests"] == 0
