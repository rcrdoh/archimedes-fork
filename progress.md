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
