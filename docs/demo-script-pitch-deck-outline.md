# Demo Script & Pitch Deck Outline

> **Audience:** Archimedes hackathon team (deck owner + demo runner + Q&A primaries)
> **Status:** Day-4 revision (2026-05-14) — tighten in Week 2 as the orchestrator loop
> and reasoning-trace anchoring come online.
> **Pitch length assumption:** 3-minute pitch + ~2 minute live demo + Q&A. Adjust if
> Canteen tells us otherwise.
> **Shipped reality the demo can lean on (as of Day 4):**
> - Live deploy at [`http://18.171.230.205/`](http://18.171.230.205/)
> - 10 Solidity contracts on Arc testnet (chain ID `5042002`): `AMMPool`, `AMMRouter`,
>   `AssetRegistry`, `PriceOracle`, `ReasoningTraceRegistry`, `SyntheticFactory`,
>   `SyntheticToken`, `SyntheticVault`, `Vault`, `VaultFactory`
> - React 19 + Vite + viem UI with three-way wallet connect (MetaMask / Coinbase / generic
>   browser wallet) and an add-liquidity / trade tab
> - Oracle service pushing prices via Circle Wallets API on a docker-compose schedule
> - Backend strategy provider serving 4 strategies (3 paper-grounded + buy-and-hold) with
>   passport metadata exposed via the API
> - Selection-bias spec (DSR / PBO / OOS / look-ahead) and commit-reveal trace spec
>   landed; implementations are on Önder's and Chuan's queues respectively

## The headline message

> **"Markets aggregate knowledge. Archimedes lets AI agents do it for you — built on
> peer-reviewed quant research, settled on Arc, with every decision verifiable on-chain."**

That's the one-line. Everything else in the deck supports it.

## The Agora narrative

Agora (the hackathon) chose its name carefully. [From the official description](https://luma.com/7i50p2r9):

> *"In classical Athens, the agora was the heart of the city — where citizens traded
> grain and oil, money-changers leaned on their tables, oracles were consulted, and news
> was made by the speaking of it. The original information-processing machine. Markets
> are still doing the same job today; they are the social technology by which a
> civilization aggregates knowledge and decides what things are worth. AI agents are the
> new citizens."*

**Archimedes is named after another Athenian-era figure** — the Syracusan mathematician
and engineer (~287–212 BCE). The name choice is deliberate: Archimedes is the patron
saint of *empirical reasoning from first principles*. He calculated π by exhaustion. He
designed war machines. He shouted "Eureka!" when discovering the displacement principle
in his bath. He famously said "Give me a lever long enough and a fulcrum on which to
place it, and I shall move the world."

**Our framing for the pitch:**

> The agora is where citizens reasoned out loud. Archimedes was a citizen who reasoned
> with rigor — empirically, from first principles, with proofs. **Archimedes the product
> is an AI citizen who participates in the modern agora with the same rigor: every
> portfolio decision is grounded in peer-reviewed research, every reasoning step is
> auditable, every trade settles on Arc with sub-second finality. The lever is academic
> research; the fulcrum is autonomous AI; the world is your portfolio.**

This frame is **specific, defensible, and earned** — it's not "we picked a cool Greek
name." It's "we built a product whose architecture matches the original empiricist."

## The "wow moment" the demo must hit

A user, in front of judges, lives the full Archimedes flow on the live testnet deploy
at [`http://18.171.230.205/`](http://18.171.230.205/). The demo is anchored to what's
actually clickable on Day 4, with the items still on the orchestrator/regime-detector/
reasoning-trace queue marked **🚧 Week 2** so we can be honest about what's live vs.
what's narrated.

1. Lands on the Archimedes site. Sees the marketing page with the Archimedes hero.
2. Clicks **"Connect Wallet."** Sees the three-way wallet selector (MetaMask / Coinbase
   Wallet / generic browser wallet). Connects to Arc testnet (chain ID `5042002`).
3. **Picks a risk profile.** Four cards: Conservative / Moderate / Aggressive /
   Hyper-Risky. Each card shows the target vol band, max drawdown, USYC floor, and a
   one-line description. 🚧 Week 2 — currently a planned screen; the data shape is
   defined in [`docs/design.md`](design.md) § Risk Profiles.
4. **Sees a constructed portfolio.** Donut chart of weights. Underneath: the strategies
   selected (with paper citations), the backtest performance for each, the regime
   classification at construction time. 🚧 Week 2 (portfolio constructor is on Önder's
   queue per [`specs/component-interfaces-spec.md`](specs/component-interfaces-spec.md)).
5. **Clicks on a strategy card** — e.g., *"Time Series Momentum — Moskowitz, Ooi,
   Pedersen 2012, J. Fin. Econ. 104(2)."* Sees the paper title, arxiv link, methodology
   summary, our re-validated Sharpe vs. the paper's claimed Sharpe, equity curve. The
   strategy provider already serves this metadata today via the backend API; the
   strategy-detail screen is Week 2 UI work.
6. **Clicks "Deposit USDC."** Approves the transaction. USDC flows into the live
   `Vault` contract on Arc (deployed Day 4, real testnet tx, real Arc explorer link).
7. **Watches the agent build the portfolio live.** Progress UI shows: regime check ✓ →
   strategy selection ✓ → weight optimization ✓ → on-chain transfers via `AMMRouter` ✓ →
   portfolio live. Each step has a "View on Arc" link. 🚧 Week 2 — the orchestrator
   loop is the headline Week-2 deliverable.
8. **The portfolio dashboard appears.** Live positions sourced from the deployed `Vault`
   contract. Live performance vs. benchmark.
9. **Clicks the Decisions tab.** Sees the agent's construction decision with full
   reasoning trace. **Clicks "Verify trace hash."** Browser recomputes the hash in JS;
   green checkmark appears showing it matches the on-chain anchor in the deployed
   `ReasoningTraceRegistry` contract. 🚧 Week 2 — the contract is live; the
   reasoning-trace generator + anchoring writer is the wiring still to ship.
10. **(Optional advanced demo)** Fast-forward in the demo environment to trigger a
    regime change. Watch the agent autonomously rebalance. New reasoning trace appears;
    new on-chain anchor in `ReasoningTraceRegistry`; the portfolio shifts toward
    defensive strategies + USYC. 🚧 Week 2 (regime detector + portfolio constructor).

**Steps 5 (paper citation), 9 (verify trace hash), and 10 (autonomous rebalance) are the
three differentiators.** Without them, the demo is a robo-advisor on Arc. With them, the
demo is Archimedes. Three of the ten contracts on Arc are load-bearing for these three
moments: `ReasoningTraceRegistry` (step 9), `Vault` + `AMMRouter` (steps 6–10).

### What we can confidently demo today (Day 4 fallback)

If Week 2 falls behind, the Day-4-and-honest version of the demo still tells a strong
story:

- Wallet connect on Arc testnet (live).
- Deposit USDC into the deployed `Vault` (live — real on-chain tx, real Arc explorer link).
- AMM swap against the deployed `AMMPool` (live).
- Synthetic-asset mint via `SyntheticFactory` + `SyntheticVault` (live).
- Backend API call returning the 4 seeded strategies with passport metadata
  (`paper_grounded=True`, paper citation, risk profiles) — live, demonstrable in the
  Swagger UI at `/docs`.
- The selection-bias spec ([`specs/selection-bias-corrections-spec.md`](specs/selection-bias-corrections-spec.md))
  and commit-reveal trace spec ([`specs/commit-reveal-trace-spec.md`](specs/commit-reveal-trace-spec.md))
  as the *intellectual differentiators* — these are what set Archimedes apart from the 96
  other AI-portfolio submissions at the last Arc HackMoney even before the full live loop
  ships.

## Pitch deck — 9-slide structure

### Slide 1: Title + tagline

**Title:** Archimedes

**Tagline:** *Peer-reviewed AI portfolios, settled on Arc.*

**Subtitle:** *The original empiricist meets autonomous on-chain finance.*

**Visual:** Logo + the Agora/Archimedes mythology image (see `claude-design-prompts.md`
for logo prompts). Hackathon + Canteen + Circle + Arc attribution.

### Slide 2: The problem (30 seconds)

Three categories of portfolio products today:

- **TradFi robo-advisors** (Wealthfront, Betterment) — rule-based, no on-chain, opaque
  about *why* they pick what they pick.
- **DeFi yield aggregators** (Yearn, Yield Seeker) — chase current yields, no academic
  rigor, narrow to stablecoin yield.
- **AI-flavored crypto agents** (Virtuals, SingularityDAO, Theoriq) — token-mediated,
  speculation-shaped, reasoning is opaque.

**Nobody is grounding portfolio decisions in peer-reviewed quant research, with
verifiable on-chain reasoning, settled in pure USDC.**

Visual: three-column comparison with an empty fourth column where Archimedes goes.

### Slide 3: What we built (60 seconds — the meat)

Archimedes — an autonomous portfolio agent where:

- **Strategies come from peer-reviewed quant papers.** Every strategy carries a
  paper-grounded passport (paper ID, citation, methodology hash, paper-claim vs.
  re-implemented metrics with deltas surfaced honestly). Day 4: 3 paper-grounded
  strategies seeded (Faber 2007, Moreira & Muir 2017, Moskowitz Ooi Pedersen 2012)
  plus a buy-and-hold baseline, served live by the strategy provider.
- **Selection-bias gate at admission.** Every Tier-1 strategy passes Deflated Sharpe,
  Probability of Backtest Overfitting, walk-forward OOS, and a look-ahead audit. The
  spec is published; implementation is on Önder's queue.
- **The agent operates autonomously** post-deployment — regime detection, rebalancing,
  strategy rotation. Every decision produces a reasoning trace.
- **Every reasoning trace is hashed on Arc** via the deployed `ReasoningTraceRegistry`
  contract. Users can audit any decision the agent has ever made — with the v1.5
  commit-reveal upgrade in spec, "trace existed at T" strengthens to "trace existed
  *before* the trade."
- **10 contracts already on Arc testnet** (chain ID `5042002`): Vault / VaultFactory,
  AMM / Router, Synthetic Factory / Token / Vault, Asset + Price + Trace registries.
  Live UI with multi-wallet connect at `18.171.230.205`.

Visual: simplified version of [`architecture-diagram.html`](architecture-diagram.html)
with the four key components highlighted (Strategy Engine + Passport, Selection-Bias
Gate, Autonomous Portfolio Agent, ReasoningTraceRegistry on Arc).

### Slide 4: Live demo (90 seconds)

Just "**DEMO**" in large text, with `archimedes.hackagora.com` or `18.171.230.205`
underneath. Run the wow-moment script above. The demo URL should be locked in Week 2;
the EC2 IP works as the fallback.

### Slide 5: Competitive landscape (30 seconds)

The competitive slide from [`competitor-landscape.md`](competitor-landscape.md):

```
TODAY'S PORTFOLIO PRODUCTS                         ARCHIMEDES' WEDGE
─────────────────────────────                      ────────────────────
Wealthfront — TradFi robo, rule-based, no on-chain  Multi-asset RWA on Arc, settled in USDC.
Yield Seeker — USDC yield, no academic provenance   Strategies sourced from peer-reviewed papers.
DynaSets — shared on-chain vaults, native token     Per-user risk-profiled portfolios.
Theoriq — DeFi attestations, THQ token              Pure USDC. Verifiable. Consumer UX.
Olas Pearl — staking, operator-shaped               Hire-shaped: deposit USDC, get a portfolio.
Virtuals — buy the agent's token                    Hire the agent. Audit every decision.
Numerai — crowdsourced ML, opaque                   Paper-grounded, methodology in plain sight.

→ Rule-based, opaque, or token-mediated               → AI-driven, paper-provenanced, USDC-native
```

Calling out Circle directly: *"Circle gave agents wallets and nanopayments. We give users
a place to invest those nanopayments wisely."*

### Slide 6: Why we'll score well

RFB + judging-criteria coverage. From [`rfb-alignment.md`](rfb-alignment.md):

| Criterion                    | Weight | How we score                                                      |
| ---------------------------- | ------ | ----------------------------------------------------------------- |
| Agentic Sophistication       | 30%    | Regime detection, autonomous rebalancing, strategy rotation, on-chain reasoning traces. Five frozen interfaces, three queues converging on the live loop. |
| Traction                     | 30%    | Pre-curated strategies → day-1 portfolios. arc-canteen telemetry firing on every product ship + user conversation. Live testnet from Day 4. |
| Circle Tool Usage            | 20%    | Wallets (Circle-managed oracle signer, live), USDC settlement, USYC risk-off floor, CCTP for RWA bridging, Gateway for nanopayments, 10 contracts on Arc. |
| Innovation                   | 20%    | Paper-grounded passport with paper-claim deltas. On-chain reasoning traces with commit-reveal temporal binding. Selection-bias gate (DSR + PBO + OOS + look-ahead) at admission. |

See [`judging-rubric-assessment.md`](judging-rubric-assessment.md) for the running
self-score and the gap analysis driving the Week-2 critical path.

RFB 04 primary; RFB 02 math primitive (Kelly); RFB 06 adjacent (strategy leaderboard).

### Slide 7: Why now (30 seconds)

Three signals that say "this market is real, today":

- **[Circle launched Agent Stack May 11, 2026](https://decrypt.co/367490/circle-ai-agents-usdc-stablecoin-powers-222m-arc-token-sale)** — $222M Arc presale, BlackRock among
  investors. The agent economy thesis is funded.
- **[Olas Pearl is doing 700K transactions/month, 30% MoM growth](https://www.theblock.co/post/338713/olas-raises-13-8-million-to-launch-pearl-an-app-store-for-autonomous-ai-agents-in-crypto)** — the demand for autonomous on-chain agents is real.
- **[Virtuals Protocol has 18K+ agents, $470M+ Agentic GDP](https://coinmarketcap.com/cmc-ai/virtual-protocol/latest-updates/)** —
  the supply side of the agent economy is real.

But: nobody is building **paper-grounded, verifiably-auditable portfolio agents**. That's
the gap Archimedes fills.

### Slide 8: What we ship next (30 seconds)

Post-hackathon roadmap:

- **Productize the arxiv ingest pipeline** — every quant researcher can submit a paper,
  the platform extracts/validates/lists.
- **EURC + multi-currency support** for European users.
- **Strategy marketplace** — third-party researchers earn yield when their strategies
  are selected by user portfolios.
- **DAO-governed curation** — community votes on strategy inclusion.
- **v2 verticals:** prediction-market portfolio construction (RFB 03 adjacent),
  perp-aware portfolios (RFB 01 adjacent).

Visual: vertical "now / 30 days / 90 days / 180 days" roadmap.

### Slide 9: Team + ask (30 seconds)

Team photos (5 people) + one-line credentials. Use the credentials precisely:

- **Dan Browne** — PhD biochemistry, Senior Scientist at LanzaTech. (Domain rigor for
  paper curation.)
- **Marten Windler** — Systems Engineering, U. Bremen. (Off-chain ↔ on-chain integration.)
- **Daniel Reis dos Santos** — Backend engineer, distributed systems. (Frontend
  ownership.)
- **Chuan Bai** — CTO @ Gyld Finance; built CoinShares' next-gen trading platform;
  RWA tokenization expertise. (Architecture + on-chain.)
- **Önder Akkaya** — ASA Statistical Insight World Champion; President of TİD-Genç;
  trainee actuary. (Portfolio math + Kelly Criterion.)

Ask:

> "We're not asking for funding today. We're asking for: (a) feedback on the strategy
> passport schema as a candidate open standard; (b) introductions to quant researchers
> who'd want to contribute strategies; (c) partnerships with RWA-token issuers we should
> include in v2."

The "asking for nothing transactional" ask is often the strongest.

## Q&A preparation — anticipated judge questions

**Q: How is this different from Wealthfront / Betterment?**

A: They're rule-based with no on-chain settlement, no AI in the actual sense, and no
verifiable per-decision reasoning. Archimedes is AI-driven (regime detection, strategy
selection, rebalance reasoning are all LLM-mediated decisions), on-chain native, and
makes every decision auditable. We also support multi-asset RWA + USYC, not just
equity/bond ETFs.

**Q: How is this different from Yield Seeker / DynaSets?**

A: Yield Seeker chases current DeFi yields — different category. DynaSets are shared
vaults with native-token economics — different ownership model. Archimedes is a
per-user, risk-profiled portfolio agent with paper-grounded strategies and pure-USDC
settlement.

**Q: Won't the AI hallucinate strategies?**

A: That's exactly why the v1 library is hand-curated by Dan. The arxiv ingest pipeline
runs as a demo of the future workflow, not as the source of live strategies. Every
strategy in v1's library has a paper citation, a methodology hash, and a human-validated
backtest. Hallucination is a v2 conversation when the pipeline graduates from demo to
product.

**Q: What if the paper's claimed Sharpe doesn't hold out-of-sample?**

A: We capture both. The strategy passport records the paper's claimed Sharpe AND our
re-implementation's Sharpe at conservative transaction costs. If the delta is large, the
strategy is either rejected or surfaced with a warning. We're explicit that **past
performance is not predictive** — the reputation primitive is *auditable history*, not
*predicted performance*.

**Q: How does the agent know when to rebalance?**

A: Four triggers per [Chuan's design](design.md): drift threshold (any position > 5%
from target), regime change (the regime classifier transitions), strategy decay (rolling
30-day Sharpe < 0.5), or calendar (weekly check). Every trigger evaluates expected
benefit vs. transaction cost before executing. The trigger logic lives in the
`IRegimeDetector` + `IAgentOrchestrator` interfaces in
[`specs/component-interfaces-spec.md`](specs/component-interfaces-spec.md); the
implementations land in Week 2.

**Q: What about taxes?**

A: v1.5 conversation. Tax-loss harvesting is acknowledged in the design doc but not on
the demo critical path. v2 ships full tax-loss-harvesting + cost-basis tracking.

**Q: Why USDC, not your own token?**

A: Per [anti-features](anti-features.md), no native token. Revenue model is take-rate on
USDC settlement + share of USYC yield. We're optimizing for users who want a job done,
not for tokenholders. No native token also means no token-launch risk surface.

**Q: How big is the addressable market?**

A: TradFi robo-advisors collectively manage ~$1T+; DeFi TVL is ~$200B; Olas alone is
doing 700K transactions/month. We don't need to forecast precisely to know the cross-
section of "wants AI portfolio management" + "comfortable with on-chain" is material and
growing.

**Q: What's the regulatory profile?**

A: Non-custodial, permissionless, no KYC in v1 — same regulatory category as a
non-custodial DeFi protocol. We hold no user funds; the smart contracts hold the user's
own assets with the agent having only rebalance authority. No fiat on-ramp = no money
transmission. Decentralized + non-custodial is the right v1 posture.

**Q: How do you handle a bad strategy?**

A: Multiple layers. (1) Curation gate at strategy listing — Dan vets methodology + we
re-run the backtest. (2) Live monitoring — strategy decay detection triggers rotation
out. (3) Regime awareness — Crisis regime auto-deleverages to USYC floor. The Önder
math module enforces Kelly-bounded position sizing so no single strategy can blow up the
portfolio.

**Q: What's your moat against Circle building this themselves?**

A: Circle is structurally neutral infrastructure. Curation requires opinions. We bet
they won't ship strong paper-grounded curation themselves because it conflicts with their
permissionless ethos. If they do, the moat is execution speed + community trust + the
academic-researcher network we plan to build for v2.

## Logistics for demo day

- **Run the demo on a dedicated testnet wallet** with pre-funded USDC. No real-value
  assets connected.
- **Have a backup video recording** of the demo flow as insurance. Don't lean on it.
- **Test the live demo at the same time of day** as the actual judging — network
  conditions matter for sub-second-finality claims.
- **Rehearse the Q&A out loud** with the team, ideally twice in Week 2.

## Owner: who drives this?

- **Pitch deck owner:** Dan (Product Owner background; owns slide content; integrates
  team input). Marten reviews for coherence + flow.
- **Demo runner:** Daniel (he owns the frontend; he knows the system intimately and the
  visual flow). Plays the user role in the live demo.
- **Q&A primaries (rotate by topic):**
  - **Dan** — architecture, vision, strategy curation, the academic-rigor framing.
  - **Chuan** — custody, on-chain, Arc, Circle SDK, RWA-context framing.
  - **Önder** — portfolio math, Kelly, risk pricing, regime detection thresholds.
  - **Daniel** — live system, frontend, UX.
  - **Marten** — off-chain ↔ on-chain integration questions, infrastructure.

Lock these roles by end of Week 1.

## Open questions

- Should the demo include the arxiv ingest pipeline segment, or save it for the "what we
  ship next" slide? **Recommendation:** save for the slide. Live demo should be tight on
  the curated path.
- Should we name specific RWA tokens (tokenized TSLA, NVDA, GLD) in the demo, or use
  symbolic placeholders? **Day-4 reality:** the deployed `SyntheticFactory` mints synthetic
  versions today (e.g. sOIL, sNKY visible in the deploy script defaults). **Recommendation:**
  demo with the actually-minted synthetics; mention real RWA bridging via CCTP as the
  v1.5 step.
- Do we want a written one-pager for the judges to take with them? **Recommendation:** yes,
  if Canteen accepts handouts. One-page version of this deck.
- Does Week 2 prioritize the **orchestrator loop** (closing Agentic Sophistication gap)
  or **arc-canteen telemetry density** (closing Traction zero)? Both are required to
  break ~13/40; the rubric assessment argues telemetry is the cheapest +points and should
  be parallelized from Day 4 forward regardless of which engineering work lands next.
