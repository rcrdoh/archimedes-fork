"""Slippage-guard regression for the rebalance call path (issue #506).

WHERE THE SLIPPAGE GUARD LIVES. For Archimedes' vault swaps, the non-zero
``minAmountOut`` slippage floor is enforced ON-CHAIN, in ``Vault.sol``, not in
this Python executor. ``Vault.rebalance`` and ``Vault._liquidateToUsdc`` both
call ``ammRouter.swap(..., _oracleMinOut(...))``, where ``_oracleMinOut`` derives
a strictly-positive floor from the on-chain oracle price minus the bounded
``maxSlippageBps`` (default 100 bps, hard-capped at 500 bps), and REVERTS
(``OracleNotSet`` / ``InvalidOraclePrice``) rather than falling back to
``minAmountOut = 0`` when it can't price the leg. This placement is deliberate
(Vault.sol audit note, 2026-06-14): the agent must NOT be able to set the
slippage floor, or a compromised agent could pass ``minAmountOut ≈ 0`` and leak
vault value. The Solidity tests for this floor live in
``contracts/test/Vault.t.sol`` ("Swap Slippage Protection (issue #506)").

WHAT THIS PYTHON TEST GUARDS. The executor's job is therefore to route every
rebalance through the contract method that applies that on-chain floor — i.e.
``rebalance(address[],uint256[],address[],uint256[])`` — and to never introduce a
Python-side swap path that submits a caller-supplied ``minAmountOut`` of 0/None
(which would bypass the contract's oracle floor). These tests pin that contract:

  - the Circle path submits exactly the no-min ``rebalance(...)`` ABI signature
    (the contract derives the floor itself); it does not pass a 0 min;
  - the raw-key path builds the same ``vault.functions.rebalance(...)`` call;
  - neither path references the AMMRouter.swap(min) primitive directly with a
    zero/None min — the executor only ever talks to the vault, which owns the
    floor.

Hermetic: all chain/contract calls mocked. No network, no Arc RPC, no Circle.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from archimedes.chain.executor import ChainExecutor
from archimedes.models.portfolio import TradeDirection, TradeOrder
from hexbytes import HexBytes

# The rebalance ABI signature that delegates the slippage floor to the vault's
# on-chain _oracleMinOut. There is intentionally NO minAmountOut argument here —
# the vault computes it. A regression that added a Python-supplied min would
# change this signature.
REBALANCE_ABI_SIG = "rebalance(address[],uint256[],address[],uint256[])"

USDC = "0x3600000000000000000000000000000000000000"
SYNTH = "0xE745C07d7d32A1Ca0d6162A1c50e876619CF7388"  # sTSLA-style synth


# ── Fixtures (mirror test_chain_executor.py shapes) ───────────────────────────


@pytest.fixture
def mock_loader():
    loader = MagicMock()
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

    class _Awaitable:
        def __init__(self, value):
            self._value = value

        def __await__(self):
            async def _coro():
                return self._value

            return _coro().__await__()

    with patch("archimedes.chain.executor.chain_client") as mock_cc:
        mock_cc.settings = MagicMock()
        mock_cc.settings.usdc_address = USDC
        mock_cc.settings.synth_addresses = {"sTSLA": SYNTH}
        mock_cc.settings.oracle_addresses = {"sTSLA": "0xe1c9f2b11be97097223a66a188fca541e07873a6"}
        mock_cc.settings.chain_id = 5042002
        mock_cc.settings.agent_account = None
        mock_cc.to_checksum = lambda addr: addr
        mock_cc.w3 = MagicMock()
        mock_cc.w3.eth = MagicMock()
        mock_cc.w3.eth.gas_price = _Awaitable(1_000_000_000)
        mock_cc.w3.eth.get_transaction_count = AsyncMock(return_value=1)
        mock_cc.w3.eth.send_raw_transaction = AsyncMock(return_value=HexBytes(b"\x00" * 32))
        mock_cc.w3.eth.wait_for_transaction_receipt = AsyncMock(return_value={"status": 1})

        ex = ChainExecutor(loader=mock_loader)
        ex._mock_cc = mock_cc
        yield ex


def _buy(symbol="sTSLA", token_address=SYNTH, amount=10.0):
    return TradeOrder(
        symbol=symbol,
        direction=TradeDirection.BUY,
        amount=amount,
        token_address=token_address,
        estimated_usdc_value=amount,
    )


# ── #506: Circle path routes through the on-chain-floor rebalance signature ───


class TestCircleRebalanceUsesOracleFloorSignature:
    def test_circle_submits_no_min_rebalance_signature(self, executor):
        """The Circle path submits the rebalance ABI that delegates the slippage
        floor to the vault (no Python-supplied minAmountOut)."""
        trade = _buy()
        with (
            patch.object(executor, "_validate_trade_liquidity", new=AsyncMock()),
            patch.object(executor, "_confirm_receipt", new=AsyncMock(return_value="0xtx")),
            patch("archimedes.chain.executor.circle_signer") as mock_signer,
        ):
            mock_signer.is_configured = True
            mock_signer.execute_contract = AsyncMock(return_value="0xtx")

            asyncio.run(executor.execute_trades("0xvault", [trade]))

            mock_signer.execute_contract.assert_called_once()
            _, kwargs = mock_signer.execute_contract.call_args
            # The exact rebalance signature — the vault, not the executor, owns
            # the slippage floor. If a refactor adds a Python-side min, this
            # signature (and thus the abi_params arity) changes and the test trips.
            assert kwargs["abi_function"] == REBALANCE_ABI_SIG
            # rebalance takes exactly 4 params: tokensIn, amountsIn, tokensOut,
            # amountsOut. No 5th "minAmountOut" array is smuggled in.
            assert len(kwargs["abi_params"]) == 4

    def test_circle_does_not_call_router_swap_directly(self, executor, mock_loader):
        """The executor never invokes AMMRouter.swap(min) itself — that primitive
        (and its min argument) is only ever reached via the vault's rebalance,
        which supplies the oracle-derived non-zero floor."""
        trade = _buy()
        with (
            patch.object(executor, "_validate_trade_liquidity", new=AsyncMock()),
            patch.object(executor, "_confirm_receipt", new=AsyncMock(return_value="0xtx")),
            patch("archimedes.chain.executor.circle_signer") as mock_signer,
        ):
            mock_signer.is_configured = True
            mock_signer.execute_contract = AsyncMock(return_value="0xtx")

            asyncio.run(executor.execute_trades("0xvault", [trade]))

            # No direct router.swap(...) call with a Python-chosen (possibly zero) min.
            mock_loader.amm_router.functions.swap.assert_not_called()


# ── #506: raw-key path routes through the same vault.rebalance(...) ────────────


class TestRawKeyRebalanceUsesOracleFloorSignature:
    def test_raw_key_builds_vault_rebalance(self, executor, mock_loader):
        """The raw-private-key path builds vault.functions.rebalance(...), the
        same on-chain-floor entrypoint as the Circle path — no AMMRouter.swap
        with a zero/None min on the Python side."""
        trade = _buy()

        # Give the executor a usable raw agent account.
        account = MagicMock()
        account.address = "0x000000000000000000000000000000000000dEaD"
        account.sign_transaction.return_value = MagicMock(raw_transaction=b"\x01" * 32)
        executor._mock_cc.settings.agent_account = account

        vault = mock_loader.vault.return_value
        vault.functions.rebalance.return_value.build_transaction = AsyncMock(
            return_value={"from": account.address, "nonce": 1, "gas": 2_000_000}
        )

        with (
            patch.object(executor, "_validate_trade_liquidity", new=AsyncMock()),
            patch.object(executor, "_confirm_receipt", new=AsyncMock(return_value="0xtx")),
            patch("archimedes.chain.executor.circle_signer") as mock_signer,
        ):
            mock_signer.is_configured = False

            asyncio.run(executor.execute_trades("0xvault", [trade]))

            # rebalance(...) was the entrypoint (positional 4-arg form: tokensIn,
            # amountsIn, tokensOut, amountsOut). The vault derives the slippage
            # floor; the executor passes no min.
            vault.functions.rebalance.assert_called_once()
            pos_args, _ = vault.functions.rebalance.call_args
            assert len(pos_args) == 4
            # And the executor did not bypass the vault by calling router.swap.
            mock_loader.amm_router.functions.swap.assert_not_called()
