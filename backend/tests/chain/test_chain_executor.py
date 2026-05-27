"""Tests for ChainExecutor — on-chain vault operations.

Target: backend/archimedes/chain/executor.py
Goal: ≥85% coverage. Consolidates #405 sub-task 5 + #408.

Hermetic: all chain/contract calls mocked. No network, no Arc RPC, no Circle.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from archimedes.chain.executor import (
    MIN_HEALTHY_LIQUIDITY_USDC,
    ChainExecutor,
    InsufficientLiquidityError,
)
from archimedes.models.portfolio import TradeDirection, TradeOrder


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def mock_loader():
    """Mock ContractLoader with all contract accessors."""
    loader = MagicMock()
    # amm_router is a @property
    mock_router = MagicMock()
    type(loader).amm_router = PropertyMock(return_value=mock_router)
    loader.amm_pool.return_value = MagicMock()
    loader.vault.return_value = MagicMock()
    loader.oracle_for.return_value = MagicMock()
    loader.usdc.return_value = MagicMock()
    return loader


@pytest.fixture
def executor(mock_loader):
    """ChainExecutor with mocked loader + chain_client."""
    with patch("archimedes.chain.executor.chain_client") as mock_cc:
        mock_cc.settings = MagicMock()
        mock_cc.settings.usdc_address = "0x3600000000000000000000000000000000000000"
        mock_cc.settings.synth_addresses = {
            "sTSLA": "0xE745C07d7d32A1Ca0d6162A1c50e876619CF7388",
            "sSPY": "0x04315D3c35639288949cEE1d1E01Bd6100aDf3f5",
        }
        mock_cc.settings.oracle_addresses = {
            "sTSLA": "0xe1c9f2b11be97097223a66a188fca541e07873a6",
        }
        mock_cc.settings.chain_id = 5042002
        mock_cc.settings.agent_account = None  # No raw key
        mock_cc.to_checksum = lambda addr: addr  # pass-through
        mock_cc.w3 = MagicMock()
        mock_cc.w3.eth = MagicMock()
        mock_cc.w3.eth.gas_price = AsyncMock(return_value=1000000000)

        ex = ChainExecutor(loader=mock_loader)
        ex._mock_cc = mock_cc  # expose for test access
        yield ex


def _make_trade(symbol="sTSLA", direction=TradeDirection.BUY, amount=10.0, token_address=None):
    return TradeOrder(
        symbol=symbol,
        direction=direction,
        amount=amount,
        token_address=token_address or "0xE745C07d7d32A1Ca0d6162A1c50e876619CF7388",
        estimated_usdc_value=amount,
    )


# ── _validate_trade_liquidity ─────────────────────────────────


class TestValidateTradeLiquidity:
    def test_skips_usdc_self_swap(self, executor, mock_loader):
        """USDC→USDC leg should be silently skipped (Issue #399)."""
        trade = _make_trade(
            symbol="USDC",
            token_address="0x3600000000000000000000000000000000000000",
        )
        # Should not call getPool at all
        asyncio.run(executor._validate_trade_liquidity([trade]))
        mock_loader.amm_router.functions.getPool.assert_not_called()

    def test_raises_on_zero_pool(self, executor, mock_loader):
        """getPool returning zero address → InsufficientLiquidityError."""
        trade = _make_trade()
        mock_loader.amm_router.functions.getPool.return_value.call = AsyncMock(return_value="0x" + "0" * 40)

        with pytest.raises(InsufficientLiquidityError, match="zero address"):
            asyncio.run(executor._validate_trade_liquidity([trade]))

    def test_raises_on_low_reserves(self, executor, mock_loader):
        """Pool with reserves below threshold → InsufficientLiquidityError."""
        trade = _make_trade()
        pool_addr = "0x38c3A5f52044a72C9cC11Ce621f1bfD7754BF8Bd"
        mock_loader.amm_router.functions.getPool.return_value.call = AsyncMock(return_value=pool_addr)

        mock_pool = mock_loader.amm_pool.return_value
        mock_pool.functions.reserve0.return_value.call = AsyncMock(return_value=100_000)  # $0.10
        mock_pool.functions.reserve1.return_value.call = AsyncMock(return_value=1_000_000_000_000)
        mock_pool.functions.token0.return_value.call = AsyncMock(
            return_value="0x3600000000000000000000000000000000000000"  # USDC is token0
        )

        with pytest.raises(InsufficientLiquidityError, match="below threshold"):
            asyncio.run(executor._validate_trade_liquidity([trade]))

    def test_passes_on_sufficient_reserves(self, executor, mock_loader):
        """Pool with reserves above threshold → no error."""
        trade = _make_trade()
        pool_addr = "0x38c3A5f52044a72C9cC11Ce621f1bfD7754BF8Bd"
        mock_loader.amm_router.functions.getPool.return_value.call = AsyncMock(return_value=pool_addr)

        mock_pool = mock_loader.amm_pool.return_value
        # $10,000 USDC (6 decimals)
        mock_pool.functions.reserve0.return_value.call = AsyncMock(return_value=10_000_000_000)
        mock_pool.functions.reserve1.return_value.call = AsyncMock(return_value=1_000_000_000_000_000)
        mock_pool.functions.token0.return_value.call = AsyncMock(
            return_value="0x3600000000000000000000000000000000000000"
        )

        # Should not raise
        asyncio.run(executor._validate_trade_liquidity([trade]))

    def test_usdc_as_token1(self, executor, mock_loader):
        """When USDC is token1, reserve1 is the USDC-side reserve."""
        trade = _make_trade()
        pool_addr = "0xe0725Db0eC0e793Cde04Fa32BA21A4D211a5E685"
        mock_loader.amm_router.functions.getPool.return_value.call = AsyncMock(return_value=pool_addr)

        mock_pool = mock_loader.amm_pool.return_value
        mock_pool.functions.reserve0.return_value.call = AsyncMock(return_value=500_000_000_000_000)  # synth
        mock_pool.functions.reserve1.return_value.call = AsyncMock(return_value=10_000_000_000)  # USDC
        mock_pool.functions.token0.return_value.call = AsyncMock(
            return_value="0xE745C07d7d32A1Ca0d6162A1c50e876619CF7388"  # synth is token0
        )

        # Should pass — USDC (token1) has $10k
        asyncio.run(executor._validate_trade_liquidity([trade]))

    def test_non_fatal_on_unexpected_error(self, executor, mock_loader):
        """Unexpected errors during pool read are non-fatal (logged, trade allowed)."""
        trade = _make_trade()
        mock_loader.amm_router.functions.getPool.return_value.call = AsyncMock(side_effect=RuntimeError("RPC timeout"))

        # Should NOT raise — non-fatal
        asyncio.run(executor._validate_trade_liquidity([trade]))


# ── execute_trades ────────────────────────────────────────────


class TestExecuteTrades:
    def test_calls_validate_liquidity_before_swap(self, executor, mock_loader):
        """execute_trades must call _validate_trade_liquidity first."""
        trade = _make_trade()

        with (
            patch.object(executor, "_validate_trade_liquidity", new=AsyncMock()) as mock_validate,
            patch("archimedes.chain.executor.circle_signer") as mock_signer,
        ):
            mock_signer.is_configured = True
            mock_signer.execute_contract = AsyncMock(return_value="0xtxhash")

            asyncio.run(executor.execute_trades("0xvault", [trade]))
            mock_validate.assert_called_once_with([trade])

    def test_raises_insufficient_liquidity(self, executor):
        """execute_trades propagates InsufficientLiquidityError."""
        trade = _make_trade()

        with patch.object(
            executor, "_validate_trade_liquidity", new=AsyncMock(side_effect=InsufficientLiquidityError("thin pool"))
        ):
            with pytest.raises(InsufficientLiquidityError):
                asyncio.run(executor.execute_trades("0xvault", [trade]))

    def test_circle_signer_path(self, executor, mock_loader):
        """When Circle signer is configured, uses circle_signer.execute_contract."""
        trade = _make_trade()

        with (
            patch.object(executor, "_validate_trade_liquidity", new=AsyncMock()),
            patch("archimedes.chain.executor.circle_signer") as mock_signer,
        ):
            mock_signer.is_configured = True
            mock_signer.execute_contract = AsyncMock(return_value="0xdeadbeef")

            result = asyncio.run(executor.execute_trades("0xvault", [trade]))
            assert result == ["0xdeadbeef"]
            mock_signer.execute_contract.assert_called_once()

    def test_no_signer_raises(self, executor):
        """No Circle signer + no raw key → RuntimeError."""
        trade = _make_trade()

        with (
            patch.object(executor, "_validate_trade_liquidity", new=AsyncMock()),
            patch("archimedes.chain.executor.circle_signer") as mock_signer,
        ):
            mock_signer.is_configured = False
            executor._mock_cc.settings.agent_account = None

            with pytest.raises(RuntimeError, match="No agent account"):
                asyncio.run(executor.execute_trades("0xvault", [trade]))


# ── _usdc_value_to_token_raw ─────────────────────────────────


class TestUsdcValueToTokenRaw:
    def test_usdc_to_usdc_returns_6_decimals(self, executor):
        """USDC→USDC: amount × 1e6."""
        result = asyncio.run(executor._usdc_value_to_token_raw("0x3600000000000000000000000000000000000000", 10.0))
        assert result == 10_000_000  # 10 × 1e6

    def test_synth_with_oracle_price(self, executor, mock_loader):
        """Synth with oracle price: usdc_value / price × 1e18."""
        mock_oracle = mock_loader.oracle_for.return_value
        mock_oracle.functions.price.return_value.call = AsyncMock(return_value=500_000_000)  # $500

        result = asyncio.run(
            executor._usdc_value_to_token_raw(
                "0xE745C07d7d32A1Ca0d6162A1c50e876619CF7388",
                100.0,  # $100 of sTSLA
            )
        )
        # $100 / $500 = 0.2 tokens × 1e18
        assert result == 200_000_000_000_000_000  # 0.2 × 1e18

    def test_fallback_on_oracle_failure(self, executor, mock_loader):
        """Oracle failure → fallback 1:1 at 18 decimals."""
        mock_oracle = mock_loader.oracle_for.return_value
        mock_oracle.functions.price.return_value.call = AsyncMock(side_effect=RuntimeError("oracle down"))

        result = asyncio.run(executor._usdc_value_to_token_raw("0xE745C07d7d32A1Ca0d6162A1c50e876619CF7388", 5.0))
        # Fallback: 5 × 1e18
        assert result == 5_000_000_000_000_000_000

    def test_unknown_token_fallback(self, executor):
        """Unknown token address → fallback 1:1 at 18 decimals."""
        result = asyncio.run(executor._usdc_value_to_token_raw("0x0000000000000000000000000000000000099999", 1.0))
        assert result == 1_000_000_000_000_000_000  # 1 × 1e18


# ── InsufficientLiquidityError ────────────────────────────────


class TestInsufficientLiquidityError:
    def test_is_runtime_error(self):
        assert issubclass(InsufficientLiquidityError, RuntimeError)

    def test_message_preserved(self):
        err = InsufficientLiquidityError("Pool 0x38c3: $0.10 below $5")
        assert "below" in str(err)

    def test_min_threshold_is_positive(self):
        assert MIN_HEALTHY_LIQUIDITY_USDC > 0
