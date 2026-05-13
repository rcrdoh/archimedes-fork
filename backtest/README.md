# Archimedes Backtest

Backtesting sandbox for Archimedes MVP.

## Operations (v1)

- `SPY`
- `NIKKEI`
- `GOLD`
- `TREASURY`
- `OIL`

## Quickstart

```bash
cd backtest
uv sync
uv run archimedes-backtest run --operations SPY NIKKEI GOLD TREASURY OIL
```

Artifacts land in `backtest/artifacts/`.
