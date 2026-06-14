"""Regression for the swap-quote raw-exception leak (audit 2026-06-14).

GET /api/swap/quote used to return ``detail=f"Quote failed: {e!s}"`` — echoing
the raw chain/web3 exception (RPC internals, contract addresses, revert reasons)
to the client. The same leak class was fixed in vaults/portfolio routes (#605);
this file pins the swap path to a generic message + server-side logging.

Hermetic: the contract loader is patched at the boundary to raise a
secret-bearing exception; no chain, no RPC.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

_LEAK_MARKER = "RPC node 10.0.3.7 reverted: insufficient-reserve at 0xDEADBEEF"


@pytest.mark.asyncio
async def test_quote_failure_returns_generic_message_not_raw_exception():
    from archimedes.main import app

    with patch(
        "archimedes.chain.contracts.get_contract_loader",
        side_effect=RuntimeError(_LEAK_MARKER),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/swap/quote",
                params={
                    "token_in": "0x1111111111111111111111111111111111111111",
                    "token_out": "0x2222222222222222222222222222222222222222",
                    "amount_in": 100,
                },
            )

    assert resp.status_code == 400, resp.text
    # The raw exception text (addresses, revert reason, internal IPs) must NOT
    # appear in the response body.
    assert _LEAK_MARKER not in resp.text
    assert "0xDEADBEEF" not in resp.text
    assert resp.json()["detail"] == "Quote failed — check the token pair and amount."
