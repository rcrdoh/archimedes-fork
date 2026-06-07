"""Tests for selection_bias_routes — HTTP endpoints and schema validation.

Covers:
  - GET /api/selection-bias/gate  (library-level rigor gate)
  - GET /api/selection-bias/gate/{strategy_id}  (single-strategy gate)
  - POST /api/selection-bias/pbo  (pure-math PBO computation)
  - Pydantic schema construction and defaults
  - Pure helper functions (_load_strategy_code)

The GET /gate and GET /gate/{id} endpoints call init_db() internally; an
autouse fixture redirects DATABASE_URL to a per-test temporary SQLite file
so no persistent on-disk state is created and no external DB is required.
Tests pass with:
  env -i HOME=$HOME PATH=$PATH PYTHONPATH=backend python -m pytest \\
      backend/tests/test_selection_bias_routes.py -q
"""

from __future__ import annotations

import numpy as np
import pytest
from archimedes.api.selection_bias_routes import (
    PBORequest,
    PBOResponse,
    RigorGateDetail,
    RigorGateResponse,
    StrategyRigorResult,
    _load_strategy_code,
)
from httpx import ASGITransport, AsyncClient

# ── Hermetic DB fixture ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _use_tmp_db(tmp_path, monkeypatch):
    """Redirect DATABASE_URL to a per-test temp SQLite file.

    The evaluate_rigor_gate endpoint calls init_db() before querying
    persisted backtest data.  Without this fixture, init_db() falls back
    to sqlite:///./archimedes_chat.db (CWD-relative), which accumulates
    state across test runs and across parallel workers.  The fixture
    isolates every test and satisfies the hermetic-test mandate.
    """
    from archimedes.db import init_db

    db_path = tmp_path / "test_selection_bias.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    init_db()
    yield


# ── Schema unit tests ──────────────────────────────────────────────────


class TestRigorGateDetail:
    def test_default_values_are_missing(self):
        detail = RigorGateDetail()
        assert detail.dsr == "MISSING"
        assert detail.pbo == "MISSING"
        assert detail.oos_sharpe == "MISSING"
        assert detail.look_ahead == "MISSING"

    def test_custom_values_stored(self):
        detail = RigorGateDetail(
            dsr="PASS (p=0.98)",
            pbo="FAIL (PBO=0.6)",
            oos_sharpe="SET (OOS=1.2)",
            look_ahead="PASS",
        )
        assert detail.dsr == "PASS (p=0.98)"
        assert detail.pbo == "FAIL (PBO=0.6)"
        assert detail.oos_sharpe == "SET (OOS=1.2)"
        assert detail.look_ahead == "PASS"


class TestStrategyRigorResult:
    def test_required_fields_present(self):
        result = StrategyRigorResult(
            strategy_id="abc123",
            strategy_name="Test Strategy",
            passes_all=False,
            gate_details=RigorGateDetail(),
        )
        assert result.strategy_id == "abc123"
        assert result.strategy_name == "Test Strategy"
        assert result.passes_all is False

    def test_optional_fields_default_none(self):
        result = StrategyRigorResult(
            strategy_id="abc123",
            strategy_name="Test Strategy",
            passes_all=True,
            gate_details=RigorGateDetail(),
        )
        assert result.deflated_sharpe is None
        assert result.dsr_p_value is None
        assert result.pbo_score is None
        assert result.oos_sharpe is None
        assert result.in_sample_sharpe is None

    def test_optional_fields_accept_floats(self):
        result = StrategyRigorResult(
            strategy_id="abc123",
            strategy_name="Test Strategy",
            passes_all=False,
            gate_details=RigorGateDetail(),
            deflated_sharpe=1.23,
            dsr_p_value=0.97,
            pbo_score=0.2,
            oos_sharpe=0.8,
            in_sample_sharpe=1.5,
        )
        assert result.deflated_sharpe == pytest.approx(1.23)
        assert result.dsr_p_value == pytest.approx(0.97)
        assert result.pbo_score == pytest.approx(0.2)


class TestRigorGateResponse:
    def test_empty_library_response(self):
        resp = RigorGateResponse(strategies=[], total=0, passing=0, failing=0)
        assert resp.total == 0
        assert resp.passing == 0
        assert resp.failing == 0
        assert resp.strategies == []

    def test_counts_consistency(self):
        detail = RigorGateDetail()
        strats = [
            StrategyRigorResult(strategy_id=f"s{i}", strategy_name=f"S{i}", passes_all=(i == 0), gate_details=detail)
            for i in range(3)
        ]
        resp = RigorGateResponse(strategies=strats, total=3, passing=1, failing=2)
        assert resp.total == 3
        assert resp.passing == 1
        assert resp.failing == 2


class TestPBORequest:
    def test_default_s_partitions(self):
        req = PBORequest(returns_matrix={"s1": [0.001] * 50})
        assert req.s_partitions == 16

    def test_custom_s_partitions(self):
        req = PBORequest(returns_matrix={"s1": [0.001] * 50}, s_partitions=4)
        assert req.s_partitions == 4

    def test_matrix_stored(self):
        returns = [0.001, -0.002, 0.003]
        req = PBORequest(returns_matrix={"s1": returns})
        assert req.returns_matrix["s1"] == returns


class TestPBOResponse:
    def test_fields_stored(self):
        resp = PBOResponse(pbo_scores={"s1": 0.3, "s2": 0.3}, interpretation="PASSED rigor gate.")
        assert resp.pbo_scores["s1"] == pytest.approx(0.3)
        assert "PASSED" in resp.interpretation


# ── Pure helper function tests ──────────────────────────────────────────


class TestLoadStrategyCode:
    def test_nonexistent_path_returns_none(self):
        result = _load_strategy_code("/nonexistent/path/strategy.py")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _load_strategy_code("")
        assert result is None

    def test_none_returns_none(self):
        result = _load_strategy_code(None)
        assert result is None

    def test_path_traversal_blocked(self):
        result = _load_strategy_code("../../../../etc/passwd")
        assert result is None


# ── HTTP endpoint tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_endpoint_returns_200():
    """GET /api/selection-bias/gate returns 200."""
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/selection-bias/gate")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_gate_endpoint_has_required_top_level_keys():
    """Response body contains strategies, total, passing, failing."""
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/selection-bias/gate")
    data = resp.json()
    for key in ("strategies", "total", "passing", "failing"):
        assert key in data, f"missing key '{key}' in response: {list(data.keys())}"


@pytest.mark.asyncio
async def test_gate_endpoint_counts_are_consistent():
    """total == passing + failing and strategies list length matches total."""
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/selection-bias/gate")
    data = resp.json()
    assert data["total"] == data["passing"] + data["failing"]
    assert len(data["strategies"]) == data["total"]


@pytest.mark.asyncio
async def test_gate_endpoint_counts_non_negative():
    """total, passing, failing are all non-negative integers."""
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/selection-bias/gate")
    data = resp.json()
    assert data["total"] >= 0
    assert data["passing"] >= 0
    assert data["failing"] >= 0


@pytest.mark.asyncio
async def test_gate_endpoint_strategy_types():
    """strategy_id and strategy_name are strings; passes_all is bool."""
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/selection-bias/gate")
    data = resp.json()
    for strat in data["strategies"]:
        assert isinstance(strat["strategy_id"], str)
        assert isinstance(strat["strategy_name"], str)
        assert isinstance(strat["passes_all"], bool)


@pytest.mark.asyncio
async def test_gate_single_strategy_404_for_nonexistent():
    """GET /api/selection-bias/gate/{strategy_id} with unknown ID returns 404."""
    from archimedes.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/selection-bias/gate/nonexistent-id-that-doesnt-exist-xyz")
    assert resp.status_code == 404
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_pbo_endpoint_two_strategies_returns_200():
    """POST /api/selection-bias/pbo with valid two-strategy matrix returns 200."""
    from archimedes.main import app

    payload = {"returns_matrix": {"s1": [0.001] * 100, "s2": [-0.0005] * 100}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_pbo_endpoint_has_required_keys():
    """POST /api/selection-bias/pbo response has pbo_scores and interpretation."""
    from archimedes.main import app

    payload = {"returns_matrix": {"s1": [0.001] * 100, "s2": [-0.0005] * 100}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    data = resp.json()
    assert "pbo_scores" in data, f"missing 'pbo_scores' in {list(data.keys())}"
    assert "interpretation" in data, f"missing 'interpretation' in {list(data.keys())}"


@pytest.mark.asyncio
async def test_pbo_endpoint_scores_keyed_by_strategy_id():
    """pbo_scores dict contains entries for each submitted strategy."""
    from archimedes.main import app

    payload = {"returns_matrix": {"alpha": [0.001] * 100, "beta": [-0.0005] * 100}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    scores = resp.json()["pbo_scores"]
    assert "alpha" in scores
    assert "beta" in scores


@pytest.mark.asyncio
async def test_pbo_endpoint_scores_are_floats():
    """pbo_scores values are numeric and within [0, 1]."""
    from archimedes.main import app

    payload = {"returns_matrix": {"s1": [0.001] * 100, "s2": [-0.001] * 100}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    scores = resp.json()["pbo_scores"]
    for sid, score in scores.items():
        assert isinstance(score, (int, float)), f"score for {sid} is not numeric: {score}"
        assert 0.0 <= score <= 1.0, f"score for {sid} out of [0,1]: {score}"


@pytest.mark.asyncio
async def test_pbo_endpoint_interpretation_string():
    """interpretation field is a non-empty string."""
    from archimedes.main import app

    payload = {"returns_matrix": {"s1": [0.001] * 100, "s2": [-0.001] * 100}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    interpretation = resp.json()["interpretation"]
    assert isinstance(interpretation, str)
    assert len(interpretation) > 0


@pytest.mark.asyncio
async def test_pbo_endpoint_high_pbo_interpretation_says_failed():
    """PBO=1.0 is deterministic for s1-positive vs s2-negative constant returns.

    Constant series cause std=0 in every CSCV block, so _sharpe_per_col returns
    0.0 for both strategies via the safe_sigma=inf guard.  argsort([0,0]) is
    stable, assigning s1 (index 0) rank 1 (worst) out of 2.  omega=0.5/2=0.5,
    lambda=log(0.5/0.5)=0.0, which satisfies lam<=0, so every split votes for
    overfitting and PBO=1.0.
    """
    from archimedes.main import app

    payload = {"returns_matrix": {"s1": [0.001] * 100, "s2": [-0.001] * 100}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    data = resp.json()
    score = next(iter(data["pbo_scores"].values()))
    assert score == pytest.approx(1.0), f"expected PBO=1.0 for this payload, got {score}"
    assert "FAILED" in data["interpretation"]


@pytest.mark.asyncio
async def test_pbo_endpoint_low_pbo_interpretation_says_passed():
    """PBO=0.0 is deterministic when one strategy clearly dominates.

    With rng(42), 'good' (mean=+0.002, vol=0.003) dominates 'poor'
    (mean=-0.002, vol=0.01) on every IS/OOS split, so compute_pbo returns 0.0.
    """
    from archimedes.main import app

    rng = np.random.default_rng(42)
    good = rng.normal(0.002, 0.003, 300).tolist()
    poor = rng.normal(-0.002, 0.01, 300).tolist()
    payload = {"returns_matrix": {"good": good, "poor": poor}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    data = resp.json()
    score = next(iter(data["pbo_scores"].values()))
    assert score == pytest.approx(0.0), f"expected PBO=0.0 for dominant strategy, got {score}"
    assert "PASSED" in data["interpretation"]


@pytest.mark.asyncio
async def test_pbo_endpoint_single_strategy_returns_zero():
    """Single strategy -> compute_pbo returns 0.0 (no comparison possible)."""
    from archimedes.main import app

    payload = {"returns_matrix": {"s1": [0.001] * 100}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "pbo_scores" in data
    assert data["pbo_scores"].get("s1") == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_pbo_endpoint_short_series_edge_case():
    """Very short series (10 bars) with s_partitions=4 returns a valid response."""
    from archimedes.main import app

    payload = {
        "returns_matrix": {"s1": [0.001] * 10, "s2": [-0.001] * 10},
        "s_partitions": 4,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "pbo_scores" in data
    assert "interpretation" in data


@pytest.mark.asyncio
async def test_pbo_endpoint_three_strategies():
    """Three strategies are all present in pbo_scores output."""
    from archimedes.main import app

    payload = {
        "returns_matrix": {
            "strategy_a": [0.001] * 80,
            "strategy_b": [-0.0005] * 80,
            "strategy_c": [0.0002] * 80,
        }
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    assert resp.status_code == 200
    scores = resp.json()["pbo_scores"]
    assert set(scores.keys()) == {"strategy_a", "strategy_b", "strategy_c"}


@pytest.mark.asyncio
async def test_pbo_endpoint_custom_s_partitions():
    """s_partitions parameter is accepted and response remains valid."""
    from archimedes.main import app

    payload = {
        "returns_matrix": {"s1": [0.001] * 200, "s2": [-0.001] * 200},
        "s_partitions": 8,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/selection-bias/pbo", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "pbo_scores" in data
    assert isinstance(data["interpretation"], str)


@pytest.mark.asyncio
async def test_gate_endpoint_empty_provider(monkeypatch):
    """When provider returns no strategies, gate returns empty-list response."""
    from archimedes.api import selection_bias_routes
    from archimedes.main import app

    monkeypatch.setattr(selection_bias_routes._provider, "list_strategies", list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/selection-bias/gate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["passing"] == 0
    assert data["failing"] == 0
    assert data["strategies"] == []


@pytest.mark.asyncio
async def test_gate_endpoint_empty_provider_404_for_strategy(monkeypatch):
    """When provider returns no strategies, any strategy_id returns 404."""
    from archimedes.api import selection_bias_routes
    from archimedes.main import app

    monkeypatch.setattr(selection_bias_routes._provider, "get_strategy", lambda sid: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/selection-bias/gate/any-id-at-all")
    assert resp.status_code == 404
