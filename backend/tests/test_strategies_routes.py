"""Tests for strategies_routes — the library-list rigor badge (#821).

The user-facing ``passes_rigor_gate`` badge (and the CANDIDATE → VALIDATED 🏆
promotion) on ``GET /api/strategies/`` must come from a LIVE ``run_rigor_gate``
verdict computed on the strategy's persisted real returns — the SAME machinery
the ``/api/selection-bias/gate`` route uses — NOT from the stored fixture boolean
in ``analytics-engine/strategies/backtest_fixtures.json``. A strategy with no real
returns surfaces an explicit ``pending`` badge, never a fixture ``True``/``False``.

These tests mock at the DB boundary (``get_all_daily_returns``) — the persisted
real-returns source — and assert the served badge equals an independently-computed
``run_rigor_gate`` verdict on the same returns.

Hermetic gate:
  env -i HOME=$HOME PATH=$PATH PYTHONPATH=backend python -m pytest \\
      backend/tests/test_strategies_routes.py -q
"""

from __future__ import annotations

import numpy as np
import pytest
from archimedes.services.live_rigor_gate import (
    FAIL,
    PASS,
    PENDING,
    RigorGateVerdict,
    verdict_from_returns,
)
from archimedes.services.rigor_evaluator import (
    compute_average_pairwise_correlation,
    compute_pbo,
    run_rigor_gate,
)
from httpx import ASGITransport, AsyncClient

# ── Hermetic DB fixture ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path, monkeypatch):
    """Redirect DATABASE_URL to a per-test temp SQLite file.

    The list endpoint calls init_db() (via verdicts_for_strategies) before
    querying persisted backtest data. Isolating the DB per test satisfies the
    hermetic-test mandate and prevents cross-run state.
    """
    from archimedes.db import init_db

    db_path = tmp_path / "test_strategies_routes.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    init_db()
    yield


# A clean strategy snippet that passes the AST look-ahead audit (no future/peek
# access). Real curated strategy files also pass; this keeps the test independent
# of any particular file on disk.
_CLEAN_CODE = "def init(self):\n    self.sma = 0\n"


def _passing_series(seed: int = 0, n: int = 500) -> list[float]:
    """A return series engineered to clear the live gate when paired with a
    cohort (≥2 strategies for PBO) + clean code (look-ahead pass)."""
    return np.random.default_rng(seed).normal(0.0015, 0.004, n).tolist()


def _failing_series(seed: int = 99, n: int = 500) -> list[float]:
    """Pure-noise series — negative/zero drift, high vol — that the gate fails."""
    return np.random.default_rng(seed).normal(0.0, 0.02, n).tolist()


# ── live_rigor_gate unit tests (the single source of truth) ─────────────


class TestVerdictFromReturns:
    def test_no_returns_is_pending(self):
        v = verdict_from_returns("s", [])
        assert v.status == PENDING
        assert v.passes is False
        assert v.source == "pending"

    def test_too_few_returns_is_pending(self):
        # Below the 10-obs floor the gate cannot run → pending, NOT a boolean.
        v = verdict_from_returns("s", [0.01] * 9)
        assert v.status == PENDING
        assert v.passes is False

    def test_pending_source_is_never_fixture(self):
        # The whole point of #821: pending must never be a stored boolean.
        v = verdict_from_returns("s", [])
        assert v.source != "fixture"

    def test_real_returns_yield_live_verdict_not_boolean(self):
        # With real returns the verdict comes from run_rigor_gate, not a constant.
        a = _passing_series(0)
        b = _passing_series(1)
        pbo = compute_pbo({"a": a, "b": b})
        v = verdict_from_returns("a", a, num_trials=2, pbo_scores=pbo, strategy_code=_CLEAN_CODE)
        expected = run_rigor_gate("a", a, num_trials=2, pbo_scores=pbo, strategy_code=_CLEAN_CODE)
        assert v.passes == expected.passes_all
        assert v.status == (PASS if expected.passes_all else FAIL)
        assert v.source == "live_gate"

    def test_noise_series_fails_live_gate(self):
        v = verdict_from_returns("noise", _failing_series(), num_trials=4)
        assert v.status == FAIL
        assert v.passes is False

    def test_gate_exception_fails_closed_to_pending(self, monkeypatch):
        # If run_rigor_gate raises, the badge must NOT claim a pass.
        def _boom(*a, **k):
            raise RuntimeError("gate exploded")

        monkeypatch.setattr("archimedes.services.rigor_evaluator.run_rigor_gate", _boom)
        # verdict_from_returns is already imported at module top; patching the source
        # module's run_rigor_gate (which it imports locally) is what makes this work.
        v = verdict_from_returns("s", _passing_series(), num_trials=2)
        assert v.status == PENDING
        assert v.passes is False


class TestRigorGateVerdict:
    def test_passes_only_truthy_for_pass(self):
        assert RigorGateVerdict.passed().passes is True
        assert RigorGateVerdict.failed().passes is False
        assert RigorGateVerdict.pending().passes is False

    def test_status_labels(self):
        assert RigorGateVerdict.passed().status == PASS
        assert RigorGateVerdict.failed().status == FAIL
        assert RigorGateVerdict.pending().status == PENDING


# ── Acceptance #1: served badge == live run_rigor_gate verdict ──────────


@pytest.mark.asyncio
async def test_library_badge_equals_live_gate_verdict_on_persisted_returns(monkeypatch):
    """ACCEPTANCE #1: the library-list ``passes_rigor_gate`` for a real strategy
    equals the live ``run_rigor_gate`` verdict computed on its persisted returns.

    We inject known persisted returns at the DB boundary (get_all_daily_returns),
    serve the real ``GET /api/strategies/`` endpoint, then independently recompute
    the gate verdict over the SAME returns (same num_trials / cohort PBO /
    avg-correlation the route derives) and assert every served badge matches.
    """
    from archimedes.api import strategies_routes as sr
    from archimedes.main import app

    strategies = sr.strategy_provider.list_strategies()
    assert len(strategies) >= 2, "need ≥2 curated strategies for a PBO cohort"

    # Give the first two real strategies persisted returns: one engineered to
    # pass, one engineered to fail. The rest get no returns (→ pending).
    s_pass, s_fail = strategies[0], strategies[1]
    returns = {s_pass.id: _passing_series(0), s_fail.id: _failing_series()}

    # Patch the DB boundary used by verdicts_for_strategies (imported inside the
    # function body, so patch the definition module).
    monkeypatch.setattr(
        "archimedes.services.backtest_repository.get_all_daily_returns",
        lambda session, ids: dict(returns),
    )
    # Make the look-ahead audit deterministic (clean code → pass) for both.
    monkeypatch.setattr(
        "archimedes.services.live_rigor_gate._load_strategy_code_safe",
        lambda strategy: _CLEAN_CODE,
    )

    # Independently reproduce the route's library context.
    valid = {k: v for k, v in returns.items() if len(v) >= 10}
    pbo_scores = compute_pbo(valid) if len(valid) >= 2 else {}
    num_trials = max(len(valid), 1)
    avg_corr = compute_average_pairwise_correlation(valid) if len(valid) >= 2 else 0.0

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/strategies/?limit=100")
    assert resp.status_code == 200
    by_id = {s["id"]: s for s in resp.json()["strategies"]}

    for sid, series in returns.items():
        expected = run_rigor_gate(
            strategy_id=sid,
            daily_returns=series,
            num_trials=num_trials,
            pbo_scores=pbo_scores,
            strategy_code=_CLEAN_CODE,
            in_sample_sharpe=None,
            average_correlation=avg_corr,
        )
        served = by_id[sid]
        assert served["passes_rigor_gate"] == expected.passes_all, (
            f"served badge for {sid} ({served['passes_rigor_gate']}) != live gate verdict ({expected.passes_all})"
        )
        assert served["rigor_gate_status"] == (PASS if expected.passes_all else FAIL)

    # The engineered pass strategy passes; the noise strategy fails — on the LIVE path.
    assert by_id[s_pass.id]["passes_rigor_gate"] is True
    assert by_id[s_fail.id]["passes_rigor_gate"] is False


# ── Acceptance #2: no real returns → pending, not a fixture boolean ─────


@pytest.mark.asyncio
async def test_strategy_without_real_returns_is_pending(monkeypatch):
    """ACCEPTANCE #2: a strategy with NO persisted returns surfaces a ``pending``
    badge — never a fixture True/False. We force the DB to return nothing for
    every strategy, so the live gate cannot run for any of them."""
    from archimedes.main import app

    monkeypatch.setattr(
        "archimedes.services.backtest_repository.get_all_daily_returns",
        lambda session, ids: {},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/strategies/?limit=100")
    assert resp.status_code == 200
    served = resp.json()["strategies"]
    assert served, "expected curated strategies in the library"

    # EVERY strategy is pending with passes_rigor_gate=False — including the two
    # strategies whose FIXTURE value is True (moreira_muir, moskowitz_ooi_pedersen).
    # If the fixture boolean were still the source, those two would read True.
    for s in served:
        assert s["rigor_gate_status"] == PENDING, f"{s['id']} not pending: {s['rigor_gate_status']}"
        assert s["passes_rigor_gate"] is False, f"{s['id']} leaked a non-live pass badge"


@pytest.mark.asyncio
async def test_fixture_true_strategies_do_not_read_true_without_live_returns(monkeypatch):
    """The two fixture-True strategies (moreira_muir, moskowitz_ooi_pedersen) must
    NOT show passes_rigor_gate=True purely from the fixture: with no live returns
    they are ``pending``. This is the direct anti-regression for #821."""
    from archimedes.api import strategies_routes as sr
    from archimedes.main import app

    monkeypatch.setattr(
        "archimedes.services.backtest_repository.get_all_daily_returns",
        lambda session, ids: {},
    )

    # Resolve the deterministic strategy ids for the two fixture-True stems.
    by_path = {}
    for s in sr.strategy_provider.list_strategies():
        by_path[s.strategy_code_path or ""] = s
    fixture_true_stems = ("moreira_muir_2017_volatility_managed", "moskowitz_ooi_pedersen_2012_tsmom")
    targets = [s for path, s in by_path.items() if any(stem in path for stem in fixture_true_stems)]
    assert targets, "could not resolve the fixture-True strategies"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/strategies/?limit=100")
    by_id = {s["id"]: s for s in resp.json()["strategies"]}

    for t in targets:
        served = by_id[t.id]
        assert served["passes_rigor_gate"] is False, f"{t.id} read fixture True on the live path"
        assert served["rigor_gate_status"] == PENDING


# ── CANDIDATE → VALIDATED promotion is live, not fixture-driven ─────────


@pytest.mark.asyncio
async def test_validated_promotion_only_when_live_gate_passes(monkeypatch):
    """A CANDIDATE is promoted to VALIDATED only when the LIVE gate passes on real
    returns — not because a fixture said so. With no live returns, every CANDIDATE
    stays CANDIDATE (no fixture-driven 🏆)."""
    from archimedes.main import app

    monkeypatch.setattr(
        "archimedes.services.backtest_repository.get_all_daily_returns",
        lambda session, ids: {},
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/strategies/?limit=100")
    served = resp.json()["strategies"]

    # No live returns → no strategy may be served as "validated" purely from a fixture.
    for s in served:
        if s["rigor_gate_status"] == PENDING:
            assert s["status"] != "validated", f"{s['id']} promoted to validated without a live pass"


@pytest.mark.asyncio
async def test_validated_promotion_fires_on_live_pass(monkeypatch):
    """When the live gate passes on persisted returns for a CANDIDATE strategy, the
    served status is promoted to VALIDATED."""
    from archimedes.api import strategies_routes as sr
    from archimedes.main import app
    from archimedes.models.strategy import StrategyStatus

    strategies = sr.strategy_provider.list_strategies()
    candidates = [s for s in strategies if s.status == StrategyStatus.CANDIDATE]
    assert len(candidates) >= 2, "need ≥2 CANDIDATE strategies"
    s_pass = candidates[0]
    cohort = candidates[1]
    returns = {s_pass.id: _passing_series(0), cohort.id: _passing_series(1)}

    monkeypatch.setattr(
        "archimedes.services.backtest_repository.get_all_daily_returns",
        lambda session, ids: dict(returns),
    )
    monkeypatch.setattr(
        "archimedes.services.live_rigor_gate._load_strategy_code_safe",
        lambda strategy: _CLEAN_CODE,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/strategies/?limit=100")
    by_id = {s["id"]: s for s in resp.json()["strategies"]}

    if by_id[s_pass.id]["passes_rigor_gate"]:
        assert by_id[s_pass.id]["status"] == "validated"


# ── Endpoint smoke + schema shape ───────────────────────────────────────


@pytest.mark.asyncio
async def test_list_endpoint_returns_200_and_status_field():
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/strategies/?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "strategies" in data and "total" in data
    for s in data["strategies"]:
        assert s["rigor_gate_status"] in (PASS, FAIL, PENDING)
        assert isinstance(s["passes_rigor_gate"], bool)
