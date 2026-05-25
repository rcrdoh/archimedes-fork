# Dead-Code Audit v2 — 2026-05-24 (refreshed 2026-05-25 — submission day)

> **Refresh 2 (2026-05-25, submission day):** Pivots the doc from "what's safe
> to delete" to **"what's still stub vs shipped, and where the plan gaps are"** —
> the question that matters for the final submission window. The original audit's
> headline ("zero files safe to delete now") still holds; the new value is the
> **§ "Work Remaining Inventory"** near the bottom, which catalogs every
> currently-stubbed file against the plan that protects it and what would
> constitute "shipped." Baseline: `main` @ `2195417` (Merge PR #263, 2026-05-25)
> — same as Refresh 1; no main commits have landed in the intervening hours
> (the run of 5 dbrowneup PRs + 1 workflow PR Dan's session merged are all on
> origin/main at this SHA already).
>
> **Refresh 1 (earlier 2026-05-25):** main moved by ~80 commits / 90+ files after
> the v2 baseline. Three v2 findings were **resolved** by intermediate merges
> (test_user_profile_privacy moved, source_tracker wired, StressScenarioPanel
> wired); no new dead-code surfaced. See § "Refresh delta — 2026-05-25" mid-doc.

> **Supersedes:** the earlier same-day v1 audit, which was retracted as unsound.
> v1 ran against a static snapshot of `main` and treated "no current importer" as
> "dead." That missed (a) intentional stubs in active plans, (b) files about to
> be re-wired by an in-flight PR, and (c) entrypoints invoked by `docker-compose`
> / `python -m` / `forge script` that have no Python-level import edges.
>
> **Audit baseline:** `main` @ `d6afdca` (Merge PR #225 from
> `dbrowneup/pr-eip6963-wallet-discovery`, 2026-05-24).
> **Methodology v2 (3-phase):**
> 1. Build a **protected-files set** FIRST from every active plan, spec, open PR,
>    and open issue. Treat any file mentioned in any active artifact as off-limits
>    by default. (135 files protected at audit time.)
> 2. Inventory + importer map against current `main` (one-pass: `grep -rEn 'from
>    archimedes' …` cached, then parsed with python to handle both `from … import
>    X` and `import … .X` forms).
> 3. For every zero-importer candidate, MANDATORY cross-check against the
>    protected set + entrypoint heuristics (`if __name__`, docker-compose service,
>    `python -m`, `forge script`) before flagging anything as dead.
>
> **No deletions performed.** This is a manifest. **No file changes anywhere.**
> Delivered in chat + committed (not pushed) on branch
> `dbrowneup/dead-code-audit-v2-wt` inside `.claude/worktrees/audit-v2/`.

---

## TL;DR

| Bucket | Files | Action |
|---|---:|---|
| **Fully dead — safe to delete now** | **0** | nothing |
| Test-only (no runtime, no protection) | 1 | flag for decision, don't act unilaterally |
| Plan-protected zero-importer (intentional stubs) | 3 | leave alone, named in active plans |
| Operator-only entrypoints (docker-compose, `python -m`, forge) | 8 + 3 Forge | leave alone, intended |
| Orphaned test (wrong directory) | 1 | **move** not delete |
| JSX/TSX zero-importer (all protected or entrypoint) | 0 actionable | none |
| Solidity zero-importer (all Forge scripts or protected) | 0 actionable | none |

**Bottom line:** every candidate the v1 audit listed as "fully dead" turns out
to be protected by an active plan, an in-flight PR (`PortfolioAdvisor.jsx`
re-wired by #216), an entrypoint, or a deliberate stub for upcoming work. The
correct number of files to delete right now is **zero**. The audit's value is
making explicit *why* — and identifying which removals become safe **after**
which specific plans land.

---

## Phase 0 — What changed under main since v1 ran (~3 hours ago)

21 commits landed on `main` after v1's baseline (`409cc0f`). The ones that
invalidated v1's findings:

| Merge | What it changed | v1 finding it invalidated |
|---|---|---|
| **PR #215** — prune historical artifacts to `docs/archive/` | Moved active plans into `docs/archive/` (a docs reorg, not a retirement signal — `archive/` here means "moved out of the top-level browsing surface," not "no longer active"). | v1's grep didn't consult `docs/archive/`, so it missed protection signals like the launch plan's `AgentLike` reference. |
| **PR #216** — resurrect `PortfolioAdvisor` on `/generate` (closes #210) | `ui/src/components/Generate.jsx:6` now `import PortfolioAdvisor from './PortfolioAdvisor'`; rendered on `Generate.jsx:297,312`. | v1 flagged `PortfolioAdvisor.jsx` as zero-importer and recommended deletion. It is now LIVE. |
| **PR #220** — kill fake Library Correlation matrix | Removed the `<CorrelationMatrix>` render from `Strategies.jsx` but **explicitly kept the component file** ("kept for potential re-use once we persist real daily series"). Reasoning.jsx still imports it. | Would have been flagged by a naive v2 too without reading PR body. |
| **PR #222** — regime-honest | Touched `RegimePanel.jsx`, `chain/agent_runner.py`, regime routes. | Confirms regime detection is being actively reshaped — both `regime_detector.py` and `statistical_regime.py` are in flux, not "dead." |
| **PR #223** — ruff Tier 1 + autofixes | Touched 105 files mechanically. | v1's importer map ran against pre-autofix code; v2 ran post-autofix. |

---

## Phase 1 — Protected set construction

### Sources (in priority order)

| Source | What we extracted | Count of unique file refs |
|---|---|---|
| `docs/archive/*.md` (15 files) | Every file path / dotted module mentioned | included |
| `docs/specs/*.md` (20 files) | Same | included |
| `docs/*.md` top-level (19 files) | Same | included |
| `gh pr diff` for open PRs #199, #214, #225 | All files those PRs touch (about to land) | 22 files |
| `gh issue view` for open issues #218, #219, #163, #164, #160, #155, #154, #151, #148, #147, #212, #176 | Files named in issue bodies | 46 files |
| **Union, dedupe, filter to existing-on-disk** | | **135 files** |

Stored at `/tmp/audit-v2/protected_existing.txt` (135 lines, all confirmed to
exist on the audit-baseline tree).

### Key protections worth calling out

These are the files v1 wrongly targeted; each is now demonstrably protected:

- **`backend/archimedes/agents/base.py`** (36 lines) — `AgentLike(Protocol)`
  defined as an intentional stub. Named in:
  - `docs/archive/launch-execution-plan-2026-05-23.md:1148` ("Protocol for AgentLike + shared utilities")
  - `docs/archive/launch-execution-plan-2026-05-23.md:1172` (literal acceptance check: `python -c "from archimedes.agents.base import AgentLike"` → succeeds)
  - Closed Issue #173 ("Refactor agentic services into agents/ subpackage with shared base.py") — closed, but Issues #163 + #164 (Strategy Generation Agent + Portfolio Construction Agent) carry the work forward.
- **`backend/archimedes/services/regime_detector.py`** (111 lines) — old v1 detector.
  Named in `docs/specs/component-interfaces-spec.md`, `docs/chuan-architecture-survey.md`,
  `docs/judging-rubric-assessment.md`. Survey marks it as "superseded but coexists"
  pending Önder's read.
- **`backend/archimedes/services/statistical_regime.py`** (466 lines) — v2 GMM detector.
  Named in `docs/chuan-architecture-survey.md` + others. Survey gap #2: regime
  detection consolidation is deferred ("needs Önder's read on which is wired to
  `RegimePanel` before specing").
- **`backend/archimedes/services/_deprecated/portfolio_constructor.py`** (282 lines)
  + **`_deprecated/kelly_portfolio.py`** (523 lines) — named in
  `docs/specs/portfolio-constructor-decision-tree.md` (the canonical decision tree)
  + Issue tracker references. The `_deprecated/` location is the *plan*; deletion
  is pending the retirement step in the decision tree.
- **`backend/archimedes/services/source_tracker.py`** (86 lines) — Xia 2026 § 4.3
  Source Tracking protocol. Named in `docs/specs/xia-2026-protocols.md` and
  `docs/archive/launch-execution-plan-2026-05-23.md`. Issue #219 (Önder driving,
  T3.7 Xia 2026 named protocols) finishes the wiring; deletion would be the wrong
  direction.
- **`backend/archimedes/chain/strategy_publisher.py`** (190 lines) — `StrategyPublisher`
  class. Named in `docs/archive/launch-execution-plan-2026-05-23.md`. The wiring
  into the runtime path is pending (not yet imported anywhere outside tests).
- **`backend/archimedes/chain/agent_runner.py`** (923 lines) — `StrategyRunner`.
  Test-only at the Python-import level, BUT a `docker-compose` service entrypoint
  (`python -m archimedes.chain.agent_runner`). Live.
- **`backend/archimedes/scripts/run_kb_pipeline.py`** (115 lines) — **v1 audit
  error.** Looked orphaned but `services/kb_runner.py:102` does `from
  archimedes.scripts.run_kb_pipeline import run_pipeline` inside its tick loop,
  AND `api/corpus_routes.py:151` instructs users to invoke it directly. v2
  catches this via the "entrypoints + reverse-import" check.
- **`ui/src/components/PortfolioAdvisor.jsx`** (480 lines) — LIVE via PR #216,
  `Generate.jsx:297,312`.
- **`ui/src/components/StressScenarioPanel.jsx`** (131 lines) — named in
  `docs/specs/spine-plus-v2-plan.md`, `docs/archive/phase5-execution-runbook.md`,
  `docs/archive/afternoon-execution-plan-2026-05-24.md`. Planned for re-wire.
- **`ui/src/components/CorrelationMatrix.jsx`** (176 lines) — PR #220's body
  explicitly says "`CorrelationMatrix.jsx` is **not** deleted — kept for
  potential re-use once we persist real daily series." Also imported by
  `Reasoning.jsx` (my JSX importer regex missed the `.jsx` extension; manual
  verification confirmed the live import).
- **`contracts/src/interfaces/IPriceOracle.sol`** (36 lines) — named in
  `docs/specs/component-interfaces-spec.md` and `docs/specs/ecosystem-design-spec.md`.
  Currently no Solidity-level import or cast, but the interface is part of the
  ecosystem spec contract.

---

## Phase 2 — Importer map (current `main` @ `d6afdca`)

Inventory: 116 Python modules under `backend/archimedes/`, 34 JSX/JS under `ui/src/`,
23 Solidity files under `contracts/src` + `contracts/script`.

### Python — ZERO IMPORTERS (12 modules)

After classifying each by entrypoint role and protection:

| File | Lines | Why it's zero-importer | Bucket |
|---|---:|---|---|
| `backend/archimedes/agents/base.py` | 36 | Intentional stub | **PLAN-PROTECTED** |
| `backend/archimedes/services/regime_detector.py` | 111 | v1 detector kept pending Önder's consolidation read | **PLAN-PROTECTED** |
| `backend/archimedes/services/_deprecated/portfolio_constructor.py` | 282 | Deprecated, kept pending decision-tree retirement step | **PLAN-PROTECTED** |
| `backend/archimedes/chain/oracle_runner.py` | 52 | `docker-compose` service via `python -m` | **OPERATOR ENTRYPOINT** |
| `backend/archimedes/services/kb_runner.py` | 115 | `docker-compose` service via `python -m` | **OPERATOR ENTRYPOINT** |
| `backend/archimedes/evaluation/stockbench/__main__.py` | 88 | `python -m archimedes.evaluation.stockbench` entrypoint | **OPERATOR ENTRYPOINT** |
| `backend/archimedes/scripts/bootstrap_vaults.py` | 575 | `python -m …` operator script (in plan) | **OPERATOR ENTRYPOINT** |
| `backend/archimedes/scripts/deploy_contracts.py` | 365 | `python -m …` operator script | **OPERATOR ENTRYPOINT** |
| `backend/archimedes/scripts/hydrate_corpus.py` | 154 | `python -m …` operator script | **OPERATOR ENTRYPOINT** |
| `backend/archimedes/scripts/seed_backtests_from_artifacts.py` | 118 | `python -m …` operator script | **OPERATOR ENTRYPOINT** |
| `backend/archimedes/scripts/verify_arc_e2e.py` | 635 | `python -m …` operator script (in plan) | **OPERATOR ENTRYPOINT** |
| `backend/archimedes/tests/test_user_profile_privacy.py` | 186 | Wrong directory; `pytest.ini` doesn't collect `backend/archimedes/tests/` | **ORPHANED TEST — MOVE** |

**Truly safe-to-delete count after cross-check: 0.**

The orphaned test (`test_user_profile_privacy.py`) should be **moved** to
`backend/tests/test_user_profile_privacy.py` where pytest will collect it (this
restores Issue #181 privacy test coverage on live `email_crypto`/`log_scrubber`
code in `api/user_routes.py`).

### Python — TEST-ONLY (runtime=0, scripts=0, tests>0) (9 modules)

| File | Lines | Test importer | Disposition |
|---|---:|---|---|
| `backend/archimedes/main.py` | 275 | 4 tests | LIVE (uvicorn entrypoint) |
| `backend/archimedes/chain/agent_runner.py` | 923 | 2 tests | LIVE (docker-compose service) |
| `backend/archimedes/chain/strategy_publisher.py` | 190 | 6 tests | **PLAN-PROTECTED** (launch plan) |
| `backend/archimedes/evaluation/stockbench/adapter.py` | 656 | 2 tests | LIVE via `stockbench/__main__.py:13` import |
| `backend/archimedes/scripts/run_backtests.py` | 174 | 1 test | LIVE (`__main__` operator script) |
| `backend/archimedes/services/_deprecated/kelly_portfolio.py` | 523 | 1 test | **PLAN-PROTECTED** (decision tree) |
| `backend/archimedes/services/source_tracker.py` | 86 | 7 tests | **PLAN-PROTECTED** (Issue #219, Xia spec) |
| `backend/archimedes/services/statistical_regime.py` | 466 | 1 test | **PLAN-PROTECTED** (survey gap #2) |
| `backend/archimedes/services/arxiv_corpus.py` | 478 | 1 test | **PLAN-PROTECTED** (named in `docs/specs/spine-plus-v2-plan.md:909` as "#4 Arxiv intake paths" consolidation work) |

All 9 are accounted for. **None recommended for unilateral deletion.**

`arxiv_corpus.py` is the closest thing to a candidate — it's flagged in
spine-plus-v2 as one of three parallel intake paths to consolidate, but the
consolidation itself hasn't shipped. Wait for that consolidation PR before
acting.

### JSX/JS — ZERO IMPORTERS (regex-checked + manually verified)

| File | Lines | True status |
|---|---:|---|
| `ui/src/main.jsx` | 11 | LIVE (Vite entrypoint, not imported) |
| `ui/src/App.jsx` | 234 | LIVE (`main.jsx:5: import App from './App.jsx'` — my regex missed the `.jsx` extension) |
| `ui/src/components/CorrelationMatrix.jsx` | 176 | LIVE (`Reasoning.jsx` imports it) AND **PLAN-PROTECTED** (PR #220 explicitly kept it + `docs/specs/evening-execution-plan-2026-05-24.md`) |
| `ui/src/components/StressScenarioPanel.jsx` | 131 | **PLAN-PROTECTED** (3 plans reference it for re-wire) |

**Truly safe-to-delete count: 0.**

### Solidity — ZERO IMPORTERS

| File | Lines | True status |
|---|---:|---|
| `contracts/script/Deploy.s.sol` | 204 | LIVE (`forge script` entrypoint) |
| `contracts/script/DeployInfra.s.sol` | 53 | LIVE (`forge script` entrypoint; referenced in launch plan) |
| `contracts/script/DeployStrategyRegistry.s.sol` | 34 | LIVE (`forge script` entrypoint; referenced in launch plan) |
| `contracts/src/interfaces/IPriceOracle.sol` | 36 | **PLAN-PROTECTED** (component-interfaces-spec + ecosystem-design-spec) |

**Truly safe-to-delete count: 0.**

---

## Phase 3 — Cross-check methodology (the v1 → v2 fix)

For each candidate, the gate is:

```
candidate is SAFE-TO-DELETE only if:
    candidate not in protected_existing.txt                           AND
    candidate does NOT contain `if __name__ == "__main__"`            AND
    candidate is NOT a docker-compose service                         AND
    candidate is NOT loaded dynamically (importlib, exec, eval)       AND
    candidate is NOT a Forge script (.s.sol, contracts/script/)       AND
    candidate is NOT a Vite entry (main.jsx, App.jsx, vite.config*)   AND
    candidate file is NOT mentioned by name (with or without path)
        in ANY plan/spec/issue/open-PR body
```

Eight conditions, ALL must pass. **No candidate in v2 passed all eight.**

---

## Recommendations

### Do this now

1. **Move (don't delete)** `backend/archimedes/tests/test_user_profile_privacy.py`
   → `backend/tests/test_user_profile_privacy.py`. Restores Issue #181 privacy
   coverage on live `email_crypto`/`log_scrubber` code. This is the only
   actionable item from v2. Even this is a `git mv`, not deletion.

### Do these only when a specific PR lands

| Trigger event | Becomes-safe-to-delete |
|---|---|
| Spine-plus-v2 § "#4 Arxiv intake paths" consolidation PR merges | `services/arxiv_corpus.py` (478 lines) — wait for it. |
| `docs/specs/portfolio-constructor-decision-tree.md` retirement step ships | `services/_deprecated/portfolio_constructor.py` (282) + `_deprecated/kelly_portfolio.py` (523) + the deprecated `__init__.py` |
| Regime consolidation (survey gap #2, Issue not yet filed) ships | one of `regime_detector.py` (111) or `statistical_regime.py` (466) becomes deletable depending on Önder's read |
| Issue #173 follow-on / agentic refactor completes | `agents/base.py` continues to be protected unless the `AgentLike` Protocol is explicitly retired in spec |

### Do this never (well, almost)

- Don't delete `chain/strategy_publisher.py` — it's awaiting wiring per the launch
  plan, not orphaned by mistake.
- Don't delete `IPriceOracle.sol` — interface contract referenced in two specs;
  the absence of Solidity-level imports is intentional (interface for off-chain
  consumers).
- Don't delete any `docker-compose` service entrypoint, `python -m` script, or
  Forge script. Zero Python importers ≠ unused.

---

## Reproducibility

All intermediate files persist under `/tmp/audit-v2/`:

| File | Contents |
|---|---|
| `protected_existing.txt` | 135 files protected by plans/specs/PRs/issues |
| `modules.txt` | inventory of all 116 Python modules + paths |
| `all_imports.txt` | 608 raw import lines from grep |
| `module_importers_py.txt` | per-module importer counts (from python parser) |
| `module_importers.txt` | joined inventory + importer counts |
| `jsx_importers.txt` | 34 JSX files + importer counts |
| `sol_importers.txt` | 23 Solidity files + importer counts |

To regenerate from scratch on a future `main`:

```bash
# Phase 1: protected set
mkdir -p /tmp/audit-v2
grep -rhE '(backend|ui|contracts|scripts|analytics-engine|tests)/[A-Za-z0-9_/.-]+\.(py|jsx|tsx|ts|js|sol)' \
  docs/archive/ docs/specs/ docs/*.md \
  | sort -u > /tmp/audit-v2/protected_from_docs.txt

for n in $(gh pr list --state open --json number --jq '.[].number'); do
  gh pr diff $n --name-only
done | sort -u > /tmp/audit-v2/protected_from_open_prs.txt

# Phase 2: importer map via python (handles both import forms)
grep -rEn --include="*.py" -- '(from|import) archimedes\.[a-zA-Z0-9_.]+' \
  backend/ scripts/ analytics-engine/ tests/ > /tmp/audit-v2/all_imports.txt
# Then run the python parser block in this file

# Phase 3: cross-check
awk -F'|' '$6==0 { print $2 }' /tmp/audit-v2/module_importers.txt \
  | grep -Fvxf /tmp/audit-v2/protected_existing.txt
```

---

## Refresh delta — 2026-05-25 (main @ `2195417`)

Re-ran the audit against latest origin/main after ~80 commits / 90+ files of
merges. Verified each prior finding by `git cat-file -e` against `origin/main`
and `git grep` for new importers. **No deletions. Headline unchanged.**

### Three v2 findings resolved by intermediate merges (no action needed)

| v2 finding | Merge that resolved | New status |
|---|---|---|
| **`backend/archimedes/tests/test_user_profile_privacy.py` → `backend/tests/`** (only actionable in v2) | **PR #229** (`[tests] Move test_user_profile_privacy.py into pytest collection path`) — landed 2026-05-25 03:03 UTC, cites v2 directly | ✅ done; pytest now collects it; Issue #181 privacy coverage restored |
| **`services/source_tracker.py`** was test-only / plan-protected | **PR #235** (`onder/source-tracker-wiring`, `[quant] Wire source_tracker into reasoning trace — Xia § 4.3 runtime`) | ✅ now LIVE: `chain/agent_runner.py:40` imports `build_consulted_hashes`, called at 3 trace-publish sites; closes #219 |
| **`ui/src/components/StressScenarioPanel.jsx`** was plan-protected zero-importer | **PR #258** (`moonshot/244-stress-panel`, `[frontend] Wire StressScenarioPanel into Portfolio`) | ✅ now LIVE: `ui/src/components/Portfolio.jsx:7` imports, `Portfolio.jsx:201` renders |

### Other significant merges that touch the audit surface (status unchanged)

| Merge | Effect on audit |
|---|---|
| **PR #239** (`onder/stockbench-consolidation`, "Option C") | Consolidated two parallel StockBench adapters into the canonical `evaluation/stockbench/adapter.py`; **deleted** `benchmarks/stockbench_adapter.py` (419 LOC) + `scripts/stockbench_run.py` (234 LOC). v2 didn't list those (they were added and deleted between v2 baseline and this refresh — net-zero against `d6afdca`), but worth recording. |
| **PR #214** (`moonshot/147-aws-s3-dynamodb-iam`) | Added `services/dynamodb_paper_index.py` + `services/s3_artifact_store.py` + `api/auth_guard.py` + `services/secrets_service.py` to the tree. See "New zero-importer files" below. |
| **PR #265** (`moonshot/fix-missing-secrets-service`) | Hotfix adding `services/secrets_service.py` (502 fix). Now LIVE: `main.py` imports it. |
| **5× dependabot merges** (#247–#251) | Backend dep bumps; no audit impact. |
| **PR #267, #272** ruff format work | Mechanical autofixes; no audit impact. |

### New zero-importer files since v2 (all PLAN-PROTECTED / intentional foundation)

PR #214 added two boto3-wrapper services as the AWS foundation per
`docs/archive/launch-execution-plan-2026-05-23.md`. They're zero-importer at
runtime today, but explicitly intended as foundation for downstream features
(#148 HTTPS, #151 GPU EC2 + KB pipeline, #176 SSM secrets). 27 unit tests
cover both. **Both are PLAN-PROTECTED** by the same pattern as `agents/base.py`:
named in an active plan as a stub for upcoming work.

| File | Lines (approx) | Test coverage | Why zero-importer is OK |
|---|---:|---:|---|
| `backend/archimedes/services/dynamodb_paper_index.py` | — | ✅ `test_dynamodb_paper_index.py` | Named in launch plan; foundation for #151 KB pipeline |
| `backend/archimedes/services/s3_artifact_store.py` | — | ✅ `test_s3_artifact_store.py` | Named in launch plan; foundation for #151 KB pipeline + #148 HTTPS |

### Refreshed bottom line (still zero deletions recommended)

| File | v2 status | Refresh status |
|---|---|---|
| `agents/base.py` | PLAN-PROTECTED | unchanged |
| `services/regime_detector.py` | PLAN-PROTECTED, zero-importer | unchanged (no consolidation PR yet) |
| `services/_deprecated/portfolio_constructor.py` | PLAN-PROTECTED | unchanged |
| `services/_deprecated/kelly_portfolio.py` | PLAN-PROTECTED (test-only) | unchanged |
| `services/arxiv_corpus.py` | PLAN-PROTECTED (test-only) | unchanged (spine-plus-v2 #4 still open) |
| `services/source_tracker.py` | PLAN-PROTECTED (test-only) | **RESOLVED — now runtime-wired (PR #235)** |
| `services/statistical_regime.py` | PLAN-PROTECTED (test-only) | unchanged |
| `chain/strategy_publisher.py` | PLAN-PROTECTED (test-only) | unchanged |
| `tests/test_user_profile_privacy.py` | ORPHANED → MOVE | **RESOLVED — moved (PR #229)** |
| `StressScenarioPanel.jsx` | PLAN-PROTECTED, zero-importer | **RESOLVED — now runtime-wired (PR #258)** |
| `PortfolioAdvisor.jsx` | LIVE via Generate.jsx | unchanged |
| `CorrelationMatrix.jsx` | LIVE via Reasoning.jsx + PROTECTED | unchanged |
| `IPriceOracle.sol` | PLAN-PROTECTED, zero-importer | unchanged |
| Operator entrypoints (oracle_runner, kb_runner, scripts/*, forge scripts, stockbench/__main__) | LIVE as entrypoints | unchanged |
| `services/dynamodb_paper_index.py` (NEW) | n/a | PLAN-PROTECTED (launch plan), test-covered |
| `services/s3_artifact_store.py` (NEW) | n/a | PLAN-PROTECTED (launch plan), test-covered |

**Files safe-to-delete unilaterally: still 0.** Conditional deletion roadmap
(arxiv_corpus / _deprecated / regime consolidation) is unchanged — the
prerequisite PRs haven't shipped.

### Other useful telemetry from the refresh

- `backend/archimedes/tests/` directory was untouched by PR #229's `git mv`
  (it deleted the file but left the dir). It is now empty on `origin/main`. The
  dir itself can be `rmdir`'d in a tiny follow-up PR; leaving it is harmless.
- Backend test coverage rose materially in this window: 15+ new `backend/tests/services/test_*.py`
  files (PR #214's 60.66% coverage gate work). Several were for previously-untested
  services flagged in the survey (`test_regime_detector.py`, `test_kb_runner.py`,
  `test_amm_bootstrap.py`, etc.). None of those flip an audit verdict — they
  add tests for files that were already LIVE-via-entrypoint or
  PLAN-PROTECTED.

---

---

## Work Remaining Inventory (2026-05-25, submission day)

This section is the audit's primary deliverable for the final-window decision
making. For each currently-stubbed file or planned-but-not-shipped surface,
state precisely: **what exists today, what the plan says is supposed to exist,
what would constitute "shipped," and who owns the gap.** This is *not* a delete
list — it is a build list (and an honest "deferred" list).

The aim of organizing it this way is to make it trivially clear to a reader (or
to a `t2o2` issue author) what work is still on the table vs. what's done — and
to surface the gaps that don't have an owner yet.

### Closed since Refresh 1 (today) — confirmation

These issues / PRs landed today and need to be reflected in any prior reading
of the audit. Most were referenced as protection sources in v2:

| Closed | What | Status of the protected file(s) |
|---|---|---|
| **#147** | AWS S3 + DynamoDB for paper artifacts + IAM | Infrastructure complete; `services/s3_artifact_store.py` + `services/dynamodb_paper_index.py` are foundation code (still zero runtime importers) — see below. |
| **#151** | GPU EC2 + KB pipeline on 10k corpus → S3 / DynamoDB | Infrastructure complete; runtime wiring of pipeline output into the `/api/corpus/*` 503-or-real-data surface still needs to be exercised against the live KB artifacts. |
| **#173** | `agents/` subpackage with shared `base.py` | Subpackage created; `AgentLike` Protocol exists at `agents/base.py` (36 LOC); **no runtime adopter has imported it yet.** Sequel issues #163 + #164 carry the adoption work. |
| **#218** | StockBench harness (Önder) | Adapter consolidated to `evaluation/stockbench/adapter.py` (PR #239 Option C). LIVE via `__main__.py` entrypoint. |
| **#219** | Xia 2026 named protocols | `source_tracker.py` wired into `chain/agent_runner.py:40` (PR #235); `purged_kfold` + other protocols enumerated in [`docs/specs/xia-2026-protocols.md`](specs/xia-2026-protocols.md). |

### Still-stub files (zero runtime importers as of `2195417`)

For each: the runtime importer count (excluding tests + self-import), test
importer count, the plan that protects it, and what "shipped" looks like.

Verified by `grep -rE '(from|import) <module>( |$|\.)' backend/ scripts/
analytics-engine/` on 2026-05-25.

| File | LOC | runtime / test importers | Protecting plan | What "shipped" looks like | Owner |
|---|---:|---:|---|---|---|
| `backend/archimedes/agents/base.py` | 36 | 0 / 0 | Closed #173 (subpackage created), open #163 + #164 (concrete adopters) | A Strategy Generation Agent + Portfolio Construction Agent both declare `AgentLike` and the `services/` callsites switch to importing from `agents/` rather than `services/`. Until then the Protocol is genuinely unreferenced. | Önder (#163), Daniel R. / Önder (#164) |
| `backend/archimedes/services/regime_detector.py` | 111 | 0 / 1 | `docs/chuan-architecture-survey.md` gap #2 (regime consolidation); component-interfaces-spec | Önder reviews v1 (`regime_detector.py`) vs v2 (`statistical_regime.py`), picks one, deletes the other, and the surviving file is imported by `RegimePanel`'s data path. No issue filed yet. | Önder (architecture call) |
| `backend/archimedes/services/statistical_regime.py` | 466 | 0 / 1 | Same as above (gap #2) | Same as above — consolidation picks one or the other. | Önder |
| `backend/archimedes/services/_deprecated/portfolio_constructor.py` | 282 | 0 / 0 | `docs/specs/portfolio-constructor-decision-tree.md` retirement step | The decision tree's "retirement step" gets ticked (the surviving constructor(s) cover all callsites in `services/strategy_fusion.py` + the rebalance path) and the `_deprecated/` directory is deleted. | Önder (decision-tree owner) |
| `backend/archimedes/services/_deprecated/kelly_portfolio.py` | 523 | 0 / 1 | Same retirement step | Same as above. | Önder |
| `backend/archimedes/services/arxiv_corpus.py` | 478 | 0 / 1 | `docs/specs/spine-plus-v2-plan.md:909` (Phase 7 dedup #4) marked **Defer**; corpus-architecture.md as the canonical seed/intake path | Spine-plus-v2's "#4 Arxiv intake paths" consolidation PR ships, picking one of: `arxiv_corpus.py`, `corpus_service.py`, or `scripts/bulk_ingest_arxiv.py` as canonical. Currently deferred pending Dan's KB pipeline stabilization. | Dan |
| `backend/archimedes/chain/strategy_publisher.py` | 190 | 0 / 6 | `docs/archive/launch-execution-plan-2026-05-23.md` (publishes Strategy Passport metadata on-chain via `StrategyRegistry` contract) | `StrategyPublisher` gets called from the strategy-deploy path (post-passport-creation) so passports anchor on-chain alongside reasoning traces. Today only the trace half is wired (`source_tracker` → `ReasoningTraceRegistry`); passport half is stub. | Chuan / Marten |
| `backend/archimedes/services/dynamodb_paper_index.py` | NEW since v2 | 0 / 1 | `docs/archive/launch-execution-plan-2026-05-23.md`; closed #147 + #151 | KB pipeline output (paper-level metadata + cluster ID + embedding pointer) actually writes to DynamoDB on a pipeline run, and `corpus_routes.py` reads from it for the Explorer. Today: code exists, integration tested with mocks, no live KB artifact has been written yet. | Dan (KB pipeline), Chuan (infra glue) |
| `backend/archimedes/services/s3_artifact_store.py` | NEW since v2 | 0 / 1 | Same as above | KB pipeline output (artifact JSON / pickled topic model / SPECTER2 embeddings) actually writes to S3 and `corpus_routes.py` resolves artifact pointers when serving the Explorer. Same status as DynamoDB — code exists, no live KB artifact yet. | Dan + Chuan |
| `contracts/src/interfaces/IPriceOracle.sol` | 36 | n/a (Solidity interface) | `docs/specs/component-interfaces-spec.md`, `docs/specs/ecosystem-design-spec.md` | An off-chain consumer (e.g. a future external indexer or third-party oracle client) imports the interface ABI. **Today the interface is referenced by the spec but not implemented against by any external party** — keeping it is correct (it's a published contract); deleting would break the spec promise. | Chuan |

**Aggregate count:** **10 stub files** carrying ~2,706 LOC, all protected by an
active plan or interface promise. Zero are deletable today. Each row's "what
shipped looks like" answers Dan's question literally — these are the gaps.

### Plan gaps — work spec'd but not built (Phase 4 + Phase 5 + 3c + 9)

The `docs/specs/spine-plus-v2-plan.md` phase status snapshot as of `2195417`:

| Phase | Status | What's missing |
|---|---|---|
| **Phase 0** — Architectural Specs | ✅ LANDED | — |
| **Phase 1** — Junk extermination + UX fixes | ✅ LANDED | — |
| **Phase 2** — Streaming Generate on `portfolio_agent.py` | ✅ LANDED | — |
| **Phase 3a + 3b** — Real Explore + Corpus depth | ✅ LANDED | — |
| **Phase 3c** — KB integration | 🟡 SKELETON ONLY | Production pipeline body deferred pending Dan's Linus-side iteration. `services/kb_runner.py` + `services/kb_artifacts.py` + `scripts/run_kb_pipeline.py` exist as the runtime hooks; the pipeline has not been *run* end-to-end against the 10k corpus on the GPU EC2 host. `/api/corpus/*` returns **503 "kb_artifact_not_found"** until a real artifact lands. **Closed #151 means infra is ready; the artifact run is the remaining step.** |
| **Phase 4** — Vault encapsulation (1:1, time-bound) | 🟠 PARTIAL | `vaults_routes.py` exists (7 endpoints incl. `/create`, `/{addr}/metadata`, `/{addr}/derive-allocations`), `CreateVaultModal.jsx` + `StrategyPassport.jsx` + `DepositFlow.jsx` exist on the frontend. **MISSING:** `services/vault_lifecycle.py` — no PENDING → ACTIVE → COMPLETED state machine; `vault_service.py` has the data layer but no time-bound trade-window enforcement. The flow today is "create vault → deposit → agent rebalances perpetually." The 1:1 time-bound model is unimplemented. **Pending Chuan + Marten alignment on the 5 open questions in the phase spec.** |
| **Phase 5** — Real testnet trade execution | 🟠 CODE-COMPLETE / UNVERIFIED | `DepositFlow.jsx` issues approve + deposit + setTargetAllocations; `chain/executor.py:143` calls `vault.rebalance(tokens_in, amounts_in, tokens_out, amounts_out)`; `chain/agent_runner.py:446` records the rebalance. The path *exists* in code. What's missing is the end-to-end verification: one signed execution from a real wallet that results in (a) USDC deposited, (b) vault holds synth tokens, (c) on-chain trace anchored, (d) Portfolio reflects state. **No runbook documents this has actually happened on Arc testnet from the live UI.** |
| **Phase 6** — Onboarding tour | ✅ LANDED | PR #134; Phase 8 polish (#262) also landed. |
| **Phase 7** — Consolidation & dedup via t2o2 | ✅ LANDED | All 6 issues (#128–#133) closed. |
| **Phase 8** — Landing polish | ✅ LANDED | #262 + #263 today. |
| **Phase 9** — Fusion engine UI surface (third Generate mode toggle) | 🟠 NOT STARTED | `phase8-9-landing-and-fusion-spec.md` spec exists but no Generate-mode toggle UI ships. Backend `POST /api/strategies/generate?mode=fusion` is referenced in the spec; verify whether the endpoint exists and whether the UI exposes it. |

### Open issues with build work remaining

| Issue | Title | What it adds | Status as of `2195417` |
|---|---|---|---|
| **#163** | APIN - Backend - Strategy Generation Agent emits BOTH a bull-tilted AND a bear-tilted candidate per Generate call | Adopts `AgentLike` Protocol (would activate `agents/base.py`); changes Generate UX to surface considered-alternatives panel against current K=1 | OPEN — Önder |
| **#164** | APIN - Backend - Portfolio Construction Agent reads regime + applies bull/bear weight schedule | Second adopter of `AgentLike` Protocol; reads from regime detector output | OPEN — depends on #163's regime read |
| **#160** | APIN - Backend - Unify file-based + StrategyRecord ORM into ONE `strategy_passports` Postgres table | Migration consolidating two strategy persistence layers | OPEN |
| **#155** | APIN - Infra - AWS ALB + CloudFront + ASG: virality-ready backend tier | Production-scale infra; **post-hackathon** | OPEN, low priority for submission |
| **#154** | APIN - Backend+Security - [OPTIONAL] AWS Bedrock as primary LLM with IAM auth | Optional second LLM provider | OPEN, optional |
| **#212** | [security] Supply-chain hardening roadmap | pip-audit promoted to CI gate + SBOM + Dependabot triage | OPEN |
| **#43, #41** | Platform - Registration Page / User Management | Multi-user onboarding | OPEN, not for MVP |
| **#16** | APIN - DEMO - Final delivery (hackathon) | The submission itself | OPEN — closed when submitted |

### Summary — what to brief judges on if they ask "what's not built"

The honest, defensible answer (works because each item has a *named* plan and
owner):

1. **Vault lifecycle states (PENDING / ACTIVE / COMPLETED with a trade window):**
   spec'd in Phase 4; vault contract supports the data, but the off-chain
   state-machine worker (`vault_lifecycle.py`) and the time-bound enforcement
   are not built yet. Today vaults are "always Active."
2. **End-to-end testnet execution verified from the live UI:** code-complete
   (Phase 5), unverified. We have the path; we don't have a recorded runbook
   showing one signed execution from a real wallet results in the full
   USDC→synth→trace anchor cycle. Demo includes the path; production "we ran
   it twice" is the missing bit.
3. **KB pipeline production run:** infrastructure shipped today (#147, #151).
   The first end-to-end artifact run hasn't happened yet — Corpus Explorer
   returns 503 "first artifact pending" until it does.
4. **Two-agent generation (bull + bear candidates):** spec'd via #163; would
   activate the `agents/` subpackage. Current Generate is single-candidate K=1
   per the [`CLAUDE.md` § 5](../CLAUDE.md) architectural decision.
5. **Strategy passport on-chain anchoring (`strategy_publisher.py`):** code
   complete with 6 tests; not yet invoked from the deploy path. The trace half
   of "on-chain provenance" ships today; the passport half is the next hop.
6. **Three regime detectors / portfolio constructors / arxiv intake paths
   coexist** because consolidation decisions need a quiet hour Önder + Dan
   haven't had yet. None of the duplicates hurt correctness; they're style
   debt with a known cleanup path.

None of these are surprises; all six are documented; none affect what judges
see in the live demo. The discipline is in *naming them as gaps* rather than
hiding them behind aggregate scoring.

---

## See also

- v1 retracted: not retained on `main` (lived only in conversation context + an
  uncommitted file that was blown away by a branch switch — itself a lesson
  about not relying on uncommitted artifacts in a multi-agent checkout)
- `docs/chuan-architecture-survey.md` — the survey v2 cross-references for
  redundancy clusters #1 (rigor), #2 (regime), #3 (LLM backends), #4 (arxiv),
  #5 (portfolio constructors)
- `docs/specs/portfolio-constructor-decision-tree.md` — canonical for the
  `_deprecated/` retirement plan
- `docs/specs/xia-2026-protocols.md` — protects `source_tracker.py`
- `docs/specs/spine-plus-v2-plan.md` § "#4 Arxiv intake paths" — protects
  `arxiv_corpus.py` for now
- Closed Issue #173 + open Issues #163/#164 — context for `agents/base.py`
