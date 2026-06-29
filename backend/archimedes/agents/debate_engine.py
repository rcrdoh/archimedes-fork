"""T1.1 — Multi-agent debate society (Phase 1 skeleton: additive + flag-gated).

Design of record: ``docs/specs/multi-agent-debate-spec.md`` (v2, staged
replacement). This is the strictly **additive** Phase-1 increment — a
``pipeline_name="debate"`` generation runner gated behind
``ARCHIMEDES_DEBATE_ENABLED`` (default OFF). While the flag is OFF the legacy
live path is byte-identical (the dispatch never reaches this module). The
society:

  1. **Proposer pool** — fans ``StrategyFusion(model=...).propose`` across
     ``select_candidates(regime_bias=R)`` evidence sets (the A3 model seam
     threads the user's Generate-page model pick; the steered selection is the
     cheap diversity axis). Drops non-actionable
     (``FusionProposal.is_actionable``) and non-conformant (``_dsl_conformance_ok``,
     fix A5) specs. ``pool_size = len(POOL)``.
  2. **Adversarial round** — a thin, best-effort bull/bear transcript (Phase 1).
     It surfaces the adversarial topology on the SSE stream but never gates;
     the deterministic critics do the real culling (the budget trick). The full
     rebuttal + LLM risk-debate is Phase 2.
  3. **C-rigor** — backtests EVERY survivor for real via ``evaluate_fusion_spec``
     (deterministic Python, 0 tokens), each wrapped in try/except (fix A5
     backstop), with ``num_trials=pool_size`` so the DSR multiple-testing
     correction counts the selection-from-pool search. This is the self-contained
     A1 deflation at the per-candidate evaluator — it coordinates with #770's
     ``library + N`` additive correction on the generation path rather than the
     library-grading external route, so it does not fight that PR.
  4. **C-null** — a survivor must beat the passive null (buy-and-hold) net of
     cost by ``MIN_COST_BENEFIT``. If none clears it → first-class ABSTAIN.
  5. **Synthesizer** — deterministic rank of the survivors (Phase 1 collapses the
     synthesizer to 0 LLM calls per spec §8) → top-N leaderboard; the user picks.

``_run_debate_candidate`` returns the **leader** ``_CandidateResult`` (carrier
contract preserving); the full leaderboard is built by ``build_leaderboard``
(directly unit-tested) and the Considered-Alternatives fan-out is Phase 2.

⚠️  PHASE-1 BLOCKER: ``ARCHIMEDES_DEBATE_ENABLED`` must stay OFF on the live path
until A1 (``pool_size`` → the external rigor gate, the OPEN Önder denominator)
is proven there — else the rigor badge can false-PASS. The flag-OFF additive
skeleton in this module is safe to merge.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

# Imported at module top: generation_pipeline does NOT import this module at top
# level (only lazily inside the dispatch), so there is no import cycle.
from archimedes.agents.generation_pipeline import (
    FusionUnavailable,
    _CandidateResult,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from archimedes.agents.generation_pipeline import _Emitter
    from archimedes.api.generate_schemas import GenerateBrief

logger = logging.getLogger(__name__)

# ── Env knobs ───────────────────────────────────────────────────────────────
_TRUE = {"1", "true", "yes", "on"}

# Phase-1 leaner steer set (regime axis). Phase 2 scales to ~15-20 across
# regime × mechanism × risk-appetite. None = unbiased; "bull"/"bear" map to
# strategy_fusion._REGIME_BIAS_TERMS.
_STEERS: tuple[str | None, ...] = ("bull", "bear", "bull", "bear", None)

# Indicator stems interpret_spec actually supports. ``realized_vol_N`` *validates*
# via validate_strategy_spec but raises DSLError("unsupported indicator") inside
# interpret_spec — which would throw in C-rigor. The conformance guard (fix A5)
# drops such specs from the pool BEFORE they reach evaluate_fusion_spec.
_CONFORMANT_INDICATORS = {"sma", "ema", "rsi", "momentum"}

# DSL price operands (not indicator aliases) — excluded from the conformance scan.
_PRICE_OPERANDS = {"close", "open", "high", "low", "volume"}

# C-null passive-null bar (V_check min_cost_benefit_bps = 5 bps): a survivor must
# beat buy-and-hold net of cost by at least this. Phase-1 proxy uses the
# backtest's own annualized edge (cagr); the explicit buy-and-hold differential
# is Phase 2.
MIN_COST_BENEFIT = 0.0005  # 5 bps


def debate_enabled() -> bool:
    """True iff ``ARCHIMEDES_DEBATE_ENABLED`` is set truthy (default OFF)."""
    return os.getenv("ARCHIMEDES_DEBATE_ENABLED", "").strip().lower() in _TRUE


def _pool_max() -> int:
    """``DEBATE_POOL_MAX`` clamped to [2, 24] (default 10 for Phase 1)."""
    try:
        return max(2, min(24, int(os.getenv("DEBATE_POOL_MAX", "10"))))
    except ValueError:
        return 10


class DebateUnavailable(FusionUnavailable):
    """The society produced no actionable + conformant + backtestable candidate.

    Subclasses ``FusionUnavailable`` so the existing ``run_generation`` fallback
    (``except FusionUnavailable``) relabels honestly to the agent path — no
    dispatch except-clause change is needed.
    """


# ── DSL conformance guard (fix A5) ───────────────────────────────────────────


def _indicator_alias_stems(spec: dict[str, Any]) -> set[str]:
    """Collect the indicator stems referenced as ``{indicator}_{period}`` operands.

    Walks the entry/exit condition trees. A string operand is an indicator alias
    iff it has a trailing ``_<int>`` (e.g. ``sma_50`` → ``sma``,
    ``realized_vol_5`` → ``realized_vol``). Price operands (``close`` …) and
    numeric operands are ignored.
    """
    stems: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and node not in _PRICE_OPERANDS:
            stem, sep, period = node.rpartition("_")
            if sep and stem and period.isdigit():
                stems.add(stem)

    walk(spec.get("entry"))
    walk(spec.get("exit"))
    return stems


def _dsl_conformance_ok(spec: dict[str, Any] | None) -> bool:
    """True iff ``spec`` is backtestable by ``interpret_spec`` (fix A5).

    Rejects specs whose indicator aliases fall outside ``{sma, ema, rsi,
    momentum}`` — those validate but raise ``DSLError`` at interpret time, which
    would otherwise throw inside C-rigor and take down the whole leaderboard
    build. A spec must also carry both an ``entry`` and an ``exit`` tree.
    """
    if not isinstance(spec, dict):
        return False
    if not isinstance(spec.get("entry"), dict) or not isinstance(spec.get("exit"), dict):
        return False
    return all(stem in _CONFORMANT_INDICATORS for stem in _indicator_alias_stems(spec))


# ── Viability precheck (mirrors generation_pipeline._fusion_can_run) ──────────


def _debate_can_run(brief: GenerateBrief) -> bool:
    """No-LLM viability precheck: flag on AND ≥ MIN_PAPERS for the steer.

    Never raises — any failure degrades to ``False`` so the caller falls back to
    the agent path. (Mirrors ``generation_pipeline._fusion_can_run``.)
    """
    if not debate_enabled():
        return False
    try:
        from archimedes.agents.strategy_fusion import (
            MIN_PAPERS,
            FusionBrief,
            fusion_enabled,
            load_corpus,
            select_candidates,
        )

        if not fusion_enabled():
            return False
        fb = FusionBrief(
            asset_classes=list(brief.asset_classes or []),
            risk_appetite=brief.risk_appetite,
            strategic_direction=brief.intent or "",
            max_papers=brief.max_papers,
        )
        return len(select_candidates(fb, load_corpus())) >= MIN_PAPERS
    except Exception:
        logger.debug("debate viability precheck failed; treating as not runnable", exc_info=True)
        return False


# ── Step 1 — proposer pool ────────────────────────────────────────────────────


async def _propose_pool(brief: GenerateBrief, model: str | None, corpus: list[Any]) -> list[Any]:
    """Fan ``StrategyFusion(model=...).propose`` across regime-steered evidence.

    Returns the POOL: proposals that are both *actionable*
    (``FusionProposal.is_actionable``) AND *conformant* (``_dsl_conformance_ok``).
    ``pool_size = len(returned list)`` is the DSR multiple-testing selection set.
    """
    from archimedes.agents.strategy_fusion import (
        MIN_PAPERS,
        FusionBrief,
        StrategyFusion,
        select_candidates,
    )

    fb = FusionBrief(
        asset_classes=list(brief.asset_classes or []),
        risk_appetite=brief.risk_appetite,
        strategic_direction=brief.intent or "",
        max_papers=brief.max_papers,
    )
    steers = list(_STEERS)[: _pool_max()]

    def _propose_one(regime_bias: str | None) -> Any:
        # Pre-build the steered evidence set (the caller-gap fix: select_candidates
        # accepts regime_bias but StrategyFusion.propose never threads it). The
        # proposer fuses over THIS steered set via the injected corpus.
        evidence = select_candidates(fb, corpus, regime_bias=regime_bias)
        if len(evidence) < MIN_PAPERS:
            return None
        return StrategyFusion(model=model, corpus=evidence).propose(fb)

    proposals = await asyncio.gather(
        *(asyncio.to_thread(_propose_one, r) for r in steers),
        return_exceptions=True,
    )

    pool: list[Any] = []
    for p in proposals:
        if isinstance(p, BaseException) or p is None:
            continue
        if p.is_actionable and _dsl_conformance_ok(p.strategy_spec):
            pool.append(p)
    return pool


# ── Step 2 — best-effort adversarial round (transcript only, never gates) ─────

_DEBATE_SYSTEM = (
    "You are the {role} researcher in a quant strategy debate. {stance}. "
    "Cite ONLY the listed candidate strategies. Reply with ONE JSON object: "
    '{{"verdict": "act"|"decline", "confidence": <0..1>, "key_claims": [<str>...]}}.'
)


async def _debate_round(pool: list[Any], model: str | None, emit: _Emitter, candidate_id: str) -> list[dict[str, Any]]:
    """Thin best-effort bull/bear round — transcript only, never gates (Phase 1).

    Surfaces the adversarial topology on the SSE stream. Any failure (no backend,
    unparseable output) degrades to a neutral transcript entry. The transcript is
    built in fixed [bull, bear] role order for R3 determinism (sort-before-hash).
    """
    from archimedes.agents.strategy_architect import extract_json
    from archimedes.services.llm_backend import make_llm_backend

    names = "; ".join(p.strategy_name for p in pool[:5] if p.strategy_name)
    transcript: list[dict[str, Any]] = []
    try:
        backend = make_llm_backend(model=model)
    except Exception:
        logger.debug("debate round skipped (backend construction failed)", exc_info=True)
        return transcript
    if not getattr(backend, "available", False):
        return transcript

    for role, stance in (
        ("bull", "Argue FOR acting on the strongest candidate"),
        ("bear", "Argue for ABSTENTION — the null is buy-and-hold; attack overfit/cost"),
    ):
        await emit.emit(
            "tool_called",
            candidate_id=candidate_id,
            tool_name=f"debate_{role}",
            args_summary=f"candidates: {names[:120]}",
        )
        try:
            raw = await asyncio.to_thread(backend.complete, _DEBATE_SYSTEM.format(role=role, stance=stance), names)
            parsed = extract_json(raw)
            transcript.append(
                {
                    "role": role,
                    "verdict": str(parsed.get("verdict", "n/a")),
                    "claims": list(parsed.get("key_claims") or parsed.get("fatal_flaws") or []),
                }
            )
        except Exception:
            transcript.append({"role": role, "verdict": "n/a", "claims": []})
    return transcript


# ── Step 3 — C-rigor (deterministic, real backtests) ──────────────────────────


async def _critic_rigor(pool: list[Any], num_trials: int) -> list[tuple[Any, Any]]:
    """Backtest every pooled spec for real; return ``[(proposal, eval_result)]``.

    ``num_trials=pool_size`` so the DSR deflation counts the selection-from-pool
    search (A1). Each ``evaluate_fusion_spec`` is wrapped in try/except so one bad
    spec (despite the A5 pre-guard) drops with an honest emit, never aborting the
    cohort.
    """
    from archimedes.services.fusion_evaluator import evaluate_fusion_spec

    def _backtest(proposal: Any) -> Any:
        try:
            return evaluate_fusion_spec(proposal.strategy_spec, num_trials=num_trials)
        except Exception as exc:
            logger.info("debate C-rigor: dropped a candidate on backtest error: %s", exc)
            return None

    results = await asyncio.gather(*(asyncio.to_thread(_backtest, p) for p in pool))
    out: list[tuple[Any, Any]] = []
    for proposal, ev in zip(pool, results, strict=True):
        if ev is not None and ev.success and ev.rigor is not None:
            out.append((proposal, ev))
    return out


# ── Step 4/5 — C-null + synthesize → leaderboard ──────────────────────────────


def _survives_null(ev: Any) -> bool:
    """C-null: the candidate beats the passive null net of cost by ≥ 5 bps.

    Phase-1 proxy: the backtest's own annualized edge (cagr) clears
    ``MIN_COST_BENEFIT``. The explicit buy-and-hold differential is Phase 2.
    """
    cagr = getattr(ev.backtest, "cagr", None)
    return cagr is not None and cagr > MIN_COST_BENEFIT


def _score(ev: Any) -> tuple[int, float, float]:
    """Deterministic leaderboard rank key: (passing, DSR, OOS Sharpe), desc."""
    r = ev.rigor
    dsr = r.dsr if r.dsr is not None else -1e18
    oos = r.oos_sharpe if r.oos_sharpe is not None else -1e18
    return (1 if r.passing else 0, dsr, oos)


def _rigor_verdict_dict(ev: Any) -> dict[str, Any]:
    """Build the passport ``rigor_verdict`` from a FusionEvalResult.

    Mirrors ``generation_pipeline._run_fusion_candidate``'s verdict shape so the
    passport renders identically for debate and fusion candidates.
    """
    r = ev.rigor
    bt = ev.backtest
    return {
        "dsr": r.dsr,
        "dsr_p_value": r.dsr_p_value,
        "pbo": r.pbo_score,
        "oos_sharpe": r.oos_sharpe,
        "in_sample_sharpe": r.in_sample_sharpe,
        "lookahead_audit_passed": bool(r.look_ahead_clean),
        "look_ahead_label": r.look_ahead_label,
        "num_trials": int(r.num_trials),  # == pool_size (A1)
        "passing": bool(r.passing),
        "data_source": r.data_source,
        "admissible": bool(ev.admissible),
        "sharpe_ratio": bt.sharpe_ratio,
        "sortino_ratio": bt.sortino_ratio,
        "max_drawdown": bt.max_drawdown,
        "cagr": bt.cagr,
        "calmar_ratio": bt.calmar_ratio,
        "win_rate": bt.win_rate,
        "total_trades": bt.total_trades,
    }


def _make_entry(candidate_id: str, proposal: Any, ev: Any, *, regime: str) -> _CandidateResult:
    """One leaderboard entry — a fully-populated ``_CandidateResult``.

    ``has_real_rigor=True`` (carries C-rigor's real backtest) so the downstream
    ``_patch_pbo`` and buy-and-hold gather correctly SKIP it (keyed on
    ``has_real_rigor``), preserving the CSCV PBO from ``evaluate_fusion_spec``.
    """
    spec = proposal.strategy_spec or {}
    return _CandidateResult(
        candidate_id=candidate_id,
        strategy_name=proposal.strategy_name or "Debate candidate",
        thesis=proposal.thesis,
        asset_universe=list(spec.get("asset_universe", []) or []),
        source_papers=[{"arxiv_id": a, "title": ""} for a in proposal.source_arxiv_ids],
        weights={},  # debate emits a DSL spec, not a static weight vector
        reasoning=proposal.fusion_reasoning or proposal.novelty_rationale or "",
        rigor_verdict=_rigor_verdict_dict(ev),
        passes_rigor=bool(ev.rigor.passing),
        regime=regime,
        generation_method="debate",
        source_arxiv_ids=list(proposal.source_arxiv_ids),
        has_real_rigor=True,
    )


def _abstain_result(candidate_id: str, *, regime: str, reason: str) -> _CandidateResult:
    """First-class ABSTAIN — a populated, SKIP-shaped ``_CandidateResult``.

    ``generation_method="debate_abstain"`` flows through the existing emit/persist
    path (and V_check's SKIP-trace mechanism); it is NOT a new error code.
    """
    return _CandidateResult(
        candidate_id=candidate_id,
        strategy_name="Debate — abstain (hold current weights)",
        thesis=reason,
        asset_universe=[],
        source_papers=[],
        weights={},
        reasoning=reason,
        rigor_verdict={
            "dsr": None,
            "pbo": None,
            "oos_sharpe": None,
            "in_sample_sharpe": None,
            "lookahead_audit_passed": False,
            "passing": False,
            "reason": reason,
        },
        passes_rigor=False,
        regime=regime,
        generation_method="debate_abstain",
        source_arxiv_ids=[],
        has_real_rigor=False,
    )


def build_leaderboard(rigor_results: list[tuple[Any, Any]], *, regime: str, base_id: str) -> list[_CandidateResult]:
    """Deterministic C-null cull + rank → the top-N leaderboard (leader first).

    Returns ``[abstain]`` when no candidate clears the passive null. The leader
    keeps ``base_id``; alternatives get ``base_id_alt{n}`` so the persist tail can
    distinguish them. Pure + deterministic — directly unit-tested.
    """
    survivors = [(p, ev) for (p, ev) in rigor_results if _survives_null(ev)]
    if not survivors:
        return [
            _abstain_result(
                base_id,
                regime=regime,
                reason="No candidate beat the passive null by ≥ 5 bps net of cost — abstaining (hold current weights).",
            )
        ]
    survivors.sort(key=lambda pe: _score(pe[1]), reverse=True)
    return [
        _make_entry(base_id if i == 0 else f"{base_id}_alt{i}", p, ev, regime=regime)
        for i, (p, ev) in enumerate(survivors)
    ]


# ── Runner (the dispatch entry point) ─────────────────────────────────────────


async def _run_debate_candidate(
    *,
    candidate_id: str,
    brief: GenerateBrief,
    emit: _Emitter,
    regime: str = "neutral",
    agent: Any = None,  # noqa: ARG001 — signature parity with the other runners
    model: str | None = None,
    selection_pool_size: int = 1,  # noqa: ARG001 — parity with the #770 runner contract; the debate computes its OWN pool_size (the real selection count) internally
) -> _CandidateResult:
    """Run the debate society once and return the leader ``_CandidateResult``.

    Carrier-contract preserving: returns a single ``_CandidateResult`` (the
    leader). The full leaderboard is built by ``build_leaderboard`` (testable);
    the Considered-Alternatives fan-out is Phase 2. Raises ``DebateUnavailable``
    (a ``FusionUnavailable`` subclass) when no candidate survives, so the existing
    run_generation fallback relabels to the agent path.

    ``selection_pool_size`` is accepted for parity with the #770 runner contract
    (the dispatch threads it to every runner), but the society ignores the passed
    value and uses its OWN internally-computed ``pool_size = len(POOL)`` — the
    actual count of conformant proposed specs, which is the correct DSR
    selection set, not the user's ``n_candidates``.
    """
    from archimedes.agents.strategy_fusion import load_corpus

    await emit.emit("agent_iteration", candidate_id=candidate_id, iteration_n=1, max_iterations=4)
    await emit.emit(
        "tool_called",
        candidate_id=candidate_id,
        tool_name="propose_pool",
        args_summary=f"steers={len(_STEERS)}, asset_classes={brief.asset_classes or '(any)'}",
    )

    corpus = await asyncio.to_thread(load_corpus)
    pool = await _propose_pool(brief, model, corpus)
    pool_size = len(pool)
    if pool_size == 0:
        raise DebateUnavailable("debate produced no actionable, DSL-conformant candidate (empty pool)")

    await emit.emit(
        "tool_result",
        candidate_id=candidate_id,
        tool_name="propose_pool",
        result_summary=f"pool_size={pool_size} actionable+conformant specs",
    )

    # Step 2 — best-effort adversarial transcript (never gates).
    await _debate_round(pool, model, emit, candidate_id)

    # Step 3 — C-rigor: backtest every survivor with num_trials = pool_size (A1).
    await emit.emit("agent_iteration", candidate_id=candidate_id, iteration_n=2, max_iterations=4)
    await emit.emit(
        "tool_called",
        candidate_id=candidate_id,
        tool_name="evaluate_fusion_spec",
        args_summary=f"backtest ×{pool_size}, num_trials={pool_size}",
    )
    rigor_results = await _critic_rigor(pool, pool_size)
    if not rigor_results:
        raise DebateUnavailable("debate: no candidate produced a successful backtest")

    # Steps 4/5 — C-null cull + deterministic synthesize → leaderboard.
    await emit.emit("agent_iteration", candidate_id=candidate_id, iteration_n=3, max_iterations=4)
    leaderboard = build_leaderboard(rigor_results, regime=regime, base_id=candidate_id)
    leader = leaderboard[0]
    await emit.emit(
        "tool_result",
        candidate_id=candidate_id,
        tool_name="synthesize",
        result_summary=(
            "ABSTAIN — no candidate beat the passive null"
            if leader.generation_method == "debate_abstain"
            else f"leader={leader.strategy_name} dsr={leader.rigor_verdict.get('dsr')} of {len(leaderboard)} entries"
        ),
    )
    return leader
