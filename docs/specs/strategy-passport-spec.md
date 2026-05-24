# Strategy Passport — Implementation Contract

> **Audience:** Backend engineers + on-chain integration (Chuan / Marten) + UI (Daniel R. / Marten)
> **Status:** Implementation contract — post-Track-E unification (multi-paper + regime-aware + on-chain-anchored). Supersedes the Day-2 draft that described scalar-paper fields, deprecated decision endpoints, and an inline-alter migration. The unified `strategy_passports` table is the source of truth.
> **Last revised:** 2026-05-23 (Track E launch plan landing).
> **Reference doc:** [`docs/diagrams/strategy-passport-architecture.md`](../diagrams/strategy-passport-architecture.md) — canonical architecture + mermaid diagrams. This spec is the contract that doc describes.
> **Prerequisite reading:** [`../architectural-principles.md`](../architectural-principles.md) for the philosophy; [`selection-bias-corrections-spec.md`](selection-bias-corrections-spec.md) for the rigor gate.

## Goals

Three goals; everything in this spec serves one of them.

- **Independent auditability.** Any third party — judge, user, future agent, regulator — can recompute the methodology hash + paper corpus hash from the stored passport content and verify the result against the on-chain `StrategyRegistry.sol` entry. No trust in Archimedes-the-platform required. This is the Xia et al. (2026, arxiv 2605.19337) R3 reproducibility bar — **0/19** trading-agent studies in their audit cleared it.
- **Fusion-native multi-paper provenance.** Every passport carries a `papers: list[PaperRef]` from day one. Single-paper strategies have one entry; fusion strategies have N. The paper-claim delta for fusion strategies is a *blended* expectation, surfaced honestly per-paper (not hidden behind an aggregate score).
- **Regime-aware structural diversification.** Every passport carries a `regime_tag` enum (`bull` / `bear` / `regime_neutral`). The Portfolio Construction Agent reads this column to balance bull + bear exposure per the current macro regime — answering the StockBench (Chen et al. 2026, arxiv 2510.02209) finding that **14/14** evaluated LLM trading agents underperformed the passive baseline during the Jan-Apr 2025 downturn.

## Schema

**One unified `strategy_passports` table** with all passport fields as typed columns + three foreign-keyed child tables (`paper_refs`, `rigor_results`, `backtest_results`). Replaces both the previous file-based `Strategy` loader path and the slim JSON-blob `StrategyRecord` ORM — there is now **one passport store**, not two divergent ones.

### `strategy_passports` (the unified store)

```sql
CREATE TABLE strategy_passports (
    id                          VARCHAR(64)  PRIMARY KEY,    -- keccak256(papers[].arxiv_id sorted || methodology_hash)[:32]
    content_hash                VARCHAR(66)  NOT NULL UNIQUE, -- keccak256 over canonical passport; dedup primitive
    generation_method           VARCHAR(32)  NOT NULL,        -- 'curated' | 'fusion' | 'architect'

    -- Methodology integrity
    methodology_text            TEXT         NOT NULL,        -- canonical methodology, full text
    methodology_hash            VARCHAR(66)  NOT NULL,        -- keccak256(methodology_text); matches on-chain anchor
    extraction_llm              VARCHAR(64),                  -- e.g. 'glm-4.7'; NULL for hand-curated

    -- Regime tag (Layer 1 of bear-strategy architecture)
    regime_tag                  VARCHAR(16)  NOT NULL,        -- 'bull' | 'bear' | 'regime_neutral' — CHECK enforced

    -- Strategy definition (typed; not JSON-blob)
    strategy_name               VARCHAR(256) NOT NULL,
    thesis                      TEXT         NOT NULL,
    asset_universe              JSONB        NOT NULL,        -- list of tickers; JSONB for GIN-indexable
    risk_profile                VARCHAR(32)  NOT NULL,        -- 'conservative' | 'moderate' | 'aggressive'
    position_sizing             VARCHAR(32)  NOT NULL DEFAULT 'equal_weight',
    rebalance_frequency         VARCHAR(16)  NOT NULL DEFAULT 'weekly',
    risk_constraints            JSONB        NOT NULL DEFAULT '{}'::jsonb,

    -- Code binding (for the backtest engine)
    strategy_code_path          TEXT,                         -- e.g. 'analytics-engine/strategies/faber_sma200.py'
    strategy_code_hash          VARCHAR(66),                  -- keccak256 of the strategy file contents

    -- Curation trail
    curator_wallet              VARCHAR(64),                  -- v1: Dan's wallet
    curator_note                TEXT,
    curator_validation_at       TIMESTAMPTZ,

    -- Lifecycle
    status                      VARCHAR(16)  NOT NULL DEFAULT 'candidate',  -- 'candidate' | 'validated' | 'live' | 'retired' | 'rejected'
    passes_rigor_gate           BOOLEAN      NOT NULL DEFAULT FALSE,
    parent_id                   VARCHAR(64)  REFERENCES strategy_passports(id),  -- lineage; nullable

    -- On-chain anchor (populated by chain/strategy_publisher.py on Tier-1 promotion)
    on_chain_registration_tx    VARCHAR(128),                 -- StrategyRegistry.registerStrategy tx hash
    on_chain_registration_block BIGINT,
    paper_corpus_hash           VARCHAR(66),                  -- keccak256(papers[].arxiv_id sorted) — matches on-chain
    curator_sig                 BYTEA,                        -- signed (id, methodologyHash, paperCorpusHash, regimeTag, ts)

    -- Audit timestamps
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_regime_tag CHECK (regime_tag IN ('bull','bear','regime_neutral')),
    CONSTRAINT chk_status     CHECK (status IN ('candidate','validated','live','retired','rejected')),
    CONSTRAINT chk_method     CHECK (generation_method IN ('curated','fusion','architect'))
);

CREATE INDEX ix_strategy_passports_status     ON strategy_passports(status);
CREATE INDEX ix_strategy_passports_regime     ON strategy_passports(regime_tag);
CREATE INDEX ix_strategy_passports_generation ON strategy_passports(generation_method);
CREATE INDEX ix_strategy_passports_rigor      ON strategy_passports(passes_rigor_gate);
CREATE INDEX ix_strategy_passports_universe   ON strategy_passports USING GIN(asset_universe);
```

### `paper_refs` (multi-paper, foreign-keyed)

```sql
CREATE TABLE paper_refs (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id         VARCHAR(64)  NOT NULL REFERENCES strategy_passports(id) ON DELETE CASCADE,
    ordinal             INTEGER      NOT NULL,            -- stable display order; 0-indexed
    arxiv_id            VARCHAR(64),                      -- nullable for non-arxiv
    doi                 VARCHAR(128),                     -- nullable
    title               TEXT         NOT NULL,
    authors             TEXT[]       NOT NULL,
    venue               VARCHAR(128),
    year                INTEGER,
    citation_count      INTEGER,                          -- snapshot at curation time
    contribution        TEXT,                             -- what this paper contributed (fusion strategies)
    contribution_weight NUMERIC(4,3),                     -- nullable; populated for fusion blending
    paper_claimed_sharpe NUMERIC(8,4),                    -- per-paper claim (for blended-claim computation)
    paper_claimed_cagr   NUMERIC(8,4),
    paper_claimed_max_dd NUMERIC(8,4),

    CONSTRAINT chk_paper_identifier CHECK (arxiv_id IS NOT NULL OR doi IS NOT NULL OR title IS NOT NULL),
    UNIQUE (strategy_id, ordinal)
);

CREATE INDEX ix_paper_refs_strategy_id ON paper_refs(strategy_id);
CREATE INDEX ix_paper_refs_arxiv_id    ON paper_refs(arxiv_id) WHERE arxiv_id IS NOT NULL;
```

### `rigor_results` (Tier-1 admission gate outputs)

```sql
CREATE TABLE rigor_results (
    id                          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id                 VARCHAR(64)  NOT NULL REFERENCES strategy_passports(id) ON DELETE CASCADE,
    deflated_sharpe_ratio       NUMERIC(8,4),
    dsr_p_value                 NUMERIC(8,6),
    num_trials_in_selection     INTEGER,
    pbo_score                   NUMERIC(4,3),
    out_of_sample_sharpe        NUMERIC(8,4),
    look_ahead_audit_passed     BOOLEAN      NOT NULL DEFAULT FALSE,
    sharpe_ci_lower             NUMERIC(8,4),             -- Lo (2002) 95% CI lower bound
    sharpe_ci_upper             NUMERIC(8,4),
    kelly_fraction              NUMERIC(8,4),
    evaluator_version           VARCHAR(32),              -- e.g. 'rigor_evaluator@1.3.0'
    evaluated_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_rigor_results_strategy_id ON rigor_results(strategy_id);
```

### `backtest_results` (real backtest outputs + paper-claim deltas)

```sql
CREATE TABLE backtest_results (
    id                       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id              VARCHAR(64)  NOT NULL REFERENCES strategy_passports(id) ON DELETE CASCADE,
    backtest_engine          VARCHAR(32)  NOT NULL,    -- 'backtrader' | 'vectorbt'
    backtest_code_hash       VARCHAR(66),              -- keccak256 of the executable backtest code
    transaction_cost_bps     INTEGER      NOT NULL DEFAULT 10,
    walk_forward_split       NUMERIC(4,2) NOT NULL DEFAULT 0.70,

    -- Real outputs
    real_sharpe              NUMERIC(8,4),
    real_sortino             NUMERIC(8,4),
    real_cagr                NUMERIC(8,4),
    real_max_drawdown        NUMERIC(8,4),
    real_win_rate            NUMERIC(8,4),
    real_calmar              NUMERIC(8,4),
    real_corr_spy            NUMERIC(8,4),
    real_total_trades        INTEGER,
    n_obs_daily              INTEGER,
    backtest_start           DATE,
    backtest_end             DATE,

    -- Paper-claim delta (blended for fusion strategies; see "Multi-paper specifics" below)
    paper_claim_blended_sharpe NUMERIC(8,4),
    paper_claim_delta_sharpe   NUMERIC(8,4),

    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_backtest_results_strategy_id ON backtest_results(strategy_id);
```

### `strategy_proposals` (episodic memory — the compounding substrate)

Every fusion / architect / agent proposal — **including rigor-fails and user-rejects** — is
persisted here (T-PE.8). The strategy library is not static; every generation contributes
content-hashed, retrievable rows. Separated from `strategy_passports` because proposals
are ephemeral candidates while passports are admitted artifacts. When a proposal passes
the rigor gate and is promoted, a corresponding `strategy_passports` row is minted.

```sql
CREATE TABLE strategy_proposals (
    id                  VARCHAR(64)  PRIMARY KEY,     -- content_hash[:16]
    generation_id       VARCHAR(64)  NOT NULL,        -- groups proposals from one Generate call
    proposal_id         VARCHAR(64)  NOT NULL,        -- unique within generation
    parent_proposal_id  VARCHAR(64),                  -- lineage pointer

    -- Verdict
    verdict             VARCHAR(32)  NOT NULL DEFAULT 'pending',  -- 'pending' | 'rigor_pass' | 'rigor_fail' | 'user_rejected'
    trust_level         VARCHAR(16)  NOT NULL DEFAULT 'CANDIDATE', -- 'CANDIDATE' | 'VALIDATED' | 'RETIRED'

    -- Integrity
    content_hash        VARCHAR(66)  NOT NULL UNIQUE, -- keccak256 of canonical payload

    -- Agent provenance
    agent               VARCHAR(32)  NOT NULL DEFAULT 'unknown', -- 'fusion' | 'architect' | 'agent'

    -- Regime
    regime_tag          VARCHAR(16),                 -- nullable; populated when regime is known

    -- Full proposal payload
    payload             TEXT         NOT NULL DEFAULT '{}',

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_proposal_verdict       ON strategy_proposals(verdict);
CREATE INDEX ix_proposal_agent         ON strategy_proposals(agent);
CREATE INDEX ix_proposal_generation_id ON strategy_proposals(generation_id);
```

The `/api/strategies/proposals` endpoint exposes these for the UI's explore surface and
for the compounding-strategy narrative in the pitch.

**Notes on what this schema is NOT:**

- Not an inline column addition to a pre-existing table. The Day-2 spec assumed a `strategies` table to extend; that table never landed in the shipped shape. `strategy_passports` is the table.
- Not a slim JSON-blob (the pre-Track-E `StrategyRecord`). All passport fields are typed columns so the rigor pipeline, regime filter, and on-chain publisher can all read structured data.
- Not split between "curated" and "generated" stores. `generation_method` is a column, not a separate table — same shape, same gate, same anchor.

## Dataclass shape

The Python contract mirrors the schema. Multi-paper from the constructor.

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

@dataclass(frozen=True)
class PaperRef:
    """One paper contributing to a strategy. Single-paper strategies have one PaperRef;
    fusion strategies have N. Foreign-keyed to strategy_passports.id via the paper_refs table."""
    arxiv_id: str | None        # nullable for non-arxiv
    doi: str | None             # nullable
    title: str
    authors: list[str]
    venue: str | None = None
    year: int | None = None
    citation_count: int | None = None
    contribution: str | None = None         # what this paper contributed ("provided the inverse-vol sizing rule")
    contribution_weight: float | None = None # for fusion blending; nullable for single-paper
    paper_claimed_sharpe: float | None = None
    paper_claimed_cagr: float | None = None
    paper_claimed_max_dd: float | None = None


@dataclass
class StrategyPassport:
    """The unified, multi-paper, regime-aware, on-chain-anchorable passport.

    Replaces the scalar-paper `Strategy` dataclass. One row per strategy in
    `strategy_passports`; one row per paper in `paper_refs` (foreign-keyed).
    """
    # Identity
    id: str                                  # deterministic: keccak256(papers[].arxiv_id sorted || methodology_hash)[:32]
    content_hash: str                        # keccak256 over the canonical passport JSON; dedup primitive
    generation_method: Literal["curated", "fusion", "architect"]

    # Provenance
    papers: list[PaperRef]                   # ≥1; fusion strategies have N
    methodology_text: str                    # canonical methodology, full text
    methodology_hash: str                    # keccak256(methodology_text); matches on-chain anchor
    extraction_llm: str | None = None        # e.g. "glm-4.7"; None for hand-curated

    # Regime
    regime_tag: Literal["bull", "bear", "regime_neutral"] = "regime_neutral"

    # Strategy definition
    strategy_name: str = ""
    thesis: str = ""
    asset_universe: list[str] = field(default_factory=list)
    risk_profile: Literal["conservative", "moderate", "aggressive"] = "moderate"
    position_sizing: str = "equal_weight"
    rebalance_frequency: str = "weekly"
    risk_constraints: dict[str, float] = field(default_factory=dict)

    # Code binding
    strategy_code_path: str | None = None
    strategy_code_hash: str | None = None

    # Curation
    curator_wallet: str | None = None
    curator_note: str | None = None
    curator_validation_at: datetime | None = None

    # Lifecycle
    status: Literal["candidate", "validated", "live", "retired", "rejected"] = "candidate"
    passes_rigor_gate: bool = False
    parent_id: str | None = None

    # On-chain anchor (populated by chain/strategy_publisher.py on Tier-1 promotion)
    on_chain_registration_tx: str | None = None
    on_chain_registration_block: int | None = None
    paper_corpus_hash: str | None = None     # keccak256(papers[].arxiv_id sorted)
    curator_sig: bytes | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_tier_1(self) -> bool:
        """Tier-1 = passes rigor gate AND has on-chain anchor."""
        return self.passes_rigor_gate and self.on_chain_registration_tx is not None
```

`RigorResult` and `BacktestResult` are separate dataclasses (live in `models/rigor.py` and `models/backtest.py`) joined via `strategy_id`. They are populated independently of passport ingest.

## API surface

Endpoints that actually exist post-Track E. Removed: legacy decision-routing endpoints (those live in the reasoning-trace spec, not here); `/api/strategies/{id}/paper` (subsumed by the multi-paper passport).

```
GET    /api/strategies/{id}/passport
       → full multi-paper StrategyPassport JSON, including:
         - papers[] (the N PaperRefs)
         - methodology_text + methodology_hash
         - regime_tag
         - rigor_results (latest)
         - backtest_results (latest) with paper-claim blended delta
         - on_chain_registration_tx + on_chain_registration_block + arcscan URL

GET    /api/strategies?regime=bear
       → filterable list. Query params:
         - regime: 'bull' | 'bear' | 'regime_neutral'
         - status: 'candidate' | 'validated' | 'live' | 'retired' | 'rejected'
         - generation_method: 'curated' | 'fusion' | 'architect'
         - passes_rigor_gate: bool
       → returns lean shape (id, name, regime_tag, sharpe, status, anchor_tx); UI calls
         /passport for the detail page

GET    /api/strategies/{id}/verify
       → server-side recomputes:
         - keccak256(methodology_text) == on-chain methodologyHash?
         - keccak256(papers[].arxiv_id sorted) == on-chain paperCorpusHash?
         - regime_tag matches on-chain regimeTag?
         - curator_sig recovers to on-chain curator address?
       → returns {is_verified: bool, anchor_tx, anchor_block, arcscan_url,
                  recomputed_methodology_hash, on_chain_methodology_hash,
                  recomputed_paper_corpus_hash, on_chain_paper_corpus_hash,
                  divergence: [] | ['methodology_hash', ...]}
       → this is the endpoint that powers the "Verify on-chain" button on the
         StrategyPassport page (see "Frontend implications" below)

POST   /api/strategies/{id}/anchor       (internal — called by Tier-1 promotion only)
       → fires StrategyRegistry.registerStrategy(strategyId, methodologyHash,
         paperCorpusHash, regimeTag, curatorSig)
       → updates strategy_passports.on_chain_registration_tx + _block
       → idempotent: returns existing tx if already anchored
       → 403 if passes_rigor_gate=false (rigor gate is prerequisite)

GET    /api/traces/{trace_id}/verify     (cross-reference — see reasoning-trace spec)
       → analogous endpoint for per-decision ReasoningTraceRegistry verification.
         Mentioned here because the UI surfaces the same Verify pattern for both
         strategies and traces.

GET    /api/strategies/proposals
       → episodic memory surface (T-PE.8). Returns every generation attempt:
         fusion proposals, architect proposals, rigor-fails, user-rejects.
         Query params:
         - verdict: 'pending' | 'rigor_pass' | 'rigor_fail' | 'user_rejected'
         - agent: 'fusion' | 'architect' | 'agent'
         - regime_tag: 'bull' | 'bear' | 'regime_neutral'
         - generation_id: filter to a single generation session
       → the compounding substrate: every generation contributes retrievable rows;
         the strategy library compounds over time instead of being a static artifact.
```

## Integration with the agent's decision flow

This is how a passport gets minted, gated, anchored, and read — end to end.

1. **Strategy Generation Agent emits a passport.** Either:
   - **Fusion path** (`services/strategy_fusion.py`): user brief → KB retrieval → multi-paper LLM synthesis → emits `papers: list[PaperRef]` with N≥2 entries + `contribution_weight` per paper.
   - **Architect path** (`services/strategy_architect.py`): user brief → curated-library selection → copies passport from the selected strategy file; `papers` has 1 entry.
   - **Curated seed path** (file-based): `analytics-engine/strategies/*.py` files have `PAPER_ARXIV_IDS` (list, not scalar), `METHODOLOGY_TEXT`, `PAPER_CLAIMED_*`, `REGIME_TAG` module constants. AST-parsed at ingest.

2. **`passport_loader.py` writes to the unified store.** (Replaces the file-based `LocalStrategyProvider`.) Loader:
   - Computes `keccak256(methodology_text)` → `methodology_hash`.
   - Computes `keccak256(papers[].arxiv_id sorted joined)` → `paper_corpus_hash`.
   - Derives `regime_tag` from the regime classifier (or reads the explicit `REGIME_TAG` constant from a curated file).
   - Upserts to `strategy_passports` (content-hash dedup); inserts N rows to `paper_refs`.
   - **Also persists to `strategy_proposals`** (episodic memory) — every attempt is recorded with verdict, agent, regime_tag, and content_hash. The proposals table is the compounding substrate; passports are the promoted subset.
   - `strategy_provider.py` becomes a thin backward-compat shim that reads from the same store via the loader's queries.

3. **Rigor pipeline runs.** Backtest engine executes `strategy_code_hash` on real data → writes `backtest_results` row. `rigor_evaluator.py` computes DSR + Sharpe CI; `fusion_evaluator.py` computes PBO via CSCV; AST scan for look-ahead. All four results land in `rigor_results`. If all pass → `strategy_passports.passes_rigor_gate = true` and `status` transitions `candidate → validated`. If any fail → `status = rejected` (visible failure, NOT silent drop).

4. **Tier-1 promotion anchors on-chain.** When `passes_rigor_gate` flips false→true, `chain/strategy_publisher.py` fires:
   - Builds canonical anchor payload: `(strategyId, methodologyHash, paperCorpusHash, regimeTag, timestamp)`.
   - Curator wallet (v1: Dan) signs it.
   - Calls `StrategyRegistry.registerStrategy(...)` on Arc.
   - On tx success → writes `on_chain_registration_tx` + `_block` + `curator_sig` to `strategy_passports`.
   - Failed strategies (rigor gate fail) are NOT anchored — kept in DB as visible failures; on-chain registry stays meaningful ("if it's anchored, it passed").

5. **Live Execution Agent reads passport during cost-benefit checks.** The Portfolio Construction Agent queries `/api/strategies?regime=<current_regime>&passes_rigor_gate=true` per the regime classifier's output. The Live Execution Agent's cost-benefit sub-agent reads the full passport (paper-claim delta, OOS sharpe, regime tag) to weight rebalance decisions. Every rebalance produces a `ReasoningTrace` that references the consumed `strategy_id` — verifiable through the trace's `strategies_invoked` column.

## StrategyRegistry contract

`contracts/src/StrategyRegistry.sol` (NEW; pattern lifted from `ReasoningTraceRegistry.sol`). Interface as defined in the architecture doc:

```solidity
interface IStrategyRegistry {
    event StrategyRegistered(
        bytes32 indexed strategyId,
        bytes32 methodologyHash,
        bytes32 paperCorpusHash,
        uint8   regimeTag,        // 0=bull, 1=bear, 2=regime_neutral
        address indexed curator,
        uint256 registeredAt
    );

    function registerStrategy(
        bytes32 strategyId,
        bytes32 methodologyHash,
        bytes32 paperCorpusHash,
        uint8   regimeTag,
        bytes calldata curatorSig    // signed (strategyId, methodologyHash, paperCorpusHash, regimeTag, timestamp)
    ) external;

    function getStrategy(bytes32 strategyId) external view returns (
        bytes32 methodologyHash,
        bytes32 paperCorpusHash,
        uint8   regimeTag,
        address curator,
        uint256 registeredAt
    );

    function isRegistered(bytes32 strategyId) external view returns (bool);
}
```

**Anchoring policy:**

- **Tier-1 only.** `registerStrategy` is called only when `passes_rigor_gate` transitions false→true. Failed-rigor strategies are NEVER anchored. Gas budget on Arc testnet is ~$0.01/strategy; bounded because the gate filters before the contract call.
- **Curator-signed.** v1 = Dan's wallet signs single-handedly. v2 = curator multisig (Dan + Önder + a third). v3 = on-chain DAO vote with token-weighted approval. The contract is signature-agnostic — only the off-chain promotion policy changes.
- **Immutable once anchored.** `registerStrategy` rejects duplicate `strategyId`. To "update" a strategy you mint a new passport with a new `id` (derived from the new methodology hash) and a `parent_id` pointer to the original — lineage is on-chain via re-registration with the new ID.
- **No on-chain backtest numbers.** Sharpe / DSR / PBO are stored off-chain in `rigor_results` (volatile precision, recomputable). Only the integrity primitives (methodology + paper corpus + regime + curator) anchor on-chain.

## Multi-paper specifics

Fusion strategies are the reason the schema is multi-paper from day one. The implementation contract:

- **`papers` is always a list.** Single-paper strategies have `len(papers) == 1`; fusion strategies have `len(papers) >= 2`. The dataclass and API responses never collapse to a scalar shape. UI must render N rows.
- **Per-paper contribution.** Each `PaperRef` carries a `contribution: str` describing what that paper contributed to the fusion (e.g. "provided the inverse-realized-variance sizing rule"). For curated single-paper strategies this can be `None`; for fusion strategies it is required.
- **Contribution weights.** Each `PaperRef` carries `contribution_weight: float | None` in `[0.0, 1.0]`. For fusion strategies, weights sum to ~1.0 (validation: `0.95 <= sum(weights) <= 1.05`). For single-paper strategies, `contribution_weight = None` (implicit 1.0).
- **Paper-claim blending.** When `len(papers) > 1`, `paper_claim_blended_sharpe` (column on `backtest_results`) is computed as `Σ(paper.paper_claimed_sharpe * paper.contribution_weight)`. The `paper_claim_delta_sharpe = real_sharpe - paper_claim_blended_sharpe`. This is the honest delta — the fusion strategy isn't beating its papers; it's matching the blended expectation within noise.
- **UI rendering.** `StrategyPassport.jsx` renders a per-paper table with columns: `Paper | Claim Sharpe | Contribution to fusion | Implied weighted claim`. Plus a final row: `Fusion actual Sharpe | — | — | <real_sharpe>` with the delta surfaced as ±delta below.

## Bear-strategy architecture

Layer 1 of the three-layer architecture (full detail in [`docs/diagrams/strategy-passport-architecture.md` "Bear-strategy architecture"](../diagrams/strategy-passport-architecture.md#bear-strategy-architecture-option-d---full)) lives in this spec because `regime_tag` is a passport column.

**The enum is part of the contract:**

```sql
regime_tag VARCHAR(16) NOT NULL CHECK (regime_tag IN ('bull','bear','regime_neutral'))
```

- **`bull`** — strategy expects positive returns in risk-on regimes; underperforms in bear markets. Examples: TSMOM (Moskowitz et al. 2012), trend-following (Faber 2007), momentum factor.
- **`bear`** — strategy generates returns in risk-off regimes; underperforms in bull markets. Examples: vol-managed portfolios (Moreira-Muir 2017), defensive sector rotation, downside-beta tilts (Ang-Chen-Xing 2006), short-interest factors.
- **`regime_neutral`** — strategy is regime-agnostic by construction. Examples: long-short market-neutral, statistical arbitrage, dollar-neutral pairs.

Layer 2 (always-both generation) and Layer 3 (regime-aware portfolio weighting) live in `services/strategy_fusion.py` and the Portfolio Construction Agent respectively — both consume `regime_tag` as a passport input. The contract here is just: *every passport MUST carry a `regime_tag`; the loader rejects passports without one.*

## Content-hashing details

**`keccak256` over canonical-encoded JSON.** Web3-compatible; matches what the on-chain registry computes. The pre-Track-E spec used a non-EVM hash — that's wrong for our on-chain integration. Hash divergence between off-chain and on-chain breaks verification.

Canonical form:

- UTF-8 string.
- No trailing whitespace; `\n` line endings.
- JSON serialized with sorted keys, no extra spaces:
  `json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)`.
- Numeric precision: floats serialized with 8 decimal places fixed.
- For `paper_corpus_hash`: sort `papers` by `arxiv_id` ascending (nulls last by `title`), then `keccak256` over the joined `arxiv_id || arxiv_id || ...` string.
- For `methodology_hash`: strip leading/trailing whitespace from `methodology_text`, then `keccak256` over the UTF-8 bytes.

The canonicalization rules live in `backend/archimedes/lib/canonical.py` (or equivalent) so anyone can recompute the hashes from the stored content. **The `/api/strategies/{id}/verify` endpoint does exactly this recomputation server-side and compares against on-chain `getStrategy()`.**

## Frontend / UI implications

The passport's value is fully realized in the UI. Post-Track-E shipped components:

- **`ui/src/components/StrategyPassport.jsx`** (lands with PR #142). The full `/strategy/:id` page. Renders:
  - All N PaperRefs as a table (single-paper strategies show one row; fusion strategies show N).
  - Methodology text + methodology hash.
  - Regime tag badge.
  - Rigor result grid (DSR, PBO, OOS Sharpe, look-ahead audit).
  - Backtest result table with paper-claim delta (blended for fusion strategies).
  - **"Verify on-chain" button** — calls `GET /api/strategies/{id}/verify`, renders ✓ VERIFIED (green) with arcscan link OR ✗ MISMATCH (red) with the diverging hash highlighted. **This is the wow moment** — clicking verify on a strategy recomputes the methodology + paper corpus hashes server-side and compares to `StrategyRegistry.sol`'s on-chain entry. Verifiability becomes an interaction, not a paragraph.

- **`ui/src/components/Strategies.jsx`** (Library list). Row expansion shows summary passport fields (regime, status, anchor tx link). Faceted filters wire to `/api/strategies?regime=X&status=Y`.

- **`ui/src/components/Reasoning.jsx`** (already shipped). The trace `Verify` button already works (`verifyTrace(traceId)` at lines 89-104 hits `ReasoningTraceRegistry`). The Strategy Passport's verify button uses the same UX pattern, just pointed at `StrategyRegistry`.

**Why "verify on a strategy" is the bigger demo beat than verify-on-a-trace.** Traces are per-decision; verifying one shows "this trade was committed before execution." Strategies are the durable artifact — verifying one shows "this strategy's methodology is exactly what the registry says it is; the curator signed it; the rigor gate passed before it was anchored." The strategy verify shows *the whole rigor wedge* in one click.

## Edge cases and what NOT to do

- **DO NOT mint strategies without `regime_tag`.** The loader rejects passports with `regime_tag = NULL`. If the regime is genuinely unclear, the generation agent must explicitly tag `regime_neutral` (not omit the field). Auditable claim > silent omission.
- **DO NOT skip on-chain registration for Tier-1 promotions.** A strategy is Tier-1 iff `passes_rigor_gate = true` AND `on_chain_registration_tx IS NOT NULL`. The `is_tier_1` property enforces both. The Portfolio Construction Agent only ever consumes Tier-1 strategies for production vault deployment; Tier-2 (community, opt-in) reads candidates separately.
- **DO NOT use non-EVM hashing for `methodology_hash`.** Must be keccak256 for on-chain compatibility. The on-chain `StrategyRegistry.registerStrategy()` recomputes keccak256; if off-chain uses a different hash the verification path is broken from day one. Audit existing usages of non-keccak hashing in `strategy.py` and `strategy_provider.py` and migrate them in the Track E rollout.
- **DO NOT mint single-paper passports with `papers = []`.** The constraint is `len(papers) >= 1`. The architect/fusion paths must always produce at least one PaperRef. Curated seed strategies always have one (or more).
- **DO NOT collapse fusion strategies to a scalar paper field for UI convenience.** The `papers` list shape is the contract. The UI table is the right primitive; do not pick a "primary paper" and hide the rest.
- **DO NOT anchor failed-rigor strategies.** The on-chain registry's meaning is "this passed our gate." Anchoring failures pollutes the registry and inflates gas costs. Failed strategies stay in DB with `status='rejected'`.
- **DO NOT allow passport mutation post-anchor.** `methodology_text`, `papers`, `regime_tag` are immutable once `on_chain_registration_tx IS NOT NULL`. Status transitions (`live → retired`) are allowed; provenance fields are not. Re-extraction creates a new passport with a `parent_id` pointer.
- **Don't add aggregate ratings.** No `confidence_score` or `quality_rating` columns. Rigor primitives (DSR, PBO, OOS) are the auditable surface; an aggregate score becomes a black box.
- **Don't allow trace edits** — `reasoning_traces` shares this constraint (cross-reference); the principle generalizes: provenance artifacts are append-only.

## Estimated lift

Current Track E spec IDs from [`docs/specs/launch-execution-plan-2026-05-23.md`](launch-execution-plan-2026-05-23.md) §§ 4-Track E.

| Component                                                   | Spec ID  | Owner    | Days |
| ----------------------------------------------------------- | -------- | -------- | ---- |
| `strategy_passports` + `paper_refs` schema + Alembic migration | T-PE.1   | Daniel R.| 1.0  |
| `passport_loader.py` (replaces file-based provider; multi-paper-aware) | T-PE.2   | Daniel R.| 1.5  |
| `PaperRef` + `StrategyPassport` dataclass migration         | T-PE.3   | Daniel R.| 0.5  |
| `regime_tag` enum + always-both fusion generation           | T-PE.4   | Dan      | 1.0  |
| `StrategyRegistry.sol` contract + Foundry tests + deploy    | T-PE.5   | Chuan    | 1.0  |
| `chain/strategy_publisher.py` (Tier-1 promotion anchoring)  | T-PE.6   | Chuan    | 0.5  |
| `StrategyPassport.jsx` (multi-paper table + Verify button)  | T-PE.7   | Marten   | 1.0  |
| `strategy_proposals` table + `/api/strategies/proposals` endpoint (episodic memory) | T-PE.8 | t2o2 | 0.5  |

**Total: ~7.0 person-days, parallelizable.** T-PE.1 + T-PE.5 unblock everything else; can run concurrently. T-PE.7 needs T-PE.2 + T-PE.6 landed for the Verify button to demo end-to-end. T-PE.8 (episodic memory) is independent and can land any time.

## Acceptance criteria for the implementation contract

The contract is satisfied when all of the following are true on a cold clone deployed to the live EC2 stack:

- [ ] `strategy_passports`, `paper_refs`, `rigor_results`, `backtest_results`, `strategy_proposals` tables exist with the typed columns specified above; Alembic migration is reversible.
- [ ] Every curated strategy from `analytics-engine/strategies/*.py` is loaded into `strategy_passports` via `passport_loader.py` with `papers` populated (single-entry for the curated v1 set) and `regime_tag` populated.
- [ ] At least one fusion strategy exists in `strategy_passports` with `len(papers) >= 2`, each PaperRef carrying a non-null `contribution` and `contribution_weight`.
- [ ] `methodology_hash` and `paper_corpus_hash` are computed with `keccak256` (not legacy non-EVM hashing) for every passport; canonicalization rules live in `lib/canonical.py`.
- [ ] `StrategyRegistry.sol` is deployed to Arc testnet (deployment address recorded in `contracts/deployments.json`); ABI cached in `contracts/abis/`.
- [ ] At least one Tier-1 strategy has been anchored on-chain via `chain/strategy_publisher.py`; `on_chain_registration_tx` populated; tx visible on arcscan.
- [ ] `GET /api/strategies/{id}/passport` returns the full multi-paper passport including rigor + backtest + anchor fields.
- [ ] `GET /api/strategies?regime=bear` returns only bear-tagged strategies; `?regime=bull` returns only bull-tagged.
- [ ] `GET /api/strategies/{id}/verify` recomputes both hashes server-side, compares against `StrategyRegistry.getStrategy()`, and returns `{is_verified: true, divergence: []}` for an anchored Tier-1 strategy; returns `{is_verified: false, divergence: [...]}` if any field is mutated post-anchor (negative test).
- [ ] `StrategyPassport.jsx` renders the multi-paper table for a fusion strategy with N rows + a blended-claim summary row; the Verify button renders ✓ VERIFIED with an arcscan link for an anchored strategy.
- [ ] `Reasoning.jsx`'s existing trace Verify (lines 89-104) continues to work — the strategy-passport verify is additive, not a replacement.
- [ ] Promotion policy is honored: no passport with `passes_rigor_gate = false` has `on_chain_registration_tx IS NOT NULL`.
- [ ] Loader rejects passports without `regime_tag` (regression test asserts `IntegrityError` on insert).
- [ ] `strategy_proposals` table persists every generation attempt (rigor-pass, rigor-fail, user-reject) with content_hash + agent + regime_tag; `/api/strategies/proposals` exposes the episodic memory surface.

---

*Spec lives next to its reference doc: [`docs/diagrams/strategy-passport-architecture.md`](../diagrams/strategy-passport-architecture.md). When the two diverge, this spec is the contract for what gets implemented; the architecture doc is the explanation of why the contract is shaped this way. Reconcile both on the same revision date.*
