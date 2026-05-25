"""Unit coverage for the AMM liquidity bootstrap helper.

Mocks Circle signer + chain client + the contract loader so no live RPC
fires. Exercises every branch in `bootstrap_amm_liquidity`:
 - not-configured short-circuit,
 - missing-token skip,
 - empty-pool sentinel skip,
 - zero-price skip,
 - too-small-amount skip,
 - happy path (approve + addLiquidity),
 - per-token exception isolation.

Added 2026-05-24 as part of the #147 coverage-gate lift.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from archimedes.services.amm_bootstrap import bootstrap_amm_liquidity


def _settings(synths: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        usdc_address="0xUSDC",
        amm_router_address="0xR",
        synth_addresses=synths,
    )


def _loader(pool_addr: str = "0x" + "p" * 40, price_raw: int = 100_000_000):
    """Build a mocked contract loader returning the given pool + oracle price."""
    loader = MagicMock()
    loader.amm_router.functions.getPool.return_value.call = AsyncMock(return_value=pool_addr)
    oracle = MagicMock()
    oracle.functions.price.return_value.call = AsyncMock(return_value=price_raw)
    loader.oracle_for.return_value = oracle
    return loader


class TestBootstrapNotConfigured:
    @pytest.mark.asyncio
    async def test_returns_error_when_circle_not_configured(self) -> None:
        with patch("archimedes.services.amm_bootstrap.circle_signer") as signer:
            signer.is_configured = False
            result = await bootstrap_amm_liquidity()
            assert result == {"error": "Circle wallet not configured"}


class TestBootstrapPerTokenSkips:
    @pytest.mark.asyncio
    async def test_empty_token_address_skipped_silently(self) -> None:
        with (
            patch("archimedes.services.amm_bootstrap.circle_signer") as signer,
            patch("archimedes.services.amm_bootstrap.chain_client") as cc,
            patch("archimedes.services.amm_bootstrap.get_contract_loader") as gl,
        ):
            signer.is_configured = True
            cc.settings = _settings({"sNULL": ""})
            cc.to_checksum.side_effect = lambda x: x
            gl.return_value = _loader()
            result = await bootstrap_amm_liquidity()
            # Empty address never enters the loop body
            assert "sNULL" not in result

    @pytest.mark.asyncio
    async def test_no_pool_yields_skipped_status(self) -> None:
        with (
            patch("archimedes.services.amm_bootstrap.circle_signer") as signer,
            patch("archimedes.services.amm_bootstrap.chain_client") as cc,
            patch("archimedes.services.amm_bootstrap.get_contract_loader") as gl,
        ):
            signer.is_configured = True
            cc.settings = _settings({"sTSLA": "0xT"})
            cc.to_checksum.side_effect = lambda x: x
            gl.return_value = _loader(pool_addr="0x0000000000000000000000000000000000000000")
            result = await bootstrap_amm_liquidity()
            assert result["sTSLA"] == {"status": "skipped", "reason": "no pool"}

    @pytest.mark.asyncio
    async def test_zero_price_yields_skipped_status(self) -> None:
        with (
            patch("archimedes.services.amm_bootstrap.circle_signer") as signer,
            patch("archimedes.services.amm_bootstrap.chain_client") as cc,
            patch("archimedes.services.amm_bootstrap.get_contract_loader") as gl,
        ):
            signer.is_configured = True
            cc.settings = _settings({"sTSLA": "0xT"})
            cc.to_checksum.side_effect = lambda x: x
            gl.return_value = _loader(price_raw=0)
            result = await bootstrap_amm_liquidity()
            assert result["sTSLA"] == {"status": "skipped", "reason": "zero price"}

    @pytest.mark.asyncio
    async def test_amount_too_small_yields_skipped_status(self) -> None:
        with (
            patch("archimedes.services.amm_bootstrap.circle_signer") as signer,
            patch("archimedes.services.amm_bootstrap.chain_client") as cc,
            patch("archimedes.services.amm_bootstrap.get_contract_loader") as gl,
        ):
            signer.is_configured = True
            cc.settings = _settings({"sTSLA": "0xT"})
            cc.to_checksum.side_effect = lambda x: x
            # Massive price → tiny token amount → int(...) == 0
            gl.return_value = _loader(price_raw=10**40)
            result = await bootstrap_amm_liquidity(usdc_per_pool=0.000_001)
            assert result["sTSLA"]["status"] == "skipped"
            assert result["sTSLA"]["reason"] == "amount too small"


class TestBootstrapHappyPath:
    @pytest.mark.asyncio
    async def test_success_records_tx_and_amounts(self) -> None:
        signer = MagicMock()
        signer.is_configured = True
        signer.execute_contract = AsyncMock(return_value="0x" + "deadbeef" * 8)
        with (
            patch("archimedes.services.amm_bootstrap.circle_signer", signer),
            patch("archimedes.services.amm_bootstrap.chain_client") as cc,
            patch("archimedes.services.amm_bootstrap.get_contract_loader") as gl,
        ):
            cc.settings = _settings({"sTSLA": "0xT"})
            cc.to_checksum.side_effect = lambda x: x
            gl.return_value = _loader(price_raw=200_000_000)  # $200
            result = await bootstrap_amm_liquidity(usdc_per_pool=2.0)
            assert result["sTSLA"]["status"] == "success"
            assert result["sTSLA"]["usdc_added"] == 2.0
            assert result["sTSLA"]["tokens_added"] == round(0.01, 6)  # 2/200
            assert result["sTSLA"]["tx_hash"].startswith("0xdead")
            # 2 approve + 1 addLiquidity = 3 contract executions per token
            assert signer.execute_contract.call_count == 3


class TestBootstrapFailureIsolation:
    @pytest.mark.asyncio
    async def test_per_token_exception_does_not_kill_others(self) -> None:
        signer = MagicMock()
        signer.is_configured = True
        signer.execute_contract = AsyncMock(side_effect=RuntimeError("rpc dropped"))
        with (
            patch("archimedes.services.amm_bootstrap.circle_signer", signer),
            patch("archimedes.services.amm_bootstrap.chain_client") as cc,
            patch("archimedes.services.amm_bootstrap.get_contract_loader") as gl,
        ):
            cc.settings = _settings({"sTSLA": "0xT", "sBTC": "0xB"})
            cc.to_checksum.side_effect = lambda x: x
            gl.return_value = _loader(price_raw=100_000_000)
            result = await bootstrap_amm_liquidity()
            # Both tokens recorded as failed, neither raised out of the loop
            assert result["sTSLA"]["status"] == "failed"
            assert result["sBTC"]["status"] == "failed"
            assert "rpc dropped" in result["sTSLA"]["error"]
