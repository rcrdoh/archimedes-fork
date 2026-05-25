"""Tests for /health/amm endpoint (Issue #309)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_amm_returns_200_or_503_never_404():
    """The endpoint exists and never returns 404."""
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health/amm")
    assert resp.status_code in (200, 503), f"Expected 200 or 503, got {resp.status_code}"
    data = resp.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_health_amm_503_when_chain_disconnected():
    """Returns 503 with explicit status when chain not reachable."""
    from archimedes.main import app

    with patch("archimedes.chain.client.chain_client.is_connected", new=AsyncMock(return_value=False)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health/amm")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] in ("amm_pools_not_initialized", "chain_disconnected")


@pytest.mark.asyncio
async def test_health_amm_503_when_no_pools():
    """Returns 503 when chain is up but no pools exist."""
    from archimedes.main import app

    mock_router = MagicMock()
    mock_get_all_pools_call = MagicMock()
    mock_get_all_pools_call.call = AsyncMock(return_value=[])
    mock_router.functions.getAllPools.return_value = mock_get_all_pools_call

    mock_loader = MagicMock()
    mock_loader.amm_router.return_value = mock_router

    with (
        patch("archimedes.chain.client.chain_client.is_connected", new=AsyncMock(return_value=True)),
        patch("archimedes.chain.contracts.get_contract_loader", return_value=mock_loader),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health/amm")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "amm_pools_not_initialized"


@pytest.mark.asyncio
async def test_health_amm_200_when_pools_active():
    """Returns 200 with pool list when pools exist."""
    from archimedes.main import app

    pool_addr = "0x1234567890123456789012345678901234567890"

    # Mock the pool contract
    mock_pool = MagicMock()
    mock_pool.functions.tokenA.return_value.call = AsyncMock(return_value="0xAAA")
    mock_pool.functions.tokenB.return_value.call = AsyncMock(return_value="0xBBB")
    mock_pool.functions.reserveA.return_value.call = AsyncMock(return_value=1000000)
    mock_pool.functions.reserveB.return_value.call = AsyncMock(return_value=2000000)

    # Mock the router
    mock_router = MagicMock()
    mock_get_all_pools_call = MagicMock()
    mock_get_all_pools_call.call = AsyncMock(return_value=[pool_addr])
    mock_router.functions.getAllPools.return_value = mock_get_all_pools_call

    mock_loader = MagicMock()
    mock_loader.amm_router.return_value = mock_router
    mock_loader.amm_pool.return_value = mock_pool

    with (
        patch("archimedes.chain.client.chain_client.is_connected", new=AsyncMock(return_value=True)),
        patch("archimedes.chain.contracts.get_contract_loader", return_value=mock_loader),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health/amm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["pool_count"] >= 1


@pytest.mark.asyncio
async def test_health_main_no_regression():
    """Main /health endpoint still works."""
    from archimedes.main import app

    with patch("archimedes.chain.client.chain_client.is_connected", new=AsyncMock(return_value=False)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "service" in data
