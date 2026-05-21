# Chuan's Architecture Survey — `backend/archimedes/`

> **Audience:** Marten, Dan, the team. Recon document — describes the surface, names
> the gaps, **does not act on them**. Per-file follow-ups happen on subsequent
> prompts.
> **Scope:** the entire `backend/archimedes/` FastAPI package. Chuan-via-`t2o2`
> (his agentic system) holds **52 of the 91 commits** under this tree —
> more than every other contributor combined. The narrow `chain/` subdir is
> Chuan-the-person's literal lane per `CLAUDE.md`; the rest is Chuan-as-architect
> via the bot pipeline.
> **Method:** for every `*.py` file, I extracted line count, first-commit author,
> module docstring, public symbols, and `TODO|FIXME|NotImplementedError` markers.
> Raw data: `/tmp/backend_survey_raw.txt` (regenerable). Per-file commit history
> via `git log --author='t2o2' --author='chuan@gyld.fi' -- backend/archimedes/`.
> **Status:** as of `main` HEAD on 2026-05-21 (post-#117). The strip-to-spine PR
> (`#118`, open) doesn't structurally change `backend/archimedes/` — same survey
> applies before/after the strip merges.

## Quick stats

- **Files surveyed:** 75 `*.py` under `backend/archimedes/`
- **Top files by Chuan/`t2o2` commit count:** `api/routes.py` (19), `main.py` (16),
  `api/schemas.py` (6), `services/vault_service.py` (5), `services/strategy_fusion.py` (5),
  `services/strategy_architect.py` (5)
- **Author distribution under this tree:** `t2o2` 52 · Önder 20 · Daniel Browne (me) 14 ·
  Dan Browne 2 · Chuan (personal) 2 · danielscoffee 1

## File tree

```
backend/archimedes/
├── __init__.py
├── main.py                 ← app entrypoint + startup hooks
├── db.py                   ← SQLAlchemy async session factory
├── api/                    ← FastAPI routes + Pydantic schemas (11 files)
├── chain/                  ← Chuan's personal lane: web3 + Circle + on-chain (8 files)
├── interfaces/             ← frozen Protocol contracts (4 files)
├── models/                 ← SQLAlchemy ORM + dataclass models (11 files)
├── scripts/                ← operational scripts (4 files + __init__)
└── services/               ← business logic (25 files + __init__)
```

---

## Package root

- **`__init__.py`** (1 line) — empty package marker. **No gap.**
- **`main.py`** (195 lines, **`t2o2`** primary) — FastAPI app entrypoint. Two startup hooks: `_startup_populate_rigor_gate()` and `_startup_seed_corpus()`. Exposes `/health`, `/`. **Gap:** uses deprecated `@app.on_event("startup")` (FastAPI deprecation warning in test output); migrate to lifespan handler.
- **`db.py`** (68 lines, **`t2o2`**) — async engine + `get_session()`. Falls back from `DATABASE_URL` to local SQLite. **Gap:** none structural, but the strip commit added idempotent `ALTER TABLE` for `papers.cluster_id/topic_label/content_hash` here — that migration approach is fragile (no Alembic). Worth tracking if the column set grows.

---

## `api/` — route handlers + frontend contracts

- **`__init__.py`** (2 lines) — empty. **No gap.**
- **`architect_schemas.py`** (84 lines, **Daniel B. / me**) — request/response schemas for the strategy architect. Deliberately separate from `schemas.py` to avoid the announce-before-changing policy on the frontend contract. **Gap:** flagged in its own docstring — fold into `schemas.py` later if it stabilizes.
- **`chat_routes.py`** (145 lines, `t2o2`) — per-vault chat endpoints. **Gap:** none obvious; well-scoped per `ecosystem-design-spec.md § 16–17`.
- **`marketplace_routes.py`** (153 lines, `t2o2`) — community strategy discovery. Lists / featured / trending / categories. **Gap:** consumes `marketplace_service.py` which is entirely seed data — endpoints work, but the data they return isn't real (see `marketplace_service.py` below).
- **`marketplace_schemas.py`** (253 lines, `t2o2`) — Pydantic models for marketplace responses. **Gap:** none structural; tied to `marketplace_service.py`'s seed-data model.
- **`risk_routes.py`** (231 lines, `t2o2`) — risk analysis aggregator (`/api/risk/portfolio`, `/api/risk/profiles`). **Gap:** none obvious; Önder's `RiskAnalysis.jsx` was the consumer (now deleted by strip — front-end consumer needs to relocate to `/portfolio` per the strip).
- **`risk_schemas.py`** (80 lines, `t2o2`) — risk band response models. **Gap:** none.
- **`routes.py`** (**2199 lines**, `t2o2`) — *the* main API surface. Asset / vault / strategy / efficient-frontier / correlation endpoints. **Gap (a):** line 172 has `# TODO: Implement with stored price history` (asset price history is stubbed). **Gap (b):** at 2200 lines it's a monolithic file — splitting by resource (assets / vaults / strategies / frontier) would improve discoverability.
- **`schemas.py`** (489 lines, `t2o2`) — the frontend contract. Asset / vault / strategy / trace response shapes. **Gap:** none structural; touching it triggers the announce-before-changing policy.
- **`selection_bias_routes.py`** (296 lines, `t2o2`) — rigor gate endpoints (per-strategy + bulk + PBO). **Gap:** `_synthetic_returns_from_stub()` and `_load_strategy_code()` are private helpers — the PBO endpoint synthesizes returns from stub metrics when no real returns are stored, which is an honest fallback but worth verifying it's still in use given Önder's `rigor_evaluator.py` work.
- **`vault_schemas.py`** (60 lines, `t2o2`) — vault create / metadata / allocation request-response models. **Gap:** no module docstring.

---

## `chain/` — Chuan's personal lane

- **`__init__.py`** (14 lines, `t2o2`) — package docstring describing the three interface implementations. **No gap.**
- **`agent_runner.py`** (**744 lines**, `t2o2`) — `StrategyRunner` class — the autonomous loop that polls market, evaluates signals, rebalances vaults, publishes traces. *"This IS the intelligence layer."* Configured via env (`AGENT_INTERVAL_SECONDS`, `AGENT_DRY_RUN`, `AGENT_VAULT_ADDRESSES`, `AGENT_USDC_FLOOR`). **Gap:** 744 lines for one runner is a lot; observability (per-tick logs, failure modes) lives implicit in the run loop. Worth confirming the `_DRIFT_THRESHOLD = 0.15` is the intended value (the kelly-portfolio uses `0.05`).
- **`circle_signer.py`** (246 lines, `t2o2`) — `CircleSigner` — submits contract executions via Circle's managed-wallet REST API; polls until terminal. Replaces raw private-key signing for vault operations. **Gap:** 60 polls × 2s = 2 min max; if a Circle call hangs longer the runner stalls. Bounded but inflexible.
- **`client.py`** (147 lines, `t2o2`) — `ChainClient` singleton + `ChainSettings` Pydantic config. AsyncWeb3 against Arc testnet RPC. **Gap:** none obvious; settings init at module import-time has been a test-mocking pain point (two tests `SKIPPED` in CI cite "Requires chain_client.settings module-level init mocking").
- **`contracts.py`** (100 lines, `t2o2`) — `ContractLoader` reads ABIs from `contracts/abis/` and binds to deployed addresses from `ChainSettings`. **Gap:** none.
- **`executor.py`** (442 lines, `t2o2`) — `ChainExecutor` implements `IChainExecutor`. Reads portfolio state, executes rebalance trades, creates vaults. **Gap:** at 442 lines, encapsulates both reads and writes; splitting (`reader.py` + `writer.py`) would help.
- **`oracle_runner.py`** (52 lines, `t2o2`) — standalone process loop (`python -m archimedes.chain.oracle_runner`). Thin — calls `OracleUpdater.update_all_prices()` every `ORACLE_INTERVAL_SECONDS`. **Gap:** none structural.
- **`oracle_updater.py`** (303 lines, `t2o2`) — `OracleUpdater` — fetches yfinance + CoinGecko prices, pushes to `PriceOracle` contract via Circle. Maps tickers (`YFINANCE_MAP`, `CRYPTO_MAP`). **Gap:** the `YFINANCE_MAP` is hardcoded (10 symbols); adding new synth assets requires editing this file.
- **`trace_publisher.py`** (196 lines, `t2o2`) — `TracePublisher` implements `ITracePublisher`. Anchors `keccak256` hashes to `ReasoningTraceRegistry`. **Gap:** none structural; the IPFS / Pinata pinning design (per `docs/specs/ipfs-reasoning-traces-design-note.md` on the strip branch) hasn't been wired here yet.

---

## `interfaces/` — frozen Protocol contracts

These were defined early as the contract surface for the 5-person concurrent build per `docs/specs/component-interfaces-spec.md`. All authored by `t2o2`.

- **`__init__.py`** (32 lines). **No gap.**
- **`agent.py`** (90 lines) — `IAgentOrchestrator`. Docstring says "Chuan implements this" — implementation is in `chain/agent_runner.py`. **Gap:** ownership comment is now stale (the bots wrote both); update the docstrings if accuracy matters.
- **`chain.py`** (156 lines) — `IOracleUpdater`, `IChainExecutor`, `ITracePublisher`. Docstring says "Marten implements these" — currently implemented in `chain/oracle_updater.py`, `chain/executor.py`, `chain/trace_publisher.py` (by `t2o2`, not Marten). **Gap:** same stale ownership.
- **`math.py`** (134 lines) — `IRegimeDetector`, `IPortfolioConstructor`, `IBacktestEvaluator`. Docstring says "Önder implements these." `IBacktestEvaluator` is real (the analytics-engine populates `BacktestResult`); `IRegimeDetector` is implemented twice (heuristic + statistical); `IPortfolioConstructor` is partly implemented (Kelly + MVO). **Gap:** the interface and the multiple implementations are drifting — see services/ gaps below.
- **`strategy.py`** (73 lines) — `IStrategyProvider`. Docstring says "Dan implements this." Implementation is `services/strategy_provider.py` by Daniel B. (me). **No gap.**

---

## `models/` — ORM + dataclass models

- **`__init__.py`** (59 lines, `t2o2`). **No gap.**
- **`asset.py`** (78 lines, `t2o2`) — `AssetInfo`, `AssetPrice`, `MarketSnapshot` dataclasses. **No gap.**
- **`backtest_store.py`** (165 lines, **danielscoffee** primary) — `BacktestResultRecord` SQLAlchemy ORM. **Gap:** Daniel R. authored; consumes `analytics-engine` artifacts via `services/backtest_repository.py`.
- **`backtest.py`** (181 lines, `t2o2`) — `BacktestResult` dataclass with the full selection-bias contract (DSR, PBO, OOS, look-ahead audit flag). Has `passes_validation` + `passes_rigor_gate` properties. **Gap:** none structural; this is the spec-aligned shape Önder + Daniel R. populate.
- **`chat.py`** (96 lines, `t2o2`) — `VaultMetadata` + `ChatMessage` ORM (this is also where the `Base = DeclarativeBase` is exported and re-used by other model files). **Gap:** `chat.py` owning `Base` is a fragile import structure — adding a model that doesn't want chat deps still requires importing through `chat.py`.
- **`corpus_store.py`** (79 lines, `t2o2`) — `PaperRecord` + `CorpusMetaRecord` (the corpus DB substrate). **Gap:** `cluster_id`/`topic_label`/`artifact_hash`/`artifact_built_at` columns exist but are unwritten (waiting on the `#101` KB pipeline). `quality_signal` fields from the spec are absent.
- **`portfolio.py`** (149 lines, `t2o2`) — `RiskProfile` enum + `Portfolio`/`PortfolioHolding`/`TargetAllocation`/`TradeOrder`/`RebalanceDecision` dataclasses. **No gap.**
- **`regime.py`** (56 lines, `t2o2`) — `Regime` enum + `RegimeSignals` + `RegimeClassification`. **No gap.**
- **`strategy_store.py`** (188 lines, `t2o2`) — `StrategyRecord` ORM with content-hashed dedup, status transitions, source-paper provenance. **Gap:** `_compute_content_hash()` + `upsert_strategy()` are the substrate the strip's `/api/strategies/generated` reads from — verified live.
- **`strategy.py`** (173 lines, `t2o2`) — `Strategy` dataclass (passport-aware, with paper provenance fields). **Gap:** none; spec-aligned per `strategy-passport-spec.md`.
- **`trace.py`** (99 lines, `t2o2`) — `ReasoningTrace` dataclass + `DecisionType` enum. **Gap:** imports `web3` at module level (`from web3 import Web3`) which is a heavy dep for a model file — the hash computation could live in a helper instead.
- **`vault.py`** (66 lines, `t2o2`) — `VaultInfo`, `VaultMetrics`, `VaultTier`. **No gap.**

---

## `scripts/` — operational scripts

- **`__init__.py`** (0 lines, `t2o2`). **No gap.**
- **`bootstrap_vaults.py`** (556 lines, `t2o2`) — bootstraps the demo ecosystem (sets oracle prices, mints synthetics, creates vaults, funds + allocates, adds AMM liquidity, verifies). Hardcoded `TARGET_PRICES` + `VAULT_PROFILES` + `MINT_BUDGET`. **Gap:** operational, works, but tightly coupled to specific demo state — re-running is non-trivial.
- **`hydrate_corpus.py`** (151 lines, `t2o2`) — deploy-time corpus PDF/text hydration. Polite (3s delay), idempotent (sha256 cache). **Gap:** not auto-invoked anywhere — operator-triggered only.
- **`run_backtests.py`** (180 lines, **danielscoffee**) — invokes the analytics-engine and persists results. **Gap:** Daniel R. authored; runs the analytics suite as a separate process.
- **`seed_backtests_from_artifacts.py`** (119 lines, `t2o2`) — loads pre-existing artifact JSON into `backtest_results` table without re-running. **Gap:** deployment-time loader; operator-triggered.

---

## `services/` — business logic (the heart of the architecture)

### Domain: corpus + arxiv

- **`arxiv_corpus.py`** (489 lines, **Dan Browne** primary) — Dan's original q-fin scraper (Stream A) that built the seed `manifest.jsonl`. **Gap:** **redundant** with `corpus_service.py` (DB-backed) + `scripts/bulk_ingest_arxiv.py` (the 10k expansion path). Worth deciding which of these stays canonical.
- **`arxiv_pipeline.py`** (324 lines, **Daniel B. / me** primary) — implements `IStrategyProvider.extract_from_paper` (PDF → text → LLM-synthesized passport → rendered strategy module). Uses `pypdf` (BSD-3) not PyMuPDF. **Gap:** wired but not invoked on a live demo path — the curated `analytics-engine/strategies/*.py` is what actually loads.
- **`corpus_service.py`** (295 lines, `t2o2`) — DB-first read/seed/intake of the q-fin corpus. **Gap:** `intake_from_arxiv()` exists but no periodic scheduler; `CORPUS_MAX` retention not enforced (no eviction). See `docs/corpus-architecture.md` for the fuller "what's wired vs not" picture.

### Domain: strategy generation

- **`strategy_provider.py`** (494 lines, **Daniel B. / me** primary) — `LocalStrategyProvider` reads `analytics-engine/strategies/*.py` via AST (no backtrader import), computes methodology hash + strategy id, loads fixtures. **Gap:** strip commit added `backtest_start/end` exposure — verify it's still parsing correctly post-rebase.
- **`strategy_architect.py`** (411 lines, **Daniel B. / me** primary) — interactive Claude-driven architect that selects + weights pre-curated strategies. **Gap:** owns its own `LLMBackend` Protocol + `ClaudeBackend` impl — duplicates the abstraction in `llm_backend.py`. Worth unifying.
- **`strategy_fusion.py`** (650 lines, **Dan Browne** primary) — multi-paper novelty-seeking synthesis. Loads corpus DB-first with file fallback. **Gap:** uses **keyword selection** over corpus (not embeddings — that's `#96`); duplicates `LLMBackend`/`ClaudeBackend`/`CannedBackend` pattern from `strategy_architect.py`. Has a feature flag `fusion_enabled()`.
- **`strategy_guardrail.py`** (169 lines, **Daniel B. / me** primary) — deterministic weight normalizer + USYC-floor reserver + max-weight cap. Step-2 of the architect path. **Gap:** none structural.
- **`strategy_signal_evaluator.py`** (444 lines, `t2o2`) — extracts live allocation signals from `analytics-engine/strategies/*.py` (without backtrader). Hardcoded per-strategy signal evaluators (`_faber_sma200_signal`, `_vol_managed_signal`, `_tsmom_signal`, `_buy_hold_signal`). **Gap:** adding a new paper-grounded strategy requires editing this file (`_get_evaluator` dispatch); not data-driven.

### Domain: regime detection

- **`regime_detector.py`** (108 lines, `t2o2`) — **v1 heuristic** VIX thresholds. Docstring says "v1 until the full statistical classifier lands from [Önder's] lane." **Gap:** **superseded** by `statistical_regime.py` but both still exist on disk.
- **`statistical_regime.py`** (463 lines, `t2o2`) — **v2** Gaussian Mixture Model + multi-signal scoring + transition probabilities + confidence. **Gap:** unclear which version is wired in the runtime (Önder's #115 added a `RegimePanel` UI; need to check which detector backs it).

### Domain: portfolio construction + rigor

- **`portfolio_constructor.py`** (285 lines, `t2o2`) — `PortfolioConstructor` — given regime + strategies + risk profile, produces target allocations. Falls back to equal-weight; calls MVO when `price_histories` supplied. **Gap:** hardcoded `_DEFAULT_SYNTHS` list; `_DRIFT_THRESHOLD` differs from `agent_runner.py`'s value.
- **`portfolio_optimizer.py`** (282 lines, **Önder Akkaya**) — pure MVO: GMV / Max Sharpe / Max Expected Return per risk profile. **Gap:** none structural.
- **`kelly_portfolio.py`** (505 lines, `t2o2`) — `KellyRiskParityConstructor` — Kelly sizing + inverse-vol risk parity + USDC floor + regime-aware deleveraging. **Gap:** at 505 lines this is the largest constructor — relationship to `portfolio_constructor.py` and `portfolio_optimizer.py` deserves diagramming. Three constructors is a lot.
- **`rigor_evaluator.py`** (348 lines, **Önder Akkaya**) — DSR / PBO / OOS Sharpe / Kelly fraction / Sharpe CI computation. **Gap:** **duplicates** `selection_bias.py` (DSR + PBO are computed in both). Önder's version is newer (recent #114). Worth deciding which is canonical.
- **`selection_bias.py`** (534 lines, `t2o2`) — older `RigorGateResult` + `run_rigor_gate()` + look-ahead audit. **Gap:** see above — overlaps `rigor_evaluator.py`.

### Domain: vault + chain glue (consumed by the API layer)

- **`asset_service.py`** (59 lines, `t2o2`) — composes chain + oracle data for asset responses. **Gap:** thin; could fold into `routes.py`.
- **`vault_service.py`** (377 lines, `t2o2`) — composes `ChainExecutor` data into API responses. **Gap:** none structural; the `metadata_hash` computation pattern is repeated in a couple of services — could DRY.
- **`vault_monitor.py`** (220 lines, `t2o2`) — periodic vault metric snapshots, AUM trend, oracle staleness, McLean-Pontiff Sharpe decay. **Gap:** snapshot collection is called from `agent_runner.tick()` but the API helpers for the monitoring dashboard / SSE stream are deferred.
- **`amm_bootstrap.py`** (106 lines, `t2o2`) — quick on-demand AMM liquidity addition. **Gap:** the docstring flags it as a workaround ("the initial bootstrap didn't add AMM pool liquidity") — fix is in `bootstrap_vaults.py`; this is the compensating service.
- **`circle_service.py`** (121 lines, `t2o2`) — Circle SDK breadth showcase. **Gap:** the docstring is explicit: *"demonstrates breadth of Circle tool usage…for the rubric's 20% Circle Tool Usage category."* This is judge-oriented, not load-bearing.
- **`config_service.py`** (49 lines, `t2o2`) — serves deployed contract addresses to the frontend. **Gap:** thin.

### Domain: cross-cutting

- **`__init__.py`** (6 lines, **Daniel B. / me**) — package docstring naming ownership. **Gap:** ownership comment is stale (much was rewritten by `t2o2`).
- **`backtest_mapper.py`** (188 lines, **danielscoffee**) — Pydantic models + mappers for analytics-engine artifacts → `BacktestResult`. **Gap:** Daniel R. lane.
- **`backtest_repository.py`** (172 lines, **danielscoffee**) — read/write helpers for `backtest_results` table. **Gap:** Daniel R. lane.
- **`chat_service.py`** (259 lines, `t2o2`) — message persistence + AI response generation + auto-post on rebalance/regime. **Gap:** `AI_WALLET_ADDRESS = "0x0000000000000000000000000000000000000000"` is a placeholder; if the AI identity should be on-chain identifiable, this needs a real wallet.
- **`chat_routes.py` → `chat_service.py`** ties to **`models/chat.py`** — full chat stack is wired.
- **`construction_trace.py`** (102 lines, **Daniel B. / me**) — builds `ReasoningTrace` for architect output + computes integrity hash. *"This module STOPS at the hash. It never touches the chain."* Hard seam. **Gap:** none; clean.
- **`job_queue.py`** (107 lines, `t2o2`) — Redis-backed async job queue for strategy generation. **Gap:** the strip commit notes that fusion traces now flow to `/api/traces` automatically; verify the job-queue + trace persistence are coherent.
- **`llm_backend.py`** (307 lines, `t2o2`) — provider-agnostic LLM backend factory (`LLM_PROVIDER` ∈ {anthropic, anthropic_compatible, openai, ollama}); falls back to `CannedBackend`. **Gap:** `strategy_architect.py` + `strategy_fusion.py` each define their *own* `LLMBackend` Protocol + `ClaudeBackend` + `CannedBackend` instead of using this one. Three parallel abstractions.
- **`marketplace_service.py`** (**1005 lines**, `t2o2`) — community strategy seed data. **Gap:** docstring: *"Eventually this will connect to a database for user-created strategies."* Currently 1000+ lines of hardcoded seed data — large for what it is, and entirely fake.
- **`redis_state.py`** (258 lines, `t2o2`) — `AgentStateStore` over Redis. Persists regime, heartbeat, last-rebalance per vault, traces + trace index. **Gap:** none structural; this is now the trace-index backing for `/api/traces`.

---

## Aggregate gap clusters (where to look first)

Roughly in priority order for "where to fill gaps next" given the launch window:

1. **Redundancy: rigor implementation** — `selection_bias.py` (534 lines, `t2o2`, older) overlaps `rigor_evaluator.py` (348 lines, Önder, newer). Pick one as canonical and delete or wrap the other. Active risk: any future rigor bug fix may land in the wrong file.
2. **Redundancy: regime detection** — `regime_detector.py` (v1 heuristic) vs `statistical_regime.py` (v2). Unclear which is wired to the live agent loop and the new `RegimePanel` (#115). Decide which is canonical.
3. **Redundancy: LLM backends** — three parallel `LLMBackend` Protocols + `ClaudeBackend` + `CannedBackend` impls (in `llm_backend.py`, `strategy_architect.py`, `strategy_fusion.py`). Unify on `llm_backend.py`.
4. **Redundancy: arxiv intake paths** — `arxiv_corpus.py` (Dan, Stream A), `corpus_service.py` (DB-backed), `scripts/bulk_ingest_arxiv.py` (#97 expansion). Cross-cutting; `corpus_service.py` is the canonical going forward but the other two still exist.
5. **Redundancy: portfolio constructors** — `portfolio_constructor.py` (orchestrator), `portfolio_optimizer.py` (Önder's MVO), `kelly_portfolio.py` (Kelly + risk parity). Three constructors with overlapping responsibilities; a diagram of who calls whom under what regime would help.
6. **Monolith: `api/routes.py`** — 2199 lines is hard to navigate. Splitting by resource (assets / vaults / strategies / frontier) would improve discoverability; the existing dedicated routers (`chat_routes.py`, `marketplace_routes.py`, `risk_routes.py`, `selection_bias_routes.py`) prove the pattern works.
7. **Stale interface ownership comments** — `interfaces/agent.py`, `chain.py`, `math.py` say "Chuan implements" / "Marten implements" / "Önder implements" but everything was written by `t2o2`. Cosmetic but misleading for new contributors.
8. **`marketplace_service.py` seed-data weight** — 1005 lines of fake community strategies. If the marketplace surface lives post-launch, this becomes the longest "real data" gap.
9. **Scheduled intake / artifact build** — `corpus_service.intake_from_arxiv()` exists but no periodic task; `archimedes-corpus-artifact` volume mounted but empty. Both flagged in `docs/corpus-architecture.md`; both blockers for the "dynamic, continuously fresh" claim.
10. **Operational scripts as scripts, not as commands** — `bootstrap_vaults.py` (556 lines), `hydrate_corpus.py`, `seed_backtests_from_artifacts.py`, `run_backtests.py` are all operator-triggered. A `Makefile` target per script (per `#106`'s `make corpus` follow-on) would make them discoverable and CI-able.
11. **TODO marker** — `routes.py:172` `# TODO: Implement with stored price history` (asset price history is stubbed). Small but visible to anyone reading the API.
12. **`circle_service.py` is judge-oriented** — explicit in the docstring. Not a bug, but worth being aware that this is rubric-surface, not product-surface.

---

## See also

- [`docs/corpus-architecture.md`](corpus-architecture.md) — the corpus-specific deep-dive
  that overlaps the "Domain: corpus + arxiv" section above
- [`docs/specs/component-interfaces-spec.md`](specs/component-interfaces-spec.md) — the
  original frozen-interface contract these `interfaces/*.py` files derive from
- [`docs/specs/strategy-passport-spec.md`](specs/strategy-passport-spec.md) +
  [`docs/specs/selection-bias-corrections-spec.md`](specs/selection-bias-corrections-spec.md) —
  the contracts `BacktestResult` and the rigor evaluators implement
- [`CLAUDE.md`](../CLAUDE.md) — lead+coverage table (post-lanes-softening)
