# Progress

## Status
In Progress

## Tasks
- [x] Issue #161: Rewrite strategy-passport-spec.md for Track E architecture
  - Removed stale `/api/decisions/*` references (0 remaining)
  - Removed all SHA-256 references (0 remaining; all keccak256)
  - Removed stale `ALTER TABLE strategies` syntax (0 remaining)
  - Added `strategy_proposals` episodic memory table (T-PE.8) with schema + API endpoint
  - Added proposals endpoint to API surface section
  - Updated integration flow to mention proposals persistence
  - Added proposals to acceptance criteria
  - Updated estimated lift table with T-PE.8
  - All acceptance criteria verified ✅

## Files Changed
- `docs/specs/strategy-passport-spec.md` — rewritten for Track E (multi-paper + regime-aware + on-chain + episodic memory)

## Notes
- Spec is 543 lines (within 400-600 target)
- PaperRef mentions: 12, regime_tag: 21, StrategyRegistry: 13
- Cross-references architecture doc 3 times
- strategy_proposals table documented with 9 mentions

## Issue #156 — Xia et al. 2026 Named Protocols
- **Status**: ✅ Implemented and merged
- **Commit**: `[intelligence] Implement Xia 2026 named protocols in generation pipeline (Issue #156)`
- **What was done**:
  - Outcome Embargo: `services/embargo_filter.py` — filters papers within configurable embargo window (default 30 days)
  - Time-Aware Retrieval: `services/time_aware_retrieval.py` — SPECTER2 scores decayed by exp(-λ×age); regime-aware λ
  - Source Tracking: `services/source_tracker.py` — consulted_paper_hashes in trace canonical hash
  - V_check: `chain/v_check.py` — deterministic pre-trade validity (weights_sum, max_concentration, min_cost_benefit)
  - Hierarchy of Truth: enforced structurally via V_check gate
  - `docs/specs/xia-2026-protocols.md` spec doc
  - 36 new tests, all passing
  - Wired into `agent_runner.py` (V_check before commit_trace) and `corpus_service.py` (embargo + decay)
- **Tests**: 472 passed, 0 new failures

## Issue #159 — Refactor Strategy → StrategyPassport with papers: list[PaperRef]
- **Status**: ✅ Implemented and merged
- **Commit**: included in batch push with other Track E work
- **What was done**:
  - New `backend/archimedes/models/paper_ref.py` — `PaperRef` dataclass (arxiv_id, title, authors, doi, venue, year, citation_count, contribution)
  - `Strategy` → `StrategyPassport` with `papers: list[PaperRef]` replacing scalar `paper_*` fields
  - Backwards-compat alias `Strategy = StrategyPassport` + property accessors for `paper_arxiv_id`, `paper_title`, etc.
  - New fields: `on_chain_registration_block`, `arcscan_url`, `paper_claim_blended_sharpe`
  - `compute_methodology_hash_keccak()` using SHA-3 (keccak-256)
  - API schema: `PaperRefResponse` + `papers` list in `StrategyResponse`
  - `strategy_provider.py` builds `StrategyPassport` with single `PaperRef` from curated files
  - Updated tests: test_regime_tag, test_kelly_portfolio, test_strategy_signal_evaluator
- **Tests**: 472 passed, 0 new failures
- **Acceptance verified**: PaperRef import OK, StrategyPassport papers list works, no scalar paper fields in dataclass, keccak256 matches hashlib canonical
