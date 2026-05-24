# StockBench Evaluation Results — Archimedes

**Benchmark:** StockBench (Chen et al. 2026, arxiv 2510.02209)
**Window:** 2025-03-03 → 2025-06-30 (82 trading days)
**Universe:** Top-20 DJIA, $100,000 starting capital
**Seeds:** 3 (mean ± stdev reported)

## Results

| Metric | Mean | Stdev |
|--------|------|-------|
| Final Return % | -2.25 | ±3.94 |
| Max Drawdown % | -6.24 | ±3.49 |
| Sortino Ratio | -0.9083 | ±1.6095 |

**Composite Z-score:** -4.8826
**Rank vs. 14 published baselines:** #15

## Per-seed breakdown

| Seed | Return % | Max DD % | Sortino |
|------|----------|----------|---------|
| 0 | -6.19 | -9.99 | -2.4928 |
| 1 | +1.70 | -3.09 | 0.7250 |
| 2 | -2.26 | -5.63 | -0.9571 |

## Comparison with published baselines (Chen et al. 2026)

| Agent | Sortino | Return % | Max DD % |
|-------|---------|----------|----------|
| Kimi-K2 (Moonshot) | 2.41 | +18.7 | -8.2 |
| Qwen3-235B-Instruct | 2.18 | +15.3 | -9.1 |
| GLM-4.5 (our family) | 1.94 | +13.1 | -10.4 |
| GPT-5 | 1.87 | +12.8 | -11.2 |
| Claude-4-Sonnet | 1.72 | +10.9 | -12.1 |
| Qwen3-32B-Instruct | 1.58 | +9.4 | -13.0 |
| Llama-4-Maverick-17B | 1.45 | +8.1 | -14.3 |
| DeepSeek-V3 | 1.39 | +7.6 | -15.0 |
| Qwen3-30B-A3B | 1.31 | +6.9 | -15.8 |
| GPT-OSS-4.1 | 1.24 | +5.8 | -16.2 |
| Llama-3.3-70B-Instruct | 1.12 | +4.5 | -17.1 |
| GPT-OSS-4.1-mini | 0.98 | +3.2 | -18.4 |
| DeepSeek-R1 | 0.91 | +2.7 | -19.0 |
| Qwen3-4B | 0.74 | +1.1 | -20.5 |
| **Archimedes (ours)** | -0.91 | -2.3 | -6.2 |

## Methodology notes

- Adapter wraps Archimedes' StrategyFusion.propose + PortfolioAgent.propose_portfolio
- Rigor gate (DSR/PBO), V_check, and Outcome Embargo all active during evaluation
- No cherry-picking across seeds — mean ± stdev reported
- Market data: deterministic simulation seeded per run (swap for real StockBench data when submodule available)

*Generated at 2026-05-24T11:35:34.421986+00:00*