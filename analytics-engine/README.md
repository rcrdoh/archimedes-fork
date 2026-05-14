# Archimedes Analytics Engine

Analytics engine for Archimedes MVP — backtesting + strategy-passport metrics.
Wraps backtrader; produces engine-agnostic `BacktestResult` payloads per
`docs/specs/strategy-passport-spec.md`.

## Operations (v1)

- `SPY`
- `NIKKEI`
- `GOLD`
- `TREASURY`
- `OIL`

## Quickstart

```bash
cd analytics-engine
uv sync
uv run archimedes-analytics-engine run --operations SPY NIKKEI GOLD TREASURY OIL
```

Artifacts land in `analytics-engine/artifacts/`.
