# Quant Audit Report: Archimedes
**Perspective:** Senior Quant, Systematic Strategies
**Scope:** All quantitative finance code — math, statistics, backtesting, portfolio construction, risk
**Date:** 2026-06-07

---

## Summary Table

| Severity | Finding | File | Impact |
|---|---|---|---|
| **CRITICAL** | Sharpe computed without risk-free rate | engine.py, backtester, rigor_evaluator | All Sharpe overstated ~0.25–0.38 |
| **CRITICAL** | `in_sample_sharpe` uses full series, not IS slice | rigor_evaluator.py:774 | OOS/IS gate ratio wrong |
| **CRITICAL** | OOS > IS for all strategies — gate provides no filtering | backtest_fixtures.json | Rigor gate has no discriminatory power |
| **CRITICAL** | Negative OOS Sharpe can pass gate when IS is None | rigor_evaluator.py:664 | Gate has hard bypass path |
| **CRITICAL** | `num_trials=1` default — no multiple-testing correction | rigor_evaluator.py:720 | DSR is just a dressed-up Sharpe |
| **CRITICAL** | `look_ahead_passed=True` hardcoded for all generated strategies | portfolio_backtester.py:401 | AST audit bypassed for all LLM output |
| **CRITICAL** | Moreira-Muir vol includes current bar (look-ahead) | moreira_muir.py:96 | One-bar forward contamination |
| **CRITICAL** | Faber rebalances daily via integer rounding, not on signal change | faber.py:97 | ~200× excess turnover |
| **HIGH** | All strategies on SPY: degenerate covariance matrix | backtest_fixtures.json | MVO/Kelly portfolio undefined |
| **HIGH** | TSMOM uses 12-0 momentum, not 12-1 | tsmom.py:99 | Short-term reversal noise in signal |
| **HIGH** | Kelly fraction meaninglessly clipped at 1.0 | rigor_evaluator.py:477 | Metric has no discriminatory value |
| **HIGH** | PBO on N=4–5 strategies is statistically unreliable | rigor_evaluator.py:221 | PBO score uninterpretable |
| **HIGH** | Dead GMM midpoint computation | statistical_regime.py:301 | GMM is decorative |
| **HIGH** | GMM label switching not handled | statistical_regime.py:396 | Calm/stressed can invert |
| **HIGH** | `usyc_yield` used as cross_asset_correlation proxy | statistical_regime.py:134 | Regime signal incoherent |
| **HIGH** | Simulation cost mixes pre/post-return equity basis | portfolio_backtester.py:217 | Systematic cost understatement |
| **MEDIUM** | Sortino uses two different formulas in two files | engine.py vs backtester.py | Inconsistent metric |
| **MEDIUM** | DSR correlation adjustment not from Bailey-LdP paper | rigor_evaluator.py:141 | Undocumented heuristic |
| **MEDIUM** | Faber documented as monthly, runs as daily | faber.py:51 | Metadata wrong |
| **MEDIUM** | Stress engine overstates rigor | stress_engine.py:13 | 1-factor beta model misrepresented |
| **MEDIUM** | Capacity decay runs 5 redundant full simulations | portfolio_backtester.py:379 | Unnecessary 5× compute |
| **MEDIUM** | Lookahead audit is `coc`/`coo` check, not signal-contamination check | engine.py:120 | Insufficient audit scope |
| **MEDIUM** | OOS minimum floor is 5 bars | rigor_evaluator.py:263 | Statistically degenerate OOS accepted |
| **MEDIUM** | CPCV path assembly has no assertion on path count | rigor_evaluator.py:398 | Silent path-count mismatch |
| **LOW** | Faber correlation_to_spy=1.0 in fixture but strategy goes to cash | backtest_fixtures.json | Incorrect fixture value |
| **LOW** | George-Hwang stub win_rate disagrees with fixture value | george_hwang.py:81 | UI may show wrong number |
| **LOW** | RISK_ON regime multiplier 0.5 can push conservative below their floor | kelly_portfolio.py:41 | Risk profile violated in bull market |
| **LOW** | Purged k-fold discards label-end max | purged_kfold.py:111 | Weak purge for long-horizon labels |

---

## CRITICAL — Wrong Math, Wrong Results

### 1. Sharpe Ratio Computed Without Risk-Free Rate — Everywhere

**Files:** `analytics-engine/src/archimedes_analytics_engine/engine.py:153`, `backend/archimedes/services/portfolio_backtester.py:260`, `backend/archimedes/services/rigor_evaluator.py:86`

```python
# engine.py — riskfreerate=0.0 hardcoded in a 5% rate environment
cerebro.addanalyzer(bt.analyzers.SharpeRatio, riskfreerate=0.0, ...)

# portfolio_backtester.py — bare mean, no rf subtraction
sharpe = (mu / sigma) * np.sqrt(ANNUALIZATION) if sigma > 0 else 0.0

# rigor_evaluator.py — same
SR_hat = float(arr.mean()) / sigma
```

At 5% Fed funds and ~13% vol (SPY), this overstates Sharpe by ~0.38 units (5% / 13%). Every Sharpe number reported in `backtest_fixtures.json` is wrong by this amount. The DSR, the gate thresholds, and the OOS/IS ratios are all computed on inflated Sharpe values.

The Kelly optimizer in `portfolio_optimizer.py` **does** subtract rf correctly — but the Sharpe numbers being audited do not. You cannot pass a rigor gate using a metric computed differently from how you compute it at runtime.

---

### 2. `in_sample_sharpe` Uses Full-Sample Returns, Not IS Slice

**File:** `backend/archimedes/services/rigor_evaluator.py:774`

```python
# in run_rigor_gate() — called when in_sample_sharpe not provided
if in_sample_sharpe is None and len(daily_returns) >= 2:
    arr = np.asarray(daily_returns, dtype=float)
    sigma = float(arr.std(ddof=1))
    if sigma > 0:
        in_sample_sharpe = (float(arr.mean()) / sigma) * math.sqrt(_ANNUALIZATION)
```

`compute_oos_sharpe()` at line 261 splits at `split = int(T * train_fraction)`. The OOS Sharpe is computed on `arr[split:]`. But the IS Sharpe reference is computed on the **entire** series `arr[0:T]`, not `arr[0:split]`. The OOS/IS ratio check in `passes_all` therefore compares OOS to a blended IS+OOS estimate, understating the ratio and making the criterion trivially easy to pass.

---

### 3. OOS Sharpe Exceeds IS Sharpe for Every Strategy — Gate Provides Zero Filtering

**File:** `analytics-engine/strategies/backtest_fixtures.json`

```
faber:        IS=0.634, OOS=0.930  (OOS/IS = 1.47)
moreira_muir: IS=0.769, OOS=0.969  (OOS/IS = 1.26)
tsmom:        IS=0.650, OOS=0.762  (OOS/IS = 1.17)
buy_hold:     IS=0.537, OOS=0.792  (OOS/IS = 1.47)
```

Every single strategy shows OOS > IS. With a 70/30 split on 2004–2026 data, the OOS window is approximately 2019–2026: COVID V-shaped recovery, the 2020–2021 bull run, and the 2022 rate-shock trend. This period is systematically favorable to trend-following strategies because trends were strong and sharp. The OOS gate criterion (`OOS ≥ 50% × IS`) is trivially met when OOS happens to be exceptional. This is precisely the scenario the rigor gate is supposed to detect and block — but it doesn't.

**You need multiple non-overlapping OOS windows, not one chronological tail.**

---

### 4. Negative OOS Sharpe Strategies Can Pass the Rigor Gate

**File:** `backend/archimedes/services/rigor_evaluator.py:664`

```python
@property
def passes_all(self) -> bool:
    ...
    if self.oos_sharpe is None:
        return False
    if self.in_sample_sharpe and self.in_sample_sharpe > 0 and self.oos_sharpe / self.in_sample_sharpe < 0.5:
        return False
    ...
    return self.look_ahead_passed
```

If `in_sample_sharpe` is `None` (which happens when `in_sample_sharpe` is not provided and the fallback fails), the entire OOS Sharpe quality check is **skipped**. A strategy with `oos_sharpe = -2.0` passes this gate as long as `in_sample_sharpe` is None. There is no absolute floor on OOS Sharpe.

---

### 5. `num_trials=1` Default Disables Multiple-Testing Correction

**File:** `backend/archimedes/services/rigor_evaluator.py:720`

```python
def run_rigor_gate(
    strategy_id: str,
    daily_returns: list[float],
    num_trials: int = 1,  # ← default: no correction applied
    ...
```

With `num_trials=1`, `E_max_N = 0.0` and `SR_zero = 0.0`. The DSR collapses to the raw annualized Sharpe with a non-normality adjustment. DSR's entire purpose is to penalize for the number of strategies tested before selecting this one. If every caller omits `num_trials` (and there's no enforcement mechanism to pass the library size), the multiple-testing correction never fires. The `backtest_fixtures.json` shows `num_trials_in_selection` ranging from 2 to 6 — but even N=6 barely moves the needle compared to the true exploration space if LLM generation tried dozens of candidate strategies.

---

### 6. `look_ahead_audit_passed = True` Hardcoded for All LLM-Generated Strategies

**File:** `backend/archimedes/services/portfolio_backtester.py:401`

```python
# Static rebalance with t-1 prices generating t returns is structurally
# lookahead-free — no signal computation at all. We mark this true for the gate.
look_ahead_passed = True
```

This hardcodes a pass for ALL portfolios run through the portfolio backtester, regardless of how the weights were generated. If the LLM generates weights with embedded look-ahead logic (e.g., "allocate more to assets that outperformed this quarter"), the weight matrix itself encodes future information. The static rebalancer is not look-ahead free — the *allocation decisions* may be. There is no audit of the agent's weight-generation logic, and the AST-based check is never invoked for any generated strategy.

---

### 7. Moreira-Muir Volatility Estimate Includes Current Bar

**File:** `analytics-engine/strategies/moreira_muir_2017_volatility_managed.py:96`

```python
def _realized_vol_annual(self) -> float | None:
    for i in range(window):
        prev = float(self.data.close[-i - 1])
        curr = float(self.data.close[-i])      # i=0: close[0] = current bar
```

When `i=0`: `curr = close[0]` (today's close), `prev = close[-1]` (yesterday). Today's return is included in the volatility estimate used to set today's position size. The paper uses σ²_{t-1} — realized variance computed entirely from past data. This is one-bar look-ahead: the sizing decision uses information from the return being earned that bar.

The paper also computes volatility from monthly returns (one value per month), not daily returns evaluated every bar. The Archimedes adaptation rebalances daily, changing the strategy's risk profile substantially from the paper.

---

### 8. FaberSMA200 Rebalances Every Day Due to Integer Truncation

**File:** `analytics-engine/strategies/faber_2007_sma200_timing.py:97`

```python
target_size = int(account_value * float(self.params.exposure_fraction) // price)
if target_size > 0 and self.position.size != target_size:
    self.order_target_size(target=target_size)
```

As the account value changes daily, `target_size = int(account_value × 0.99 // price)` changes every bar. `self.position.size` will never exactly equal `target_size` after account growth because the fractional shares change daily. This triggers a trade on nearly every bar when the strategy is invested — not just on signal changes. Faber's paper rebalances monthly. This implementation generates approximately 200× more trades annually and incurs proportionally more transaction costs. The 10 bps transaction cost in the fixture is therefore being applied far more frequently than intended.

---

## HIGH — Conceptually Wrong or Misleading

### 9. All Three Main Strategies Run on SPY: Degenerate Covariance Matrix

**File:** `analytics-engine/strategies/backtest_fixtures.json`

```
faber:        correlation_to_spy = 1.0
moreira_muir: correlation_to_spy = 1.0
tsmom:        correlation_to_spy = 1.0
```

All strategies are single-asset on SPY. The portfolio optimizer receives three "assets" (sFaber, sMoreira, sTSMOM) that are all 100% correlated. The 3×3 correlation matrix is a matrix of all 1s — singular, uninvertible, with infinite condition number. Ledoit-Wolf shrinkage (`ledoit_wolf_shrinkage`) cannot rescue a matrix that is identically rank-1. The MVO and Kelly weights are numerically undefined; the optimizer is selecting among identical positions and any weight vector produces the same portfolio. The `diversification_ratio` output is 1.0 (no diversification) — this is the correct answer, but the UI presumably does not surface this as a warning.

---

### 10. TSMOM Uses 12-0 Lookback Instead of 12-1

**File:** `analytics-engine/strategies/moskowitz_ooi_pedersen_2012_tsmom.py:99`

```python
past_close = float(self.data.close[-lookback])  # close[-252] = 252 bars ago
trailing_return = (float(self.data.close[0]) / past_close) - 1.0
```

Moskowitz, Ooi, Pedersen (2012) use the trailing 12-month return *excluding the most recent month* to avoid contamination from short-term reversal (the Jegadeesh-Titman effect). The standard implementation is 12-1 months. The code uses 12-0 months (current close vs. 252 bars ago), which embeds the one-month reversal noise. This affects signal quality — particularly around reversals at momentum extremes. The methodology documentation does not acknowledge this divergence from the paper.

---

### 11. Kelly Fraction Is Meaninglessly Clipped at 1.0

**File:** `backend/archimedes/services/rigor_evaluator.py:477`

```python
return round(float(np.clip(f_fractional, 0.0, 1.0)), 6)
```

The continuous-time Kelly formula `f* = (μ - rf) / σ²` for a strategy with Sharpe=0.65, vol=13% produces:
- μ_excess = 0.65 × 0.13 = 8.45%
- σ² = 1.69%
- f* = 8.45% / 1.69% = 5.0 (500% Kelly)
- Half-Kelly = 2.5 → clipped to 1.0

The fixture shows `kelly_fraction: 0.839` for Faber and `kelly_fraction: 1.0` for Moreira-Muir. The 1.0 value is a clipping artifact, not a signal. Displaying this as a meaningful metric to users implies precision that doesn't exist — the actual Kelly for every strategy in the library is "bet 300%+ of your wealth," which the clip suppresses. The metric has no discriminatory power between strategies.

---

### 12. PBO With N=4–5 Strategies Is Statistically Meaningless

**File:** `backend/archimedes/services/rigor_evaluator.py:221`

With N=4 strategies, the OOS rank of the IS-best strategy can only take values {1, 2, 3, 4}. The normalized rank ω = rank/N ∈ {0.25, 0.50, 0.75, 1.00}. λ = log(ω/(1-ω)) ≤ 0 only for ω ≤ 0.50 (ranks 1–2). PBO counts the fraction of C(16,8) = 12,870 splits where the IS-best lands in rank 1 or 2 — a very coarse discrete distribution, not the smooth empirical CDF the paper assumes. Bailey et al. (2014) develop PBO for grids of parameter variants (e.g., 50+ parameterizations of one model), not a handful of fundamentally different strategies. Using it across Faber, Moreira-Muir, TSMOM, and Buy-and-Hold conflates conceptually orthogonal designs. The PBO score in the fixture (0.373–0.390) is not interpretable as a selection-bias measure.

---

### 13. Dead Computation in StatisticalRegimeDetector

**File:** `backend/archimedes/services/statistical_regime.py:301`

```python
def _composite_to_regime(self, composite: float, vix: float) -> Regime:
    # The midpoint between the two GMM components is the natural boundary
    (self._gmm_calmed_mu + self._gmm_stressed_mu) / 2.0   # ← computed, never assigned

    vix_normalized = (vix - self._gmm_calmed_mu) / (self._gmm_stressed_mu - self._gmm_calmed_mu)
```

The "adaptive GMM threshold" is computed and immediately discarded. The actual thresholds used are hardcoded boundaries (0.30, 0.50, 0.75), making the GMM decorative. The comment and the code are inconsistent. The GMM parameters update via EM but never feed into the regime call thresholds.

---

### 14. GMM Label Switching — Calm and Stressed Can Swap

**File:** `backend/archimedes/services/statistical_regime.py:396`

```python
mu1 = float((r1 * vix_arr).sum() / n1)
mu2 = float((r2 * vix_arr).sum() / n2)
```

After EM iterations, there is no guarantee that `mu1 < mu2` (calm < stressed). If the VIX data has tight overlap between components, the components can swap identities across EM runs. There is no sorting step. After a swap, the "calm" component describes the stressed regime and vice versa, inverting the regime classification. The 0.3 damping factor makes this unlikely in practice but it is a latent correctness bug.

**Fix:**
```python
if mu1 > mu2:
    mu1, mu2 = mu2, mu1
    sigma1, sigma2 = sigma2, sigma1
    w1 = 1.0 - w1
```

---

### 15. `usyc_yield` Used as `cross_asset_correlation` Proxy

**File:** `backend/archimedes/services/statistical_regime.py:134`

```python
cross_asset_correlation=snapshot.usyc_yield,  # Proxy for risk appetite
```

USYC yield is the yield of a money-market-adjacent stablecoin, essentially tracking the overnight rate. Cross-asset correlation (the equity-bond correlation, or average pairwise correlation across asset classes) is a completely different measure with different scale, units, sign, and interpretation. USYC yield barely moves; cross-asset correlation spikes to 1.0 in a liquidity crisis. This proxy is incorrect and feeds garbage into the `RegimeSignals` dataclass.

---

### 16. Simulation Cost Accounting Mixes Pre/Post-Return Equity

**File:** `backend/archimedes/services/portfolio_backtester.py:217`

```python
q_j = delta_w * post_r_t_equity          # uses TODAY's equity (after return)
...
cost_fraction = total_cost_dollars / equity  # divides by YESTERDAY's equity
r_t -= cost_fraction
post_r_t_equity = max(0.0, equity * (1.0 + r_t))
```

`q_j` (turnover in dollars) is computed using `post_r_t_equity` (equity after today's return), but `cost_fraction` divides by `equity` (equity at the start of the day, before today's return). The cost basis is inconsistent across the same calculation. If today's return is +2%, this understates the cost fraction by 2%. Small individually but systematic across all rebalance bars.

---

## MEDIUM — Design Defects, Inconsistencies

### 17. Sortino Ratio Uses Different Formulas in Two Places

**`analytics-engine/src/archimedes_analytics_engine/engine.py:86`:**

```python
dd_std = math.sqrt(sum(r * r for r in downside) / len(downside))  # RMS of negative returns
```

**`backend/archimedes/services/portfolio_backtester.py:263`:**

```python
down_sigma = float(downside.std(ddof=1))  # std of negative returns, ddof=1
```

These produce different values. `std(ddof=1)` subtracts the mean of negative returns before squaring; RMS does not. For a strategy with mean negative return of -1%, the two formulas diverge materially. More importantly, neither definition subtracts the risk-free rate from the numerator. The Sortino reported in the strategy passport is inconsistent depending on which backtester ran the strategy.

---

### 18. Correlation Adjustment in DSR Is Not From Bailey-LdP (2014)

**File:** `backend/archimedes/services/rigor_evaluator.py:141`

```python
if average_correlation > 0.0:
    E_max_N *= math.sqrt(max(0.0, 1.0 - average_correlation))
```

Bailey & López de Prado (2014) do not multiply `E[max_N]` by `sqrt(1-ρ)`. Their correlation adjustment enters through the variance of the Sharpe estimator (equation 10), not through E[max_N] directly. The correct adjustment modifies the effective number of independent trials `M_eff = N / (1 + (N-1)ρ)` and recomputes `E[max_{M_eff}]`. The current formula is an undocumented heuristic that is directionally correct but not derived from the paper.

---

### 19. Faber Strategy Documented as Monthly, Runs as Daily

**File:** `analytics-engine/strategies/faber_2007_sma200_timing.py:51`

```python
REBALANCE_FREQUENCY = "daily"  # Implementation evaluates signal on every bar; Faber's original uses monthly closes.
```

The metadata `REBALANCE_FREQUENCY = "daily"` is used by downstream systems for display and selection logic, but the original paper is a monthly-signal strategy. Any logic consuming `REBALANCE_FREQUENCY` to characterize this strategy will misrepresent it. Combined with finding #8, the strategy is running daily rebalancing when the paper's signal fires monthly. These are two separate issues — the metadata error and the execution error compound each other.

---

### 20. Stress Engine Claims to Reflect Real-Shop Practice — It Does Not

**File:** `backend/archimedes/services/stress_engine.py:13`

```python
# This is the standard risk-management view at any real shop.
```

Real shops use factor models: DV01 and convexity for fixed income, sector/style betas for equity, delta/gamma for optionality. A 1-factor beta-1 model that buckets assets by broad class with flat percentage shocks is not the standard view at any real shop. TLT (duration ~18) and SHY (duration ~2) both receive their respective class shock applied identically per unit of weight, ignoring that TLT is 9× more sensitive to parallel rate shifts. The comment misrepresents the rigor of the tool.

---

### 21. Capacity Decay Runs 5 Full Redundant Simulations

**File:** `backend/archimedes/services/portfolio_backtester.py:379`

```python
for aum_tier in [1_000_000.0, 10_000_000.0, 100_000_000.0, 1_000_000_000.0, 10_000_000_000.0]:
    tier_rets, tier_eq = _simulate_portfolio(...)
```

Each call to `backtest_portfolio()` runs 6 full simulations (1 main + 5 capacity tiers), each re-executing the entire simulation loop over every bar. The price data, volatility estimates, and ADV are identical across all tiers. The only thing that changes per tier is `initial_cash`. For a static-weight portfolio, the turnover fractions (δw) are AUM-independent, so the impact cost at any AUM tier can be derived analytically from the main run's turnover profile. The 5 redundant full reruns are unnecessary.

---

### 22. Lookahead Audit Is `coc`/`coo` Check, Not Signal-Contamination Check

**File:** `analytics-engine/src/archimedes_analytics_engine/engine.py:120`

```python
def _lookahead_audit_passed(cerebro: bt.Cerebro) -> bool:
    coc = getattr(cerebro.broker.p, "coc", False)
    coo = getattr(cerebro.broker.p, "coo", False)
    return not coc and not coo
```

`coc` = cheat-on-close, `coo` = cheat-on-open. Not having these flags enabled is necessary but not sufficient for lookahead-free backtesting. Strategies that use `close[0]` in signal computation (such as FaberSMA200, whose SMA includes today's close) can still exhibit look-ahead behavior independent of `coc`/`coo`. The audit flag is green for Faber while the SMA computation includes the current bar's price in the decision.

---

### 23. OOS Minimum Floor Is 5 Bars

**File:** `backend/archimedes/services/rigor_evaluator.py:263`

```python
if len(oos) < 5:
    return None
```

5 bars = 1 trading week as the minimum OOS period. A Sharpe ratio computed on 5 days has a standard error of approximately:

```
SE(SR) ≈ sqrt((1 + 0.5 × SR²) × 252 / 5) ≈ 7 (for SR = 1)
```

The 95% CI for a Sharpe of 0.9 on 5 daily observations spans roughly (-20, +22). This OOS Sharpe would pass the gate trivially while being statistically meaningless. The minimum floor should be at least 252 bars (one trading year).

---

### 24. CPCV Path Assembly Has No Assertion on Path Count

**File:** `backend/archimedes/services/rigor_evaluator.py:398`

```python
for i in range(n_groups):
    splits_with_i = [s_idx for s_idx, combo in enumerate(splits) if i in combo]
    paths[:, bounds[i]] = arr[np.ix_(splits_with_i, bounds[i])]
```

The number of rows in `splits_with_i` must equal `n_paths = C(n_groups-1, test_groups-1)`. If `cv_splits` is provided with a non-standard ordering, `len(splits_with_i)` may vary per block, and `np.ix_` will broadcast incorrectly rather than raising an error — producing a silently wrong path matrix.

**Missing:**
```python
assert len(splits_with_i) == n_paths, f"block {i}: expected {n_paths} splits, got {len(splits_with_i)}"
```

---

## LOW — Minor Issues

### 25. Faber `correlation_to_spy = 1.0` in Fixture Is Wrong

**File:** `analytics-engine/strategies/backtest_fixtures.json:14`

A strategy that exits to cash when SPY is below its 200-day SMA cannot have correlation_to_spy = 1.0 over the full backtest period. When the strategy is in cash, its daily return is 0% while SPY may move ±2%. The empirical correlation should be around 0.6–0.8 for a strategy that is invested roughly 70% of the time. The backtest code computes this incorrectly or the fixture is stale.

---

### 26. George-Hwang Stub Win Rate Disagrees With Fixture

**File:** `analytics-engine/strategies/george_hwang_2004_52w_high.py:81`

```python
BACKTEST_WIN_RATE = 0.54  # stub
```

The `backtest_fixtures.json` shows `win_rate: 0.278` for this strategy. These disagree by a factor of ~2. Whichever value the UI surfaces will be wrong for half the time.

---

### 27. RISK_ON Regime Multiplier 0.5 Can Violate Conservative Risk Profile

**File:** `backend/archimedes/services/_deprecated/kelly_portfolio.py:41`

```python
_REGIME_DELEVERAGE_FACTORS: dict[Regime, float] = {
    Regime.RISK_ON: 0.5,  # Use only 50% of profile's base floor in risk_on
    ...
}
```

If a conservative investor has `usyc_floor = 0.40` and the regime is RISK_ON, the USDC floor drops to `0.40 × 0.5 = 0.20`. A conservative investor is now 80% in risky assets. A conservative investor being pushed to maximum risk exposure in a bull market is the opposite of what the risk profile label implies and would be immediately flagged by any compliance function.

---

### 28. Purged K-Fold Discards Label-End Maximum

**File:** `analytics-engine/src/archimedes_analytics_engine/purged_kfold.py:111`

```python
# The *latest* label-end time within the test window — anything
# before this in train still has its label observed inside test.
t1.iloc[test_positions].max()   # ← computed, result never assigned
```

The maximum label-end time within the test window is computed on line 111 and immediately discarded. The purge criterion on lines 123–126 uses `train_t1.values >= test_start_ts` but not the max label-end. For long-horizon labels (multi-month forward returns), training observations whose labels START before the test window but END inside it will not be correctly purged, creating information leakage. For short-horizon labels (1–5 day forward returns) this is negligible.

---

## Closing Assessment

The DSR and PBO machinery is structurally sound in concept, and the look-ahead AST audit is a good idea. The Ledoit-Wolf shrinkage implementation is correct. The Almgren-Chriss impact model is directionally reasonable.

However, the execution has enough gaps that the "Tier-1 Archimedes Verified" badge currently means: *this strategy has a positive Sharpe ratio on SPY over 2004–2026, where the OOS window happened to be favorable to trend-following.* That is not the same thing as selection-bias-corrected alpha.

The three fixes that would most improve the gate's integrity, in order of impact:

1. **Subtract the risk-free rate from all Sharpe computations.** Use a consistent rf across the backtest engine, DSR, OOS check, and Kelly sizing.
2. **Compute in-sample Sharpe from the IS slice only** (first 70% of bars), and add an absolute floor on OOS Sharpe (e.g., OOS > 0).
3. **Expand the strategy universe** beyond SPY-only single-asset implementations before running MVO or Kelly. A portfolio optimizer on identical assets is undefined.
