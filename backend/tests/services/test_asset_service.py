"""Unit coverage for AssetService — list_assets composes oracle + chain.

Mocks `chain_client` and the `OracleUpdater` so no live RPC fires.

Added 2026-05-24 as part of the #147 coverage-gate lift.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from archimedes.services.asset_service import AssetService


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        usdc_address="0xUSDC",
        synth_addresses={"sTSLA": "0xT", "sNVDA": "0xN", "sNULL": ""},
        oracle_addresses={"sTSLA": "0xOT", "sNVDA": "0xON"},
    )


class TestListAssets:
    @pytest.mark.asyncio
    async def test_usdc_is_first_and_well_formed(self) -> None:
        oracle = MagicMock()
        oracle.fetch_prices = AsyncMock(return_value=[])
        with (
            patch("archimedes.services.asset_service.OracleUpdater", return_value=oracle),
            patch("archimedes.chain.client.chain_client") as cc,
        ):
            cc.settings = _settings()
            resp = await AssetService().list_assets()
            assert resp.assets[0].symbol == "USDC"
            assert resp.assets[0].asset_type == "native"
            assert resp.assets[0].decimals == 6
            assert resp.assets[0].price_usd == 1.0

    @pytest.mark.asyncio
    async def test_synthetics_emitted_with_oracle_prices(self) -> None:
        oracle = MagicMock()
        oracle.fetch_prices = AsyncMock(
            return_value=[
                SimpleNamespace(symbol="sTSLA", price_usd=180.0),
                SimpleNamespace(symbol="sNVDA", price_usd=900.0),
            ]
        )
        with (
            patch("archimedes.services.asset_service.OracleUpdater", return_value=oracle),
            patch("archimedes.chain.client.chain_client") as cc,
        ):
            cc.settings = _settings()
            resp = await AssetService().list_assets()
            symbols = [a.symbol for a in resp.assets]
            assert symbols == ["USDC", "sTSLA", "sNVDA"]  # sNULL filtered out
            stsla = next(a for a in resp.assets if a.symbol == "sTSLA")
            assert stsla.price_usd == 180.0
            assert stsla.asset_type == "synthetic"
            assert stsla.decimals == 18
            assert stsla.name == "Synthetic TSLA"  # symbol[1:] expansion
            assert stsla.oracle_address == "0xOT"

    @pytest.mark.asyncio
    async def test_synthetic_with_missing_price_falls_back_to_zero(self) -> None:
        oracle = MagicMock()
        oracle.fetch_prices = AsyncMock(return_value=[])  # no quotes available
        with (
            patch("archimedes.services.asset_service.OracleUpdater", return_value=oracle),
            patch("archimedes.chain.client.chain_client") as cc,
        ):
            cc.settings = _settings()
            resp = await AssetService().list_assets()
            stsla = next(a for a in resp.assets if a.symbol == "sTSLA")
            assert stsla.price_usd == 0.0

    @pytest.mark.asyncio
    async def test_empty_address_synthetic_is_skipped(self) -> None:
        oracle = MagicMock()
        oracle.fetch_prices = AsyncMock(return_value=[])
        with (
            patch("archimedes.services.asset_service.OracleUpdater", return_value=oracle),
            patch("archimedes.chain.client.chain_client") as cc,
        ):
            cc.settings = _settings()
            resp = await AssetService().list_assets()
            assert "sNULL" not in [a.symbol for a in resp.assets]
