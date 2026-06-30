"""Hermetic tests for the server-side rigor deploy gate (#818).

The guarantee "only rigor-passing strategies are deployed" must hold server-side,
where a direct (non-UI) API call cannot route around it. These pin: the resolver
reads the authoritative verdict across curated + generated sources, fails closed on
a DB error, and `create_vault` returns 422 (without spending gas) for a strategy
that failed the gate or was never validated.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from archimedes.api.vaults_routes import _assert_strategies_pass_rigor, _strategy_rigor_status
from fastapi import HTTPException

V = "archimedes.api.vaults_routes"


class _Strat:
    def __init__(self, passes):
        self.passes_rigor_gate = passes


# ── _strategy_rigor_status ────────────────────────────────────────────────


def test_status_curated_passing():
    with patch(f"{V}.strategy_provider.get_strategy", return_value=_Strat(True)):
        assert _strategy_rigor_status("s1") == (True, True)


def test_status_curated_failing():
    with patch(f"{V}.strategy_provider.get_strategy", return_value=_Strat(False)):
        assert _strategy_rigor_status("s1") == (True, False)


def test_status_fails_closed_on_db_error():
    # Not curated → falls to the DB; if the session raises, we must report not-found
    # (False, False) so the caller blocks the deploy rather than waving it through.
    with (
        patch(f"{V}.strategy_provider.get_strategy", return_value=None),
        patch("archimedes.db.get_session", side_effect=RuntimeError("db down")),
    ):
        assert _strategy_rigor_status("missing") == (False, False)


# ── _assert_strategies_pass_rigor ─────────────────────────────────────────


def test_assert_raises_422_on_failing():
    with patch(f"{V}._strategy_rigor_status", return_value=(True, False)), pytest.raises(HTTPException) as exc:
        _assert_strategies_pass_rigor(["s1"])
    assert exc.value.status_code == 422
    assert "rigor gate" in exc.value.detail


def test_assert_raises_422_on_not_found():
    with patch(f"{V}._strategy_rigor_status", return_value=(False, False)), pytest.raises(HTTPException) as exc:
        _assert_strategies_pass_rigor(["ghost"])
    assert exc.value.status_code == 422
    assert "not found" in exc.value.detail


def test_assert_passes_on_passing():
    with patch(f"{V}._strategy_rigor_status", return_value=(True, True)):
        _assert_strategies_pass_rigor(["s1", "s2"])  # no raise


def test_assert_empty_list_is_noop():
    _assert_strategies_pass_rigor([])  # nothing to validate → no raise


def test_assert_blocks_if_any_one_fails():
    # All must pass; one failing id blocks the whole deploy.
    def _status(sid):
        return (True, sid != "bad")

    with patch(f"{V}._strategy_rigor_status", side_effect=_status), pytest.raises(HTTPException) as exc:
        _assert_strategies_pass_rigor(["good", "bad", "good2"])
    assert exc.value.status_code == 422


# ── HTTP: the gate fires BEFORE the on-chain deploy ───────────────────────


async def test_create_vault_rejects_failing_strategy_before_deploy():
    from archimedes.api.auth_siwe import require_verified_wallet
    from archimedes.main import app
    from httpx import ASGITransport, AsyncClient

    app.dependency_overrides[require_verified_wallet] = lambda: "0x000000000000000000000000000000000000dEaD"
    try:
        with (
            patch(f"{V}._strategy_rigor_status", return_value=(True, False)),
            patch(f"{V}.chain_executor.create_vault") as mock_create,
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/vaults/create",
                    json={"name": "V", "symbol": "V", "strategy_ids": ["failing"]},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    assert "rigor gate" in resp.json()["detail"]
    mock_create.assert_not_called()  # never spent gas — gate fired first
