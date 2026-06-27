# Architecture Decision Records

> **Status:** Day-10 (2026-05-22; updated 2026-06-26). Two ADRs currently. The ADR pattern is:
> capture a non-trivial technical decision once, with the alternatives considered
> and the reasoning, so future contributors can understand the choice without
> needing to relitigate it.

## Index

| ADR | Decision |
|---|---|
| [`backtrader-vs-vectorbt-decision-memo.md`](backtrader-vs-vectorbt-decision-memo.md) | Why we picked **backtrader** over **vectorbt** for the v1 backtest engine |
| [`chainlink-primary-oracle.md`](chainlink-primary-oracle.md) | Why on-chain prices are **Chainlink-primary** with a thin, bounded admin fallback that **degrades (not reverts)** on feed outage (#724) |

## When to add an ADR

- A library/framework choice with a real alternative
- A protocol / interface contract that downstream code will depend on
- A trade-off that future readers will look back at and ask "why did they do it that way?"

## When NOT to add an ADR

- Routine implementation choices (variable names, function shape)
- Decisions captured implicitly in shipped code + tests
- Things best captured in inline comments or commit messages
