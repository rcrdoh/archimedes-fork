"""Hermetic tests for the T1.1 debate society (Phase 1 skeleton).

No live LLM / Redis / Postgres / Arc RPC. The proposer/critic LLM seams are
mocked at the boundary (``make_llm_backend`` / ``evaluate_fusion_spec``); the
deterministic cull/rank/abstain logic is tested directly against fake
``FusionEvalResult``-shaped objects.

Covers spec §9 Phase-1 tests:
  1. canned society → leaderboard, every entry has_real_rigor=True
  2. regime divergence (fix A4): bull vs bear evidence sets differ (Jaccard < 1)
  3. ABSTAIN → populated SKIP-shaped result (generation_method="debate_abstain")
  4. DebateUnavailable on empty pool → honest fallback signal (subclass)
  5. pool_size → num_trials (fix A1): evaluate_fusion_spec called with pool_size
  6. model threading (fix A3): FusionProposal.model reflects the user pick
  7. DSL conformance (fix A5): realized_vol_N dropped, no DSLError escapes
  8. flag-OFF byte-identical (fix A2): _pick_pipeline never returns "debate" OFF
  9. cited-paper union non-empty; transcript in fixed role order (R3 determinism)
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from archimedes.agents import debate_engine as de
from archimedes.agents.strategy_fusion import FusionBrief, StrategyFusion, load_corpus, select_candidates
from archimedes.api.generate_schemas import GenerateBrief

# ── Fixture corpus: 3 momentum-flavored + 3 defensive-flavored + 1 noise ──────

_MOMENTUM_ROWS = [
    {
        "arxiv_id": f"2401.0000{i}",
        "title": f"Cross-Sectional Equity Momentum and Trend Following {i}",
        "authors": ["A. Mom"],
        "primary_category": "q-fin.PM",
        "categories": ["q-fin.PM"],
        "published": f"2024-01-0{i}",
        "updated": f"2024-01-0{i}",
        "abstract": "Momentum, trend-following, breakout and carry factor alpha in the cross-section of equities.",
        "pdf_url": f"http://x/m{i}",
        "pdf_sha256": "a" * 64,
        "pdf_path": f"data/corpus/pdfs/2401.0000{i}.pdf",
        "text_path": f"data/corpus/text/2401.0000{i}.txt",
        "fetched_at": "2026-05-16T00:00:00Z",
    }
    for i in (1, 2, 3)
]

_DEFENSIVE_ROWS = [
    {
        "arxiv_id": f"2402.0000{i}",
        "title": f"Volatility-Managed Defensive Hedging {i}",
        "authors": ["B. Def"],
        "primary_category": "q-fin.PM",
        "categories": ["q-fin.PM"],
        "published": f"2024-02-0{i}",
        "updated": f"2024-02-0{i}",
        "abstract": "Volatility, vol-managed defensive hedge tail risk drawdown and mean-reversion overlays.",
        "pdf_url": f"http://x/d{i}",
        "pdf_sha256": "b" * 64,
        "pdf_path": f"data/corpus/pdfs/2402.0000{i}.pdf",
        "text_path": f"data/corpus/text/2402.0000{i}.txt",
        "fetched_at": "2026-05-16T00:00:00Z",
    }
    for i in (1, 2, 3)
]

_ALL_ROWS = _MOMENTUM_ROWS + _DEFENSIVE_ROWS


@pytest.fixture
def corpus(tmp_path):
    p = tmp_path / "manifest.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in _ALL_ROWS), encoding="utf-8")
    return load_corpus(p)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts with both flags explicitly cleared."""
    monkeypatch.delenv("ARCHIMEDES_DEBATE_ENABLED", raising=False)
    monkeypatch.delenv("ARCHIMEDES_FUSION_ENABLED", raising=False)
    monkeypatch.delenv("ARCHIMEDES_CORPUS_MANIFEST", raising=False)
    monkeypatch.delenv("DEBATE_POOL_MAX", raising=False)


# ── Canned backends ───────────────────────────────────────────────────────────

_CONFORMANT_SPEC = {
    "name": "Momentum/vol fusion",
    "asset_universe": ["SPY"],
    "rebalance_frequency": "monthly",
    "entry": {"gt": ["momentum_20", 0]},
    "exit": {"lt": ["close", "sma_200"]},
    "position_sizing": {"type": "full_invested_when_in_market"},
    "look_ahead_safe": True,
    "parameter_variants": {"momentum": [10, 20, 40]},
}

_NONCONFORMANT_SPEC = {
    "name": "Realized-vol trap",
    "asset_universe": ["SPY"],
    "rebalance_frequency": "monthly",
    "entry": {"gt": ["realized_vol_5", 0.2]},  # validates but raises DSLError at interpret
    "exit": {"lt": ["close", "sma_200"]},
    "position_sizing": {"type": "full_invested_when_in_market"},
    "look_ahead_safe": True,
}


class _CannedFusionBackend:
    """Returns a parseable fusion of the first 2 candidate papers + a spec.

    ``served_model`` is derived from the requested model so the A3 model-threading
    test can prove the user's pick flowed through.
    """

    def __init__(self, model=None, *, spec=None):
        self.model_id = model or "env-default"
        self.served_model = f"served::{self.model_id}"
        self.available = True
        self._spec = spec if spec is not None else _CONFORMANT_SPEC

    def complete(self, system: str, user: str) -> str:
        payload = json.loads(user)
        ids = [p["arxiv_id"] for p in payload["candidate_papers"][:2]]
        spec = dict(self._spec)
        spec["source_arxiv_ids"] = ids
        return json.dumps(
            {
                "strategy_name": "Debate canned fusion",
                "thesis": "Fuse momentum + vol mechanisms.",
                "source_arxiv_ids": ids,
                "fusion_reasoning": "canned",
                "novelty_rationale": "canned",
                "risk_notes": "canned",
                "strategy_spec": spec,
            }
        )


# ── Fake FusionEvalResult-shaped objects (deterministic critic inputs) ────────


def _fake_ev(*, cagr, dsr=1.5, passing=True, oos=1.2, num_trials=5):
    rigor = SimpleNamespace(
        dsr=dsr,
        dsr_p_value=0.01,
        pbo_score=0.1,
        oos_sharpe=oos,
        in_sample_sharpe=1.3,
        look_ahead_clean=True,
        look_ahead_label="clean",
        num_trials=num_trials,
        passing=passing,
        data_source="synthetic",
        admissible=False,
    )
    bt = SimpleNamespace(
        sharpe_ratio=1.4,
        sortino_ratio=1.6,
        max_drawdown=-0.1,
        cagr=cagr,
        calmar_ratio=1.1,
        win_rate=0.55,
        total_trades=42,
    )
    return SimpleNamespace(rigor=rigor, backtest=bt, success=True, admissible=False, error=None, spec={})


def _fake_proposal(name, ids, spec=None):
    return SimpleNamespace(
        strategy_name=name,
        thesis="thesis",
        source_arxiv_ids=ids,
        strategy_spec=spec or dict(_CONFORMANT_SPEC),
        fusion_reasoning="reasoning",
        novelty_rationale="novelty",
        is_actionable=True,
    )


class _FakeEmit:
    def __init__(self):
        self.events = []

    async def emit(self, name, **kw):
        self.events.append((name, kw))


# ── Test 1 — leaderboard build, every entry has_real_rigor=True ───────────────


def test_build_leaderboard_all_entries_have_real_rigor():
    rigor_results = [
        (_fake_proposal("A", ["2401.00001", "2402.00001"]), _fake_ev(cagr=0.2, dsr=2.0)),
        (_fake_proposal("B", ["2401.00002", "2402.00002"]), _fake_ev(cagr=0.1, dsr=1.0)),
    ]
    board = de.build_leaderboard(rigor_results, regime="neutral", base_id="cand_1")
    assert len(board) == 2
    assert all(e.has_real_rigor for e in board)
    assert all(e.generation_method == "debate" for e in board)
    # Leader is the higher-DSR candidate and keeps the base id.
    assert board[0].strategy_name == "A"
    assert board[0].candidate_id == "cand_1"
    assert board[1].candidate_id == "cand_1_alt1"


# ── Test 2 — regime divergence (fix A4) ───────────────────────────────────────


def test_regime_steers_diverge_on_fixture_corpus(monkeypatch, corpus):
    # Isolate the KEYWORD+bias divergence guarantee (fix A4). The semantic rerank
    # (FUSION_SEMANTIC_RETRIEVAL, default ON) keys on strategic_direction — IDENTICAL
    # for both steers — so on a degraded/TF-IDF corpus it re-sorts bull and bear to
    # the SAME order and ERASES the divergence. That collapse is precisely the
    # diversity-theater risk the spec flags (§4): genuine divergence needs real
    # embeddings (#778). The bias-at-the-keyword-core guarantee is what must hold now.
    monkeypatch.setenv("FUSION_SEMANTIC_RETRIEVAL", "false")
    brief = FusionBrief(asset_classes=[], strategic_direction="systematic equity strategy", max_papers=3)
    bull = {p.arxiv_id for p in select_candidates(brief, corpus, regime_bias="bull")}
    bear = {p.arxiv_id for p in select_candidates(brief, corpus, regime_bias="bear")}
    assert bull and bear
    # Jaccard < 1.0 — the steers must NOT collapse to the same tail.
    jaccard = len(bull & bear) / len(bull | bear)
    assert jaccard < 1.0


# ── Test 3 — ABSTAIN path ─────────────────────────────────────────────────────


def test_abstain_when_no_candidate_beats_passive_null():
    # Every candidate's edge (cagr) is below the 5 bps null bar → abstain.
    rigor_results = [
        (_fake_proposal("A", ["2401.00001", "2402.00001"]), _fake_ev(cagr=0.0)),
        (_fake_proposal("B", ["2401.00002", "2402.00002"]), _fake_ev(cagr=0.0001)),
    ]
    board = de.build_leaderboard(rigor_results, regime="neutral", base_id="cand_1")
    assert len(board) == 1
    abstain = board[0]
    assert abstain.generation_method == "debate_abstain"
    assert abstain.has_real_rigor is False
    assert abstain.passes_rigor is False
    assert abstain.weights == {}
    assert "abstain" in abstain.strategy_name.lower()


# ── Test 4 — DebateUnavailable on empty pool ──────────────────────────────────


async def test_empty_pool_raises_debate_unavailable(monkeypatch):
    from archimedes.agents.generation_pipeline import FusionUnavailable

    async def _empty_pool(*a, **k):
        return []

    monkeypatch.setattr(de, "_propose_pool", _empty_pool)
    monkeypatch.setattr(de.asyncio, "to_thread", _passthrough_to_thread)

    brief = GenerateBrief(intent="momentum equities")
    with pytest.raises(de.DebateUnavailable) as exc:
        await de._run_debate_candidate(candidate_id="cand_1", brief=brief, emit=_FakeEmit())
    # Subclasses FusionUnavailable so the existing fallback relabels to agent.
    assert isinstance(exc.value, FusionUnavailable)


async def _passthrough_to_thread(fn, *a, **k):
    return fn(*a, **k)


# ── Test 5 — pool_size → num_trials (fix A1) ──────────────────────────────────


async def test_critic_rigor_threads_pool_size_as_num_trials(monkeypatch):
    seen_num_trials = []

    def _fake_eval(spec, *, num_trials=None, **kw):
        seen_num_trials.append(num_trials)
        return _fake_ev(cagr=0.2, num_trials=num_trials)

    monkeypatch.setattr("archimedes.services.fusion_evaluator.evaluate_fusion_spec", _fake_eval)
    monkeypatch.setattr(de.asyncio, "to_thread", _passthrough_to_thread)

    pool = [_fake_proposal(f"P{i}", [f"id{i}a", f"id{i}b"]) for i in range(3)]
    pool_size = len(pool)
    results = await de._critic_rigor(pool, pool_size)

    assert seen_num_trials == [pool_size, pool_size, pool_size]
    # And the persisted verdict echoes pool_size as the DSR denominator.
    board = de.build_leaderboard(results, regime="neutral", base_id="cand_1")
    assert board[0].rigor_verdict["num_trials"] == pool_size


# ── Test 6 — model threading (fix A3) ─────────────────────────────────────────


def test_model_pick_threads_into_served_model(monkeypatch, corpus):
    monkeypatch.setenv("ARCHIMEDES_FUSION_ENABLED", "1")
    captured = {}

    def _fake_make(model=None, **kw):
        captured["model"] = model
        return _CannedFusionBackend(model=model)

    monkeypatch.setattr("archimedes.agents.strategy_fusion.make_llm_backend", _fake_make)

    brief = FusionBrief(asset_classes=[], strategic_direction="momentum", max_papers=4)
    proposal = StrategyFusion(model="user-model-x", corpus=corpus).propose(brief)

    assert captured["model"] == "user-model-x"
    assert proposal.requested_model == "user-model-x"  # what we asked for (backend.model_id)
    assert proposal.model == "served::user-model-x"  # the TRUE served model (field of record)
    assert proposal.is_actionable


# ── Test 7 — DSL conformance (fix A5) ─────────────────────────────────────────


def test_dsl_conformance_guard_rejects_realized_vol():
    assert de._dsl_conformance_ok(_CONFORMANT_SPEC) is True
    assert de._dsl_conformance_ok(_NONCONFORMANT_SPEC) is False
    assert de._dsl_conformance_ok(None) is False
    assert de._dsl_conformance_ok({"name": "no trees"}) is False


async def test_propose_pool_drops_nonconformant_specs(monkeypatch, corpus):
    monkeypatch.setenv("ARCHIMEDES_FUSION_ENABLED", "1")

    def _fake_make(model=None, **kw):
        return _CannedFusionBackend(model=model, spec=_NONCONFORMANT_SPEC)

    monkeypatch.setattr("archimedes.agents.strategy_fusion.make_llm_backend", _fake_make)
    monkeypatch.setattr(de.asyncio, "to_thread", _passthrough_to_thread)

    brief = GenerateBrief(intent="momentum equities", max_papers=4)
    pool = await de._propose_pool(brief, "m", corpus)
    # Every proposal emitted realized_vol_5 → all dropped by the A5 guard; no DSLError.
    assert pool == []


# ── Test 8 — flag-OFF byte-identical (fix A2) ─────────────────────────────────


def test_pick_pipeline_never_returns_debate_when_flag_off(monkeypatch):
    from archimedes.agents.generation_pipeline import _pick_pipeline

    monkeypatch.delenv("ARCHIMEDES_DEBATE_ENABLED", raising=False)
    brief = GenerateBrief(intent="momentum equities")
    name, _reason = _pick_pipeline(brief, mode_override="debate")
    assert name != "debate"
    assert name in ("fusion", "architect", "agent")


def test_pick_pipeline_returns_debate_when_flag_on(monkeypatch):
    from archimedes.agents.generation_pipeline import _pick_pipeline

    monkeypatch.setenv("ARCHIMEDES_DEBATE_ENABLED", "1")
    brief = GenerateBrief(intent="momentum equities")
    name, reason = _pick_pipeline(brief)
    assert name == "debate"
    assert "ARCHIMEDES_DEBATE_ENABLED" in reason


# ── Test 9 — cited-paper union non-empty; transcript fixed role order ─────────


def test_leaderboard_entries_carry_cited_papers():
    rigor_results = [
        (_fake_proposal("A", ["2401.00001", "2402.00001"]), _fake_ev(cagr=0.2)),
    ]
    board = de.build_leaderboard(rigor_results, regime="neutral", base_id="cand_1")
    union = {a for e in board for a in e.source_arxiv_ids}
    assert union == {"2401.00001", "2402.00001"}


async def test_debate_round_transcript_in_fixed_role_order(monkeypatch):
    monkeypatch.setattr(
        "archimedes.services.llm_backend.make_llm_backend", lambda model=None, **k: _CannedFusionBackend(model=model)
    )
    monkeypatch.setattr(de.asyncio, "to_thread", _passthrough_to_thread)

    pool = [_fake_proposal("A", ["2401.00001", "2402.00001"])]
    transcript = await de._debate_round(pool, "m", _FakeEmit(), "cand_1")
    # Best-effort round still produces a deterministic [bull, bear] ordering.
    assert [t["role"] for t in transcript] == ["bull", "bear"]
