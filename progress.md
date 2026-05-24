# Progress — Subagent Worker

## 2026-05-24 — Issue #169 (T2.4): Corpus default Catalog tab + plain-English category labels

### Status: ✅ COMPLETE

### Changes made:
1. **`ui/src/components/CorpusExplorer.jsx`** — 3 edits:
   - Default tab changed from `'overview'` → `'catalog'`
   - Overview bar chart: shows `c.label` (plain-English) instead of raw `c.name` (e.g. `q-fin.ST`)
   - Category filter dropdown: shows `c.label || c.name` instead of raw code

2. **`backend/archimedes/api/papers_routes.py`** — 1 edit:
   - KG endpoint category entities now use `_category_label(c) or c` for the label field instead of raw `c`

### What was already done (no changes needed):
- `papers_routes.py` already imported `_category_label` and injected `category_label` into every paper response (list + detail + overview)
- `corpus_categories.py` already had a complete `CATEGORY_LABELS` dict covering all q-fin, cs, stat, math, econ, physics categories
- `CorpusExplorer.jsx` catalog table and paper detail already rendered `p.category_label || p.primary_category`

### Verification:
- `pytest -q backend/tests` → 363 passed, 2 skipped, 0 failed
- `grep -c "q-fin\." ui/src/components/CorpusExplorer.jsx` → 0 (no bare codes in visible text)
- Default tab `useState('catalog')` confirmed
- API returns `category_label` field in paper responses

### Acceptance criteria met:
- [x] `/corpus` opens to Catalog tab by default
- [x] Category badges show plain English on hover (not raw q-fin.ST codes)
- [x] API returns `category_label` alongside `primary_category`
- [x] Arxiv ID display preserved (anti-goal respected)
- [x] Author/title unchanged (anti-goal respected)
- [x] Paper sort order unchanged (anti-goal respected)

### Commit: `[frontend+backend] Corpus default Catalog tab + plain-English category labels (Issue #169)`
