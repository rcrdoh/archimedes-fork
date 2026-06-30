# T1.1 — Multi-Agent Debate Engine Spec

**Status:** design / not yet built · **Owner:** Dan Browne · **Track:** Lepton Tier-1 vertical (Agentic Sophistication, 30%)
**Slot-in:** `pipeline_name="debate"` runner in `backend/archimedes/agents/generation_pipeline.py`
**Flag:** `ARCHIMEDES_DEBATE_ENABLED` (default OFF) · **Last verified against source:** 2026-06-26

This is a complete, self-contained design. It synthesizes three competing proposals (TradingAgents-faithful, lean-pragmatic, fusion-ensemble-critic) into one recommended architecture, grafting the best of each.

---

## 0. Source-of-truth corrections (verified against the code, not the briefs)

Two claims in the upstream current-state map were wrong. Both are confirmed below by direct grep, and both *change* the design — so they are stated up front:

1. **`evaluate_fusion_spec()` EXISTS** — `backend/archimedes/services/fusion_evaluator.py:578`. It runs `validate → interpret → backtest → rigor gate` and returns `FusionEvalResult{spec, backtest, rigor, error}` with `.is_actionable` / `.admissible` properties. `_run_fusion_candidate` already calls it (`generation_pipeline.py:839`). **Consequence:** the debate's real-DSL-backtest path is *reuse*, not build-new. This is the single biggest cost saver in the whole design.
2. **`dual_regime` is a `regime_bias` parameter, not a function** — `select_candidates(brief, corpus, regime_bias=...)` at `strategy_fusion.py:389`, driven by `_REGIME_BIAS_TERMS` at `:133`. **Consequence:** a bull-grounded vs. bear-grounded evidence set is free — call the same function twice with opposite biases.

Verified integration line numbers (current `generation_pipeline.py`): `_pick_pipeline` allowlist `:84` · dispatch block `:1053` · `FusionUnavailable` `:751` · `_fusion_can_run` `:113` · `_patch_pbo` skip `:440` · buy-and-hold gather skip `:1251` · episodic `agent=` ternary `:1265`. Re-exported regime-conditional rigor: `regime_robustness_score` / `regime_conditional_sharpe` / `regime_conditional_dsr` at `rigor_evaluator.py:44-46`. External gate `run_rigor_gate` at `rigor_evaluator.py:463`.

---

## 1. TL;DR + recommendation

**Recommended architecture: a structured adversarial debate with deterministic critics — "Proposer → Bull/Bear research round → deterministic critic panel (incl. GMM-regime risk) → LLM synthesizer," run once per Generate over a shared embargoed/time-decayed evidence surface, emitting N=2–3 regime-steered candidates of which exactly one goes deep.** It is wired as a new `pipeline_name="debate"` runner (`_run_debate_candidate`), a fourth peer to the existing fusion/live/fixture runners, with three edit sites and zero schema/route/persistence changes.

**Why this over the alternatives.** This grafts the three proposals deliberately:

- **From Proposal A (TradingAgents-faithful):** the genuine adversarial *topology* — a real bull-vs-bear research round with rebuttal, a moderator/synthesizer, and first-class ABSTAIN — because that is what scores on Lepton's Agentic-Sophistication axis. A naked ensemble (all critics scoring independently, no cross-agent argument) under-delivers the "multi-agent debate" the roadmap names.
- **From Proposal B (lean):** the **deterministic risk agent**. The Hierarchy-of-Truth protocol (Xia §4.4) says the regime/vault state is *non-votable* — it must override consensus structurally. An LLM risk agent can be argued out of its position; a Python gate cannot. This is both a correctness win (non-votable truth enforced in code) and the load-bearing budget win (the risk work costs zero tokens). Also from B: building shared evidence *once* and caching it across regime steers, and letting the synthesizer collapse to zero LLM calls when the deterministic floor already forces the outcome.
- **From Proposal C (fusion-ensemble):** the **deterministic critic panel** pattern (rigor-backtest, regime-risk, passive-null, embargo/provenance critics are *code, not models*), the `evaluate_fusion_spec` real-backtest spine, and the strict `num_trials = len(candidate_pool)` wiring on the external gate — the single most important number in the integration.

**What we reject from each:** A's full 9-role, 12-call roster (4× budget directly fights primitive #5's affordability reason — deferred to a stretch phase, not the ship). The pure-ensemble framing of C (no visible cross-agent argument under-sells the Agentic-Sophistication axis — we keep *one* bounded rebuttal round). B's "skip the rebuttal entirely" (we keep one round for the demo's sophistication story, but make it cheap).

**The synthesis in one line:** *N>1 diversity is bought in the cheap dimension (regime-steered grounding + adversarial reasoning over shared evidence), the deterministic critics do the risk work for zero tokens, exactly one candidate goes through deep generation + the external rigor gate, and the whole panel collapses into one canonical provenance hash — so K=1's two protected invariants (deep-generation cost, single re-derivable provenance) survive untouched.*

---

## 2. Agent roster + roles

Seven logical roles. **Only 3–4 are LLM calls**; the four critics are deterministic Python (the budget trick, grafted from Proposals B and C). Every LLM role constructs through `make_llm_backend(model=...)` and parses with `architect.extract_json` — they are *prompt modes over the shared seam*, not new backends. Every cited claim is run through the existing anti-hallucination `valid_ids` filter (fusion) so no fabricated paper enters the debate record.

| # | Role | LLM? | Reuses | Behavior |
|---|------|------|--------|----------|
| **P** | **Proposer** | yes (1 call / regime-steer) | `StrategyFusion.propose()` → `select_candidates(brief, corpus, regime_bias=R)`; `extract_json`; fusion `valid_ids` filter | Emits ONE candidate Archimedes-DSL `strategy_spec` grounded in a regime-biased paper set. Status-honest: returns `{status:'insufficient'}` rather than inventing if <2 papers support a coherent thesis. |
| **R1** | **Bull researcher** | yes (1 call) | `extract_json`; inline empirical stats from `_agent_tools` (`_tool_get_asset_stats`/corr/stress, computed in Python, fed as text) | Argues FOR acting on the candidate, citing only the proposer's papers + the inline stats. Round 2 sees the Bear's prior turn (rebuttal). Output `{verdict:'act', confidence, key_claims:[…], strongest_evidence_id}`. |
| **R2** | **Bear researcher** | yes (1 call) | same | Argues for ABSTENTION — the null is buy-and-hold. Cites the StockBench base rate (active LLM agents underperform passive baselines; our own agent ranked #15/15). Attacks overfit / regime-fragility / cost-vs-benefit (<5 bps ⇒ don't trade). **Structurally privileged toward abstention.** Output `{verdict:'decline'|'act', confidence, fatal_flaws:[…]}`. |
| **C-prov** | **Provenance/Embargo critic** | **no** | `embargo_filter`, `time_aware_retrieval`, `source_tracker`, fusion `valid_ids` | Hard-fails any candidate citing a post-embargo paper or an arxiv_id not in the shared decay-weighted surface. Enforces Xia 1/2/4. Non-votable. |
| **C-rigor** | **Rigor-backtest critic** | **no** | `evaluate_fusion_spec()` (`fusion_evaluator.py:578`) | Runs the candidate's spec → real DSL backtest → DSR/PBO/OOS. Produces `FusionEvalResult`. Deterministic; cannot be argued with. This is the spine that keeps deep generation at K=1 (one real backtest, not N). |
| **C-regime** | **GMM-regime risk critic** | **no** | `GmmRegimeDetector.get_current_regime()`; `regime_robustness_score`/`regime_conditional_sharpe` | Reads the live exogenous regime; penalizes candidates whose edge collapses in the *current* regime, rewards regime-robust ones. Discounts its own weight when `gmm_regime_health().status=="degraded"`. **The non-votable Hierarchy-of-Truth gate** — crisis/degraded biases the panel toward decline regardless of consensus. |
| **C-null** | **Passive-null critic ("StockBench skeptic")** | **no** | `V_check`'s `min_cost_benefit_bps≥5`; buy-and-hold baseline | The standing "do nothing" debater. A candidate survives only if it beats buy-and-hold net of cost by ≥5 bps. If none clears it → ABSTAIN (first-class SKIP). |
| **S** | **Synthesizer / Fund manager** | yes (1 call, or **0** — §8) | `extract_json`; `_CandidateResult` builder | Reads survivors + each critic's structured scorecard + the bull/bear transcript; picks the winner OR abstains; writes the human-readable "why this beat the others" rationale that populates Considered Alternatives. **Collapses to zero LLM calls when the deterministic floor already forces the outcome** (crisis/degraded, or no candidate clears the null). |

### Prompt sketches (the load-bearing discipline, borrowed from `strategy_architect._SYSTEM_PROMPT` + `strategy_fusion`)

**Proposer (P):**
> *System:* "You are a quant strategy proposer. You may ONLY fuse the papers in the provided candidate set `[arxiv_ids…]`. Invent no papers, no Sharpe ratios. You are arguing the **{regime}** case — favor {momentum/trend/carry | vol-managed/defensive/hedge/tail-risk} mechanisms grounded in these papers. Your peers argue the opposite; differentiate honestly, do not strawman. Emit a single Archimedes-DSL `strategy_spec` JSON. If <2 papers support a coherent thesis, return `{status:'insufficient'}` — do not guess."

**Bull (R1):**
> *System:* "You are the BULL. Argue FOR acting on this candidate. Empirical stats: {Sharpe, vol, maxDD, ρ from `_tool_get_asset_stats`/corr/stress}. {round≥2: Your opponent argued: <bear_claims>. Respond directly.} Cite only the proposer's papers + these stats. Output `{verdict:'act', confidence, key_claims:[…], strongest_evidence_id}`."

**Bear (R2):**
> *System:* "You are the BEAR. The null is buy-and-hold. The empirical base rate is that active LLM agents underperform passive baselines on most windows — our own Strategy-Generation agent ranked #15/15 on StockBench (Sortino −0.91 vs the raw model's +1.94). Attack overfit, regime-fragility, and cost-vs-benefit (<5 bps net ⇒ DON'T trade). {round≥2: The bull argued: <bull_claims>. Rebut.} Abstention is a correct and respected verdict. Output `{verdict:'decline'|'act', confidence, fatal_flaws:[…]}`."

**Synthesizer (S):**
> *System:* "You are an impartial fund manager. Below are the surviving candidates, each with a deterministic scorecard from four critics (rigor, regime-risk, passive-null, provenance), plus the bull/bear transcript. Pick the single best risk-adjusted, regime-robust, cost-justified candidate — OR ABSTAIN. **ABSTAIN ('hold current weights') is first-class and often correct**; if no candidate beats the passive null by ≥5 bps net, OR the regime critic flags crisis/degraded, you MUST output `{decision:'abstain'}`. On-chain vault state and curated-over-uncurated evidence OVERRIDE any consensus — you cannot vote past deterministic truth. Cite only the critics' numbers; invent nothing. Output `{winner_id | 'ABSTAIN', rationale, per_candidate_reject_reason{}}`."

---

## 3. Control / debate flow

```
run_generation(brief, mode="debate")  ──pipeline_name="debate"──►  _run_debate_candidate(*, candidate_id, brief, emit, regime, agent)
                                                                    (called ONCE; owns the whole panel; regimes collapses to ["neutral"])
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ONE shared decision t  ·  ONE embargo+time-aware retrieval surface  ·  ONE consulted-hash union  (Xia 1,2,4)        │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                                    │
  STEP 0 — SHARED EVIDENCE (built ONCE per Generate, cached across all steers — the budget win)
     corpus = load_corpus()
     corpus = embargo_filter(corpus, t)                 # Xia 1  (one decision t shared by all agents)
     corpus = time_aware_retrieval(corpus, regime, λ)   # Xia 2  (decay + regime scaling, identical for every agent)
     for R in {bull, bear[, neutral]}:                   # the ONLY thing that varies per steer — pure Python, free
         evidence[R] = select_candidates(brief, corpus, regime_bias=R)   # strategy_fusion.py:389
     valid_ids = sorted(union of evidence[R] arxiv_ids)
     consulted_hashes = sorted("arxiv_id:content_hash" for paper in valid_ids)   # Xia 4
     emit candidates_selected(source_arxiv_ids=valid_ids)
                                                                    │
  STEP 1 — PROPOSE  (N cheap LLM calls — the only N× cost; asyncio.gather)
     ┌────────────┐  ┌────────────┐  [┌────────────┐]
     │ Proposer   │  │ Proposer   │   │ Proposer    │   each = StrategyFusion.propose(brief, regime_bias=R)
     │  bull      │  │  bear      │   │  neutral    │   → strategy_spec ; valid_ids anti-hallucination filter on EACH
     └─────┬──────┘  └─────┬──────┘   [└─────┬──────┘]   status='insufficient' on all ⇒ raise DebateUnavailable → agent fallback
           │ spec_bull     │ spec_bear      │ spec_neutral
     emit agent_iteration / tool_called("propose") per proposer
                                                                    │  candidate pool  (+ inline empirical stats, computed once)
  STEP 2 — RESEARCH DEBATE  (ONE adversarial round, R=1 default; Bull ∥ Bear via asyncio.gather)
     ┌── R1 BULL ──┐   ┌── R2 BEAR (+passive null framing) ──┐    each sees SAME candidates + SAME stats
     │ argue ACT   │◄─►│ argue DECLINE                       │    round 2 (optional): each sees the other's claims (rebuttal)
     └──────┬──────┘   └──────────────┬─────────────────────┘    emit agent_iteration(iteration_n=round) per turn
            └────────────┬────────────┘
                                                                    │  debate_transcript (sorted by fixed role order before hashing)
  STEP 3 — CRITIC PANEL  (DETERMINISTIC — ZERO LLM CALLS)
     for each candidate:
        C-prov   embargo/id audit ───────────────► hard FAIL ⇒ drop (Xia 1,2,4, non-votable)
        C-rigor  evaluate_fusion_spec(spec) ──────► real DSL backtest → FusionEvalResult{DSR,PBO,OOS}
        C-regime GmmRegimeDetector.get_current_regime() + regime_robustness_score ──► regime-conditional score (Xia 3)
        C-null   beats buy-and-hold by ≥5 bps net? ► else flag (StockBench honesty floor)
     survivors = [c for c if not hard-failed]
     emit tool_result per (candidate × critic)   # the audit trail
                                                                    │
  STEP 4 — SYNTHESIZE / ADJUDICATE  (1 LLM call — or 0 if the floor forces it)
     if no survivor clears C-null  OR  C-regime flags crisis/degraded:  ───────────► ABSTAIN  (mechanical, 0 LLM)
     else:  Synthesizer(survivors, scorecards, transcript) ─► winner_id + rationale + per-reject reason
     emit agent_iteration("synthesize")
                                                                    │
  build ONE _CandidateResult(
       generation_method="debate"  (or "debate_abstain"),
       has_real_rigor=True,                      # winner carries C-rigor's real backtest
       rigor_verdict=<from evaluate_fusion_spec>,
       source_arxiv_ids=<winner papers>, source_papers=<union>,   reasoning=<synth rationale>,
       debate_transcript=[…], consulted_paper_hashes=<union>)
  losers → Considered Alternatives (with per-critic / synth reject rationale)
                                                                    │  returns _CandidateResult (the existing contract — unchanged)
                                                                    ▼
  ════════ run_generation TAIL — UNCHANGED ════════
  _patch_pbo SKIPS it (has_real_rigor) · best_selected · _persist_candidate · persist_proposal(agent="debate") · backtest gather SKIPS it · done
                                                                    │
  ════════ EXTERNAL RIGOR GATE — primitive #5, OUTSIDE the debate ════════
  GET /api/selection-bias/gate/{winner_id} → run_rigor_gate(
        strategy_id, daily_returns, strategy_code,
        num_trials = len(candidate_pool),   ◄── FULL debate pool, NOT 1 (DSR multiple-testing correction)
        library_pbo=…, average_correlation=…)
  → RigorGateResult{passes_all, gate_details}  ──renders on passport──►  enables Deploy
  ════════ V_check (deterministic floor) ════════
  weights_sum_bps==10000 ∧ max_concentration≤60% ∧ cost_benefit≥5bps  ──fail──► SKIP trace published (even on unanimous APPROVE)
```

**Reproducibility (R3):** agent ordering is fixed and deterministic; the Bull∥Bear concurrency is collapsed back to a fixed role order before the transcript is hashed. The transcript, each agent's `consulted_paper_hashes`, and their union go into one trace. No nondeterministic fan-out.

---

## 4. How N>1 diverse candidates emerge + how the winner is chosen + K=1 reconciliation

**Diversity axis (cheap, the only N× cost):** regime-steered grounding. `select_candidates(brief, corpus, regime_bias="bull")` ranks momentum/trend/carry/breakout papers to the top; `"bear"` ranks vol-managed/defensive/hedge/tail-risk/min-variance papers (driven by `_REGIME_BIAS_TERMS:133`). Same embargo, same decay surface, same decision `t` — the divergence is in *which decay-weighted papers rank top*, never in reaching past the decay to a stale paper (that's a C-prov hard-fail, not a stronger argument). Default ship: **N=2** (bull/bear); generalizes to **N=3** (+neutral) or risk-appetite steers, bounded by `DEBATE_N` (hard cap 5, reusing the existing `n_candidates` 1..5 ceiling).

**Winner selection:** the deterministic critic panel culls (C-prov hard-fail → C-rigor real backtest → C-regime conditioning → C-null cost-benefit). The surviving pool feeds the LLM synthesizer, which picks one OR abstains. **Exactly ONE candidate goes deep** — the winner carries the one real DSL backtest (`evaluate_fusion_spec`) and the one `return_series`. We do **not** run N independent deep generations.

**Reconciliation with primitive #5 (K=1) — explicit:**

| What #5 protects | How it survives N>1 |
|---|---|
| **Deep-generation cost** (reason #5.1) | Only the winner gets a real backtest. Proposers are cheap single `complete()` calls emitting one DSL spec each over a small grounded set; the critics are deterministic (0 tokens). Diversity is bought in the cheap reasoning/grounding dimension, not in N× expensive synthesis. |
| **Single re-derivable provenance** (reason #5.2) | ONE `methodology_hash` per Generate carrying the **union** of all proposers' `consulted_paper_hashes` + the debate transcript, anchored once via `ReasoningTraceRegistry`. N>1 surfaces in the UI; provenance stays K=1-clean. |
| **Considered-Alternatives panel** (#5 user surface) | The debate's losing candidates *become* the considered-rejects — a richer version at the same architectural slot, carrying inter-agent reject rationale, at near-zero extra cost. |
| **External rigor gate** | The winner — and only the winner — goes through the unchanged external `run_rigor_gate`. The debate never self-certifies. |
| **Episodic compounding** | The full candidate set + verdicts persist to `strategy_proposals` via the unchanged `persist_proposal` tail (`agent="debate"`). |

One line: *N>1 lives at the cheap debate-over-shared-evidence layer; K=1 survives at the deep-generation + external-rigor-gate + single-anchored-provenance layer.*

---

## 5. Integration

### 5a. `generation_pipeline.run_generation` — new `pipeline_name="debate"` runner (Option A, mirrors fusion exactly)

This is the cleanest slot-in, confirmed against source. **Three edit sites, no schema/route/persistence changes.**

1. **Allowlist** (`_pick_pipeline`, `:84`): `("fusion","architect","agent")` → `("fusion","architect","agent","debate")`. Add `"debate"` to `GenerateStartRequest.mode` docstring (`generate_schemas.py:32`). Phase 1 is **opt-in via `mode="debate"` only** — the default path stays byte-identical, de-risking the ship.
2. **Dispatch block** (`:1053`, peer to the fusion branch):
   ```python
   if pipeline_name == "debate":
       if use_live and _debate_can_run(brief):     # mirror _fusion_can_run (:113); requires >= MIN_PAPERS
           runner = _run_debate_candidate
       else:
           pipeline_name = "agent"; runner = agent_runner   # honest relabel, same as fusion
   ```
   When `pipeline_name=="debate"`, also set `regimes = ["neutral"]` so the per-regime loop (`:1037`/`:1117`) runs **once** — the debate panel owns its own internal bull/bear/neutral split. (This is Proposal C's "regime collapse"; it keeps the expensive PBO/backtest/persist tail untouched and the panel a single self-contained unit.)
3. **New `_run_debate_candidate`** + `DebateUnavailable(Exception)` (mirror `FusionUnavailable:751` so the existing `:1127` fallback catches it → relabels to agent → honest `pipeline_selected`). Set `generation_method="debate"`; extend the episodic `agent=` ternary at `:1265` to `"debate"`.

**Exact signature (all five kwargs required):**
```python
async def _run_debate_candidate(
    *, candidate_id: str, brief: GenerateBrief, emit: _Emitter,
    regime: str = "neutral", agent: Any = None,
) -> _CandidateResult: ...
```

**Returned `_CandidateResult`:** fully populated per the existing contract. For the winner, set `has_real_rigor=True` (so `_patch_pbo:440` and the buy-and-hold gather `:1251` both correctly skip it — the CSCV PBO from `evaluate_fusion_spec` must not be clobbered). For ABSTAIN, return a populated result with empty `weights`, a passive-baseline `return_series`, and an abstain `rigor_verdict` stub — this does **not** hit the empty-guard (which would wrongly emit a `NO_CANDIDATES` error); it is a first-class SKIP.

**Streaming:** emit `agent_iteration` / `tool_called` / `tool_result` per role, reusing the existing SSE vocabulary → **zero frontend changes**. (New event names would require `EventName` + listener edits; avoid.)

**New files:** `backend/archimedes/agents/debate_engine.py` (runner + `DebateUnavailable` + `_debate_can_run` + the deterministic critics + the synthesizer adapter). **Reused unchanged:** `strategy_fusion.py` (`select_candidates`, `propose`), `strategy_architect.py` (`extract_json`, prompt template), `fusion_evaluator.py` (`evaluate_fusion_spec`), `llm_backend.py` (`make_llm_backend`), `gmm_regime_detector.py`, `rigor_evaluator.py`, `strategy_memory.py` (`persist_proposal`).

### 5b. GMM-regime risk-agent input (Surface 1, in-process Path A)

The deterministic **C-regime** critic reads:
```python
detector = GmmRegimeDetector(fallback=VixRegimeDetector())
rc = detector.get_current_regime()          # RegimeClassification | None
# or cross-process: rc = await AgentStateStore().load_regime()
degraded = gmm_regime_health().status == "degraded"
```
Branch on `rc.regime` (4-way: `risk_on|risk_off|transition|crisis`), weight by `rc.confidence`, react to `rc.regime_changed`, and **discount when degraded** (treat as lower confidence, bias toward decline — honest degradation per contract). Score each candidate's regime-conditional edge via `regime_robustness_score` / `regime_conditional_sharpe` (the bridge between Surface 1 and Surface 2). **Never** read `KEY_ENSEMBLE_CONSENSUS` as a market regime (that is endogenous consensus, issue #659). Because C-regime is deterministic Python, the regime gate is structurally non-votable — Xia §4.4 enforced.

### 5c. External rigor gate (Surface 2, primitive #5 — stays OUTSIDE the debate)

The debate emits a candidate; the existing external path adjudicates. The authoritative verdict is `GET /api/selection-bias/gate/{winner_id}`:
```python
gate_result = run_rigor_gate(
    strategy_id=winner.candidate_id,
    daily_returns=winner.return_series,
    num_trials=len(candidate_pool),     # ◄── FULL debate pool, NOT 1, NOT library size
    library_pbo=library_pbo,
    strategy_code=winner_strategy_code,
    average_correlation=avg_correlation,
)
deploy_enabled = gate_result.passes_all
```
**The single most important number in the integration: `num_trials = len(candidate_pool)`.** A debate *introduces* exactly the multiple-testing inflation DSR is meant to deflate; passing `num_trials=1` silently disables the correction and produces a *false* strict-rigor badge — the "build on sand" failure. **Assert `num_trials == pool_size` in a test** and surface the pool size on the passport. `gate_details` (per-criterion PASS/FAIL with `source=library|cohort`) renders on the passport; `passes_all` gates Deploy. The debate never sets `passing` itself.

---

## 6. Enforced Xia protocols mapping

| # | Protocol | Where enforced in the debate | Non-votable? |
|---|----------|------------------------------|--------------|
| 1 | **Outcome Embargo** (§4.2) | STEP 0 builds the surface through `embargo_filter(corpus, t)` once; all agents share one decision `t`. **C-prov** hard-fails any candidate citing a post-`t` paper. | yes |
| 2 | **Time-Aware Retrieval** (§4.2) | STEP 0 `time_aware_retrieval(corpus, regime, λ)` once; every proposer draws from the same decay-weighted, regime-scaled surface. Diversity = reasoning over shared evidence; reaching past the decay is a **C-prov** hard-fail. | yes |
| 3 | **Hierarchy of Truth** (§4.4) | **C-regime is deterministic Python** — regime/vault state structurally override consensus; crisis/degraded biases toward decline regardless of what the bull argues. On-chain vault state + curated-over-uncurated outrank any synthesis. | yes |
| 4 | **Source Tracking** (§4.3) | Every cited claim runs through the fusion `valid_ids` filter. The **union** of all agents' `consulted_paper_hashes` + transcript goes into ONE `methodology_hash` anchored via `ReasoningTraceRegistry`. | — |
| 5 | **Reasoning I/O — V_check** (§5) | The synthesizer's pick is an **input** to V_check (`weights_sum_bps==10000` ∧ `max_concentration≤60%` ∧ `min_cost_benefit_bps≥5`). Fail → SKIP trace, even on unanimous agreement. The debate cannot override it. | yes |

**R3 target:** fixed deterministic agent order + transcript-sorted-before-hashing + union-of-hashes + the external gate = fully replayable, immutable provenance. No non-replayable element introduced.

---

## 7. The honesty mechanism — concluding "decline / do-nothing" and surfacing underperformance

The StockBench finding (our agent ranked **#15/15**, Sortino −0.91 vs the raw GLM-4.5's +1.94 — adding the agent made it *worse*) is load-bearing and surfaced, not hidden. Three structural mechanisms:

1. **First-class ABSTAIN.** The synthesizer can output `{decision:'abstain'}` (hold current weights). This is NOT a failure — it returns a populated `_CandidateResult` (empty weights, passive-baseline `return_series`, abstain rigor stub) that flows to V_check's existing SKIP-trace mechanism. It does not hit the empty-guard. A debate structurally forced to produce a trade would be dishonest by construction; ours is not.
2. **The passive-null is a standing position, not an afterthought.** **C-null** (deterministic) is the StockBench skeptic — a candidate survives only if it beats buy-and-hold net of cost by ≥5 bps (the V_check `min_cost_benefit_bps` bar). The **Bear researcher** argues this case in natural language and is structurally privileged toward abstention. Action is never privileged; the null is a hard-to-beat default.
3. **Underperformance is surfaced on the passport.** Whatever the debate concludes, the honest-comparison discipline carries forward: mean ± stdev, no seed cherry-picking, the paper-claim delta. The synthesizer is instructed to cite the unfavorable active-agent base rate even on APPROVE. Abstention renders as a *confident, explained* verdict ("Passive null wins by X bps; rebalancing costs more than its expected edge — StockBench base rate: active agents rank below passive on most windows"), not as a broken product.

---

## 8. LLM budget — calls per Generate, cheap-by-default, BYOK tie-in

**Current K=1 baseline (fusion path):** ~1 brief-validation + ~1 fusion synthesis per regime ≈ **~2–3 calls/Generate**.

**Debate path (default N=2 bull/bear, R=1 round):**

| Step | Calls |
|------|-------|
| Brief validation (existing) | 1 |
| Proposers (N=2, `asyncio.gather`) | 2 |
| Research debate (Bull ∥ Bear, R=1) | 2 |
| Critic panel (4 critics, **deterministic**) | **0** |
| Synthesizer (or 0 when floor forces it) | 1 |
| **Total** | **~6 calls/Generate** (~2–3× K=1) |

**The five cheap-by-default moves (grafted from B + C):**

1. **Critics are code, not models** — the adversarial risk work (rigor backtest, regime conditioning, cost-benefit, embargo) costs **zero tokens**. This is the core win over an all-LLM TradingAgents debate (which would be N proposers × R rounds × M critics ≈ 15–20 calls).
2. **Shared evidence built once** — embargo/decay/retrieval run once per Generate; only `select_candidates` re-ranks per steer (pure Python, free).
3. **Bull ∥ Bear concurrent** (`asyncio.gather`) — latency ≈ 1 call, not 2; keeps the demo responsive.
4. **Inline stats, not live tool-use** — `_tool_get_asset_stats`/corr/stress computed in Python and fed as text. Deliberately avoids the `propose_portfolio_with_tools` 12-iteration loop, which is **Anthropic-SDK-only and silently no-ops on the live Bedrock/Nova prod path** — no portability cliff.
5. **Synthesizer collapses to 0 LLM calls** when the deterministic floor already forces the outcome (crisis/degraded, or no candidate clears C-null). Realistic ceiling: **4–6 calls/Generate.**

**Bounded + configurable:** `DEBATE_N` (default 2, cap 5), `DEBATE_ROUNDS` (default 1), `DEBATE_MAX_LLM_CALLS` (hard ceiling → `DebateUnavailable` if exceeded), all env-gated; flag-off by default so the default path keeps K=1's cost.

**Model-selection / BYOK tie-in.** Every LLM role constructs via `make_llm_backend(model=...)`, so **per-role model diversity is free** and gated by `FREE_TIER_MODELS` / `is_allowed_model()`. Default: cheap model (Nova Micro / cost-picker) for proposers + bull/bear; the synthesizer may warrant a stronger model. **BYOK is the natural escalation path** — a user supplying their own key can run a stronger model per role (a Nova bull vs. a Llama bear) without changing the topology; `served_model` provenance is captured per agent. Deferred to a stretch phase because it complicates the single-provenance story and isn't needed for the demo.

---

## 9. Phased build plan

### Phase 1 — flag-gated, PR-able skeleton (the concrete first increment)

> **PR: "feat: debate pipeline skeleton (flag-gated, deterministic-critic, tool-free)"**

**Minimal roster (3 LLM roles + 2 deterministic critics):** Proposer (reuse `StrategyFusion.propose`) → Bull ∥ Bear (one round, two new prompts) → **C-rigor** (`evaluate_fusion_spec`) + **C-null** (cost-benefit) → Synthesizer (act/abstain). N=2 (bull/bear regimes). ~6 LLM calls, behind a default-OFF flag.

**Files:**
- **New** `backend/archimedes/agents/debate_engine.py`: `_run_debate_candidate` + `DebateUnavailable` + `_debate_can_run` (mirror `_fusion_can_run:113`) + the two deterministic critics + a thin JSON-decision synthesizer adapter (`extract_json` + anti-hallucination filter — keep it a decision adapter, not a clever synthesizer; it's the highest-defect-density new surface).
- **Edit** `backend/archimedes/agents/generation_pipeline.py`: allowlist `:84`, dispatch branch `:1053` (+ regime collapse to `["neutral"]`), episodic ternary `:1265`.
- **Edit** `backend/archimedes/api/generate_schemas.py:32`: add `"debate"` to the `mode` docstring.

**Reuse verbatim:** `select_candidates(regime_bias=...)`, `extract_json` + both anti-hallucination id-filters, `make_llm_backend`, `evaluate_fusion_spec`, `GmmRegimeDetector.get_current_regime()`, the unchanged PBO/backtest/persist/external-gate tail.

**Tests (hermetic — no live LLM/Redis):**
- canned-backend debate produces a valid `_CandidateResult` with `has_real_rigor=True`;
- ABSTAIN path returns a populated SKIP-shaped result (does NOT hit the empty-guard);
- the cited-paper union is non-empty;
- `DebateUnavailable` → agent-runner fallback + honest relabel;
- **`assert num_trials == len(candidate_pool)`** when the external gate is called;
- with the flag OFF, the live path is byte-identical (grep proves `"debate"` is unreachable).

This is already a real N>1 debate with adversarial culling and first-class abstention, at ~6 calls, in one reviewable PR.

### Phase 2 — full deterministic panel + GMM risk + rebuttal

Add **C-regime** (GMM, Surface 1) and **C-prov** (embargo/provenance, Xia 1/2/4). Add the second adversarial round (Bull sees Bear's claims and vice versa — visible rebuttal). Add the neutral steer (N=3). Wire Considered Alternatives to render per-critic / synth reject rationale. Add the synthesizer-collapse-to-0 optimization. Emit the full `agent_iteration`/`tool_called`/`tool_result` transparency trace.

### Phase 3 — provenance hardening + polish

Union `consulted_paper_hashes` into the single `methodology_hash` anchored via `ReasoningTraceRegistry` (C-2); persist the full candidate set + verdicts to `strategy_proposals` content-hashed (C-6); render the panel transcript on the passport; regime-conditional rigor scoring on the passport (`regime_robustness_score`). Flip `ARCHIMEDES_DEBATE_ENABLED` on for the demo once `num_trials` wiring is verified on the live path.

### Stretch (only if judges want maximal sophistication) — full TradingAgents roster + BYOK model diversity

Expand to the 9-role A-style roster (separate fundamental/sentiment/technical analysts, an aggressive-vs-conservative risk *debate* as LLMs rather than the deterministic gate, a REVISE re-synth loop). Per-role model diversity via BYOK (Nova bull vs. Llama bear). Optional Bedrock-Converse `toolConfig` port so risk agents pull live empirical evidence on the Nova path. **This is where the 30% Agentic-Sophistication axis peaks — but at ~12 calls (4× K=1), gated behind Phases 1–3 proving the budget and honesty constraints hold.** Explicitly a stretch, not the ship.

---

## 10. Risks + open questions for Dan

**Risks (with mitigations):**

1. **`num_trials` mis-wiring silently weakens rigor (highest-stakes).** `num_trials=1` disables the DSR correction and produces a false strict-rigor badge — the exact "build on sand" failure. *Mitigation:* assert `num_trials==len(candidate_pool)` in a test; surface pool size on the passport.
2. **Diversity theater on an empty corpus.** Per MEMORY (paper-corpus-empty), prod has no real ingested papers → the bull/bear proposers may converge to near-identical specs. *Mitigation:* `_debate_can_run` requires `≥MIN_PAPERS`; if the bull/bear sets don't actually differ, log it and fall back to fusion (honest relabel). **This is a hard prerequisite, not a code mitigation — populating the corpus is on the critical path for the demo to land.**
3. **Budget creep.** ~2–3× call count is real, not hidden. *Mitigation:* deterministic critics, shared evidence, synthesizer-collapse-to-0, `DEBATE_MAX_LLM_CALLS` cap, flag-off by default.
4. **Latency on prod Nova/Bedrock.** *Mitigation:* `asyncio.gather` the proposers and Bull∥Bear; stream `agent_iteration` so the UI shows progress (zero frontend change).
5. **Compounding hallucination** (more agents = more error surface, Xia §5's whole point). *Mitigation:* `valid_ids` filter on every cited turn; deterministic critics bound the blast radius (an all-LLM panel would compound errors, not catch them); V_check is the non-overridable floor.
6. **GMM degradation read as data-driven.** *Mitigation:* C-regime discounts its weight on `status=="degraded"` and the passport surfaces "regime risk: rule-based fallback."
7. **Non-replayable agent ordering** from Bull∥Bear concurrency. *Mitigation:* sort transcript by fixed role order before hashing.
8. **The synthesizer is new code with no analog** — highest defect density. *Mitigation:* keep it a thin APPROVE/ABSTAIN + rationale JSON adapter, not a clever synthesizer; reuse `extract_json` + anti-hallucination filters.

**Open questions for Dan:**

- **A. Default N — 2 or 3?** N=2 (bull/bear) is the cheapest genuine debate; N=3 (+neutral) reads as more sophisticated to judges. Recommend ship N=2, demo N=3.
- **B. One rebuttal round or zero for the ship?** R=1 with no cross-agent visibility is cheapest (Proposal B); one visible rebuttal round (Bull sees Bear's claims) is materially more "debate-like" for the 30% axis at +0 cost if collapsed into the same calls. Recommend R=1 with rebuttal in Phase 2, R=1 no-rebuttal in Phase 1.
- **C. Risk agent — deterministic (recommended) or LLM?** I've made it deterministic to enforce non-votable Hierarchy-of-Truth and save tokens. The stretch phase can add an LLM aggressive-vs-conservative risk *debate* on top if judges specifically want visible risk argument. Confirm you're happy with deterministic-by-default.
- **D. Corpus population timeline.** The debate's diversity is only as real as the corpus, and prod's is empty. Is corpus population landing before the T1.1 demo, or do we demo on a seeded fixture corpus? This gates whether the diversity is genuine or theater.
- **E. BYOK model diversity in scope for the demo?** Free per `make_llm_backend(model=)`, but complicates the single-provenance story. Recommend defer to stretch.

---

### Honest bottom line

This ships because it's ~80% reuse (fusion grounding, `evaluate_fusion_spec`, the loop, SSE vocabulary, the rigor/V_check/persist tail) and ~20% new (two/three prompts, four deterministic critics, one runner, one thin synthesizer). It costs ~2–3× K=1 in calls — real, bounded, flag-gated, not hidden — and contains that cost by keeping deep generation and provenance at K=1 while buying diversity only in cheap debate passes. Its differentiator is the StockBench-honest abstention path: a genuinely multi-agent debate that can say "do nothing," and proves it. The single biggest non-code risk is the empty prod corpus — without papers, the diversity is theater, so corpus population is on the critical path.
