# Judging-Rubric Self-Assessment — Day 3 Snapshot

> **Date:** 2026-05-13 (Day 3, late evening Chicago)
> **Audience:** Archimedes hackathon team
> **Purpose:** Honest assessment of where we stand against the four rubric categories with
> ~11 days to go. Identifies the biggest gaps and a concrete forcing function for closing
> them. Re-score weekly.
> **Source:** Rubric weights and category definitions per
> [`agora_project_analysis.md`](agora_project_analysis.md) § 1.

## The rubric

| Weight | Category                | Reads from                                                  |
| ------ | ----------------------- | ----------------------------------------------------------- |
| 30%    | Agentic Sophistication  | How much the AI actually decides vs. just automates         |
| 30%    | Traction                | Real users, real transactions, real volume *during the event window* (arc-canteen telemetry is the scoreboard) |
| 20%    | Circle Tool Usage       | Creative use of Wallets, CCTP, Gateway, App Kit, Contracts, USYC, USDC |
| 20%    | Innovation              | Novel approaches, emergent behavior, research insight       |

## TL;DR — rough running score: ~13 / 40 ≈ 33%

| Weight | Category               | Score / 10 | Trend     | Risk    |
| ------ | ---------------------- | ---------- | --------- | ------- |
| 30%    | Agentic Sophistication | **4**      | Improving | Medium  |
| 30%    | Traction               | **0**      | Flat      | **High — easily fixable** |
| 20%    | Circle Tool Usage      | **2**      | Improving | **High — gating dependency on Chuan/Marten testnet deploy** |
| 20%    | Innovation             | **7**      | Improving | Low     |

Innovation is the strongest. Traction is a fixable structural zero. Circle Tool Usage
requires the testnet deploy to happen. Agentic Sophistication is "promising specs, no
live agent" — converts when the orchestrator runs end-to-end.

---

## 30% Agentic Sophistication — current: 4 / 10

**What the rubric values:** the agent making non-trivial decisions autonomously after
deployment, not just at design time. Reasoning visible, regime-adaptive, strategy
rotation in response to drift / market state.

**What we have:**

- ✅ Architecture for an autonomous portfolio agent with five frozen interfaces
  (`IAgentOrchestrator`, `IRegimeDetector`, `IPortfolioConstructor`, `IStrategyProvider`,
  `IBacktestEvaluator`) per [`specs/component-interfaces-spec.md`](specs/component-interfaces-spec.md)
- ✅ Reasoning trace model (`models/trace.py`) with canonical-JSON SHA-256 hashing and
  on-chain anchor slots
- ✅ Day-3 commit-reveal trace integrity spec — promotes "trace existed at T" to
  "trace existed *before* the trade" with proven causal ordering
  ([`specs/commit-reveal-trace-spec.md`](specs/commit-reveal-trace-spec.md))
- ✅ Selection-bias gate that prevents the agent from acting on curve-fit artifacts
  ([`specs/selection-bias-corrections-spec.md`](specs/selection-bias-corrections-spec.md))
- ✅ Strategy provider (`backend/archimedes/services/strategy_provider.py`) implemented
  and loading 4 strategies (3 paper-grounded + 1 baseline) with risk-profile routing

**What's missing:**

- ❌ No live orchestrator loop running yet (Chuan's queue)
- ❌ No `regime_detector` / `portfolio_constructor` / `backtest_evaluator` implementations
  (Önder's queue)
- ❌ No `oracle_updater` / `chain_executor` / `trace_publisher` implementations (Marten's
  queue)
- ❌ Zero reasoning traces have been generated, hashed, or anchored
- ❌ Zero agent decisions on testnet

**To get to 7 / 10:** ship the orchestrator with one Tier-1 vault running a regime-aware
strategy, generating at least one reasoning trace that anchors to Arc. Live demo of an
autonomous rebalance triggered by a regime classification change.

**To get to 9 / 10:** ship the commit-reveal trace pattern in production. Live demo
shows the user clicking "Verify temporal binding" and seeing
`commitBlock < tradeBlock < revealBlock`.

---

## 30% Traction — current: 0 / 10

**What the rubric values:** real users, real transactions, real volume during the event
window. The Canteen team explicitly noted this weight is unusual; per
[`agora_project_analysis.md`](agora_project_analysis.md) § 1 the framing is "great
founders ship and get users in two weeks."

**The scoreboard:** `arc-canteen` telemetry. Specifically the `update-traction` and
`update-product` events that each teammate logs. **`arc-canteen status` is what the
judges see.**

**What we have:** **zero.** No traction updates logged. No product updates logged. The
rubric scoreboard reads zero across the team.

**What's missing:**

- Every team member running `arc-canteen update-product` at minimum once per meaningful
  ship (this PR, the smart-contract merges, the EC2 deployment, the analytics-engine
  release — none of these are in arc-canteen's log)
- Every team member running `arc-canteen update-traction` whenever they talk to a
  potential user, share a screenshot in Discord, get a meaningful conversation on Twitter,
  etc.
- A testnet-deployed product to drive users *to* (gates Circle Tool Usage as well)
- Outbound outreach: Canteen Discord, Arc Builder Discord, crypto Twitter, r/algotrading,
  QuantConnect forums (per the design.md § 9 channels)

**Backfill TODO (do tonight or first thing Day 4):**

```bash
# One per meaningful ship — backfill these:
arc-canteen update-product "Day 1-2: project setup, design docs, MVP scope memo"
arc-canteen update-product "Day 3: EC2 + Docker + CI/CD live; analytics-engine module shipped; passport-aware models; 3 paper-grounded strategies seeded"
arc-canteen update-product "Day 3: rigor-as-wedge — DSR + PBO + walk-forward selection-bias spec; commit-reveal trace integrity spec; doc corpus reconciled around ecosystem-design pivot"
# … one per future merge
```

**To get to 5 / 10:** consistent daily `update-product` cadence + 5 logged `update-traction`
events (judges, fellow hackers, Discord conversations).

**To get to 8 / 10:** 30+ portfolios created on testnet by Day 14, with each one
logged via `update-traction`. Per design.md § 9 targets.

**Risk:** **highest of the four categories.** A team that ships brilliantly and forgets
to log loses ~half of the 30% rubric weight for nothing. **Make this a daily ritual.**

---

## 20% Circle Tool Usage — current: 2 / 10

**What the rubric values:** depth and creativity across Wallets, CCTP, Gateway,
App Kit, Contracts, USYC, USDC, Paymaster.

**What we have:**

- ✅ Contracts written: `PriceOracle.sol`, `SyntheticToken.sol`, `SyntheticVault.sol`,
  plus 8 interface stubs
- ✅ Ecosystem design references the full Circle toolset
- ✅ USDC as exclusive settlement currency — no native-token gas to learn
- ✅ EC2 infrastructure live, ready to deploy

**What's missing:**

- ❌ No contracts deployed to Arc testnet. Zero on-chain footprint as a team.
- ❌ No CCTP usage (cross-chain USDC movement)
- ❌ No Gateway integration (unified balance / nanopayments)
- ❌ No Paymaster integration (USDC-denominated gas)
- ❌ No USYC integration (the risk-off anchor)
- ❌ No App Kit usage
- ❌ No Circle Wallets onboarding flow

**Reference material we have at hand:**

- `submodules/context-arc/circlefin-skills/use-smart-contract-platform.md` for deploy
- `submodules/context-arc/circlefin-skills/bridge-stablecoin.md` for CCTP + Gateway
- `submodules/context-arc/circlefin-skills/use-gateway.md` for unified balance
- `submodules/context-arc/samples/arc-escrow/` — closest existing vault pattern
- `submodules/context-arc/samples/arc-multichain-wallet/` — CCTP integration
- `submodules/context-arc/samples/arc-p2p-payments/` — Paymaster + USDC

**To get to 5 / 10:** contracts deployed to Arc testnet (PriceOracle + SyntheticFactory
+ Vault). PaymasterImpl integrated so all transactions are USDC-paid. USYC live as
risk-off anchor with at least one Tier-1 vault holding it.

**To get to 7 / 10:** add CCTP or Gateway for a meaningful cross-chain action. Circle
Wallets integrated for user onboarding (no MetaMask popup — direct USDC deposit flow).

**To get to 9 / 10:** add the Agent Stack (Circle CLI + Agent Wallets per
`developers.circle.com/agent-stack.md`) so the orchestrator runs as a first-class
on-chain agent with its own wallet identity, settling reasoning-trace publishes through
its own paymaster account.

---

## 20% Innovation — current: 7 / 10 ⭐

**What the rubric values:** novel approaches, emergent behavior, research insight.
**Our strongest category.**

**What we have that no other AI-portfolio submission will have:**

- ✅ **Strategy passport** ([`specs/strategy-passport-spec.md`](specs/strategy-passport-spec.md))
  — every strategy carries paper-arxiv-id, methodology hash, curator signature,
  on-chain registration tx. Other AI portfolios make "trust me" claims; ours is bound
  to peer-reviewed research with a verifiable hash chain.
- ✅ **Selection-bias corrections** ([`specs/selection-bias-corrections-spec.md`](specs/selection-bias-corrections-spec.md))
  — DSR (Bailey & López de Prado 2014) + PBO (Bailey/Borwein/López de Prado/Zhu 2014) +
  walk-forward OOS + look-ahead static audit. No other AI portfolio submission applies
  the textbook multiple-testing corrections that quant academics have demanded for a
  decade.
- ✅ **Paper-claim deltas surfaced** — `sharpe_vs_paper`, `cagr_vs_paper`, McLean-Pontiff
  (2016) post-publication-decay estimate. We tell the user where the strategy was
  expected to live (paper) vs. where it actually lives (our re-run). Hidden by every
  competitor; surfaced by us as a feature.
- ✅ **Commit-reveal trace integrity** ([`specs/commit-reveal-trace-spec.md`](specs/commit-reveal-trace-spec.md))
  — commit-before-trade / reveal-after-trade binds the agent to a single reasoning
  trace before the outcome is knowable. Closes the "generate 100 traces, pick the one
  that rationalizes the outcome" attack ([`agora_project_analysis.md`](agora_project_analysis.md)
  § 5.2). Spec'd for v1.5.
- ✅ **Two-tier architectural primitive coverage** — Tier 1 = paper-grounded +
  selection-bias-corrected + full agent; Tier 2 = freestyle + reasoning traces only.
  The badge means something concrete, not aspirational.
- ✅ **Tool-call provenance** — every market-data fetch and oracle read recorded with
  input + output hashes. Lets us *replay* agent behavior with different prompts to study
  decision sensitivity. Nobody else is doing this.
- ✅ **Honest pitch framing** — anti-features.md § "pitch-rigor anti-claims" explicitly
  rules out the "blockchain as memory", "predicted alpha", "trace proves causation",
  and "regulatory clarity" claims that competitors will reach for. We claim
  auditability + rigor; we don't claim returns.

**What's missing:**

- ⚠️ All of the above are *spec'd*. The full demo evidence (judges actually clicking
  "Verify trace hash" and seeing the green checkmark; live DSR + PBO numbers on a
  strategy detail page; the paper-claim delta line item visible) doesn't exist yet.
- ⚠️ Arxiv ingest pipeline is not built (KnowledgeBase has the patterns; we haven't
  ported them yet).

**To get to 9 / 10:** ship the "Verify trace hash" UI element. Have a strategy detail
page that shows the DSR p-value, PBO score, paper-claim delta, and a green checkmark
on the trace integrity check. Each of those is a screenshot-worthy demo moment.

**To get to 10 / 10:** add a demo segment where Dan extracts a strategy from a fresh
arxiv paper live on stage — the KnowledgeBase `extract.py` → Claude API → new strategy
file in `analytics-engine/strategies/` → backtest gate → reasoning trace anchored
on-chain in under 5 minutes. "We can turn a paper into an audited strategy on stage,
right now."

---

## Cross-category forcing function: the smallest possible end-to-end demo

The single highest-leverage thing we can build in the next 11 days is a **vertical slice
that touches all four rubric categories at once.** Per
[`agora_project_analysis.md`](agora_project_analysis.md) § 8, recent hackathon winners
shipped narrow products; none tried to be platforms.

**The minimal viable demo:**

1. **One Tier-1 vault** holding one strategy (TSMOM is the best candidate — simplest
   to backtest convincingly and pairs naturally with the regime detector).
2. **Real Arc testnet deployment** of `PriceOracle`, `SyntheticVault`,
   `ReasoningTraceRegistry`, with USDC and USYC live.
3. **User wallet flow** via Circle Wallets — judge connects, deposits 10 USDC, sees a
   portfolio constructed.
4. **One autonomous rebalance** triggered by a regime classification change (we control
   the regime trigger for demo timing).
5. **One published reasoning trace** with a working "Verify trace hash" UI button.
6. **Strategy detail page** showing the DSR p-value, PBO score, paper-claim delta, and
   the green look-ahead-audit checkmark.

That single end-to-end loop checks every rubric category:

| Category               | What the demo shows                                                  |
| ---------------------- | -------------------------------------------------------------------- |
| Agentic Sophistication | Autonomous rebalance + reasoning trace + regime classification       |
| Traction               | Real on-chain transaction by a real user; log via `update-traction`  |
| Circle Tool Usage      | USDC settlement + Paymaster + Wallets + Contracts + USYC (5 of 7)    |
| Innovation             | Strategy passport + selection-bias gate + paper-claim delta visible  |

**Everything else in the ecosystem spec — Tier 2 community vaults, AMM-traded vault
tokens, per-vault chat — is decoration on this loop.** They can be in the pitch as
"what's next"; they don't need to be in the live demo to score well.

## Recommendation for the team

1. **Tonight (Dan, alone):** start the traction-logging habit. Backfill `update-product`
   for everything that's already shipped.
2. **Day 4 morning (Chuan):** deploy contracts to Arc testnet. First on-chain
   transactions belong to us by lunchtime.
3. **Day 4-5 (Marten):** oracle updater service + chain executor + trace publisher
   skeleton. Get the agent → testnet pipe working.
4. **Day 5-7 (Önder):** portfolio constructor + backtest evaluator with the DSR/PBO
   math from the selection-bias spec. The math is the rigor pitch.
5. **Day 7-9 (Chuan + Dan):** stitch the orchestrator together; first end-to-end
   autonomous rebalance with reasoning trace.
6. **Day 9-12 (Daniel R.):** frontend Next.js app or live data on the ui-mockups —
   reasoning-trace viewer + Verify-trace button are the demo wow.
7. **Day 9-14 (Dan + everyone):** active outreach — Canteen Discord, Arc Builder
   Discord, crypto Twitter. Log every conversation.

Re-score this doc weekly. The traction line in particular should not stay at zero past
Day 4.

## Open questions

1. **Do we explicitly cut Tier 2 from the v1 demo?** Per
   [`mvp-scope-memo.md`](mvp-scope-memo.md) § "What gets cut if Day 3 ambition outruns
   the timeline," Tier 2 is the second-to-cut. With ~11 days remaining and zero on-chain
   activity, this looks like the time. Surface as "v2 — community can author vaults"
   in the deck.
2. **Same question for AMM-traded vault tokens.** Cut last per the memo, but the
   premium/discount-to-NAV story is at odds with the verifiable-history pitch and adds
   contract surface. Recommend cut from v1 demo; keep in roadmap.
3. **Same question for per-vault chat.** Cut for demo; the chat is engagement layer
   not core trust.

Recommendation: cut all three from the demo MVP, keep them in the roadmap segment of
the deck. **The wedge is one Tier-1 vault that proves the rigor stack works end-to-end.**
