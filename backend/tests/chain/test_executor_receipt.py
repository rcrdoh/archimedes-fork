"""Executor: rebalance must confirm the receipt and raise on revert (#6).

Previously execute_trades sent the tx and returned the hash without waiting,
so a reverted rebalance was logged as "sent" and recorded as a success — the
agent then published a REBALANCE trace for a trade that never settled. These
tests pin _confirm_receipt's behavior with a mocked w3.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from archimedes.chain.executor import ChainExecutor, TradeRevertedError


def _executor_with_receipt(status: int) -> ChainExecutor:
    """ChainExecutor whose w3.eth.wait_for_transaction_receipt returns `status`."""
    executor = ChainExecutor(loader=MagicMock())
    fake_w3 = MagicMock()
    fake_w3.eth.wait_for_transaction_receipt = AsyncMock(return_value={"status": status})
    fake_w3.to_bytes = MagicMock(return_value=b"\x00" * 32)
    return executor, fake_w3


@pytest.mark.asyncio
async def test_confirm_receipt_raises_on_revert():
    executor, fake_w3 = _executor_with_receipt(status=0)
    with patch("archimedes.chain.executor.chain_client") as cc:
        cc.w3 = fake_w3
        with pytest.raises(TradeRevertedError):
            await executor._confirm_receipt("0xabc123")


@pytest.mark.asyncio
async def test_confirm_receipt_returns_hash_on_success():
    executor, fake_w3 = _executor_with_receipt(status=1)
    with patch("archimedes.chain.executor.chain_client") as cc:
        cc.w3 = fake_w3
        result = await executor._confirm_receipt("0xabc123")
    assert result == "0xabc123"


@pytest.mark.asyncio
async def test_confirm_receipt_normalizes_unprefixed_hash():
    executor, fake_w3 = _executor_with_receipt(status=1)
    with patch("archimedes.chain.executor.chain_client") as cc:
        cc.w3 = fake_w3
        result = await executor._confirm_receipt("abc123")
    assert result.startswith("0x")


@pytest.mark.asyncio
async def test_confirm_receipt_accepts_bytes_input():
    """Raw-key signer path: tx_hash is HexBytes (subclass of bytes), not str.

    Pins the bytes branch at executor.py:162-165 — the actual production
    code path for raw-key signing, which the str-only tests above did not
    cover.
    """
    from hexbytes import HexBytes

    executor, fake_w3 = _executor_with_receipt(status=1)
    tx_hash_bytes = HexBytes("0x" + "ab" * 32)  # 32-byte tx hash
    with patch("archimedes.chain.executor.chain_client") as cc:
        cc.w3 = fake_w3
        result = await executor._confirm_receipt(tx_hash_bytes)
    # HexBytes input → normalized 0x-prefixed hex string out
    assert isinstance(result, str)
    assert result.startswith("0x")
    assert result == "0x" + "ab" * 32


@pytest.mark.asyncio
async def test_confirm_receipt_raises_on_revert_with_bytes_input():
    """Revert detection must work on the bytes (raw-key signer) path too."""
    from hexbytes import HexBytes

    executor, fake_w3 = _executor_with_receipt(status=0)
    tx_hash_bytes = HexBytes("0x" + "cd" * 32)
    with patch("archimedes.chain.executor.chain_client") as cc:
        cc.w3 = fake_w3
        with pytest.raises(TradeRevertedError, match="0x" + "cd" * 32):
            await executor._confirm_receipt(tx_hash_bytes)
