# Strategy Library Reference

> **Status:** Living reference. Written 2026-06-12.
> **Author:** Önder Akkaya (quant / math lane).
> **Audience:** Anyone browsing the library who wants to know what each strategy
> captures, what regime it suits, and — honestly — how the v1 implementation
> diverges from the source paper.
> **Source of truth:** the strategy files under
> [`../../analytics-engine/strategies/`](../../analytics-engine/strategies/). The
> paper / author / regime fields below are transcribed from each file's
> `PAPER_*` and `REGIME_TAG` constants. Where a file's header documents a v1
> adaptation caveat, that caveat is reproduced here. For strategies whose full
> methodology is non-trivial, see the file header for the complete write-up.

This page documents the **25 strategy files** in the library as of this writing.
Each carries an academic or practitioner anchor, a `REGIME_TAG`
(`bull` / `bear` / `regime_neutral`), and the honest paper-vs-implementation
delta. Admission to Tier 1 still requires passing the four-gate
[`admission-criteria.md`](admission-criteria.md); a paper anchor is necessary, not
sufficient. Today **Faber 2007** and **Moreira–Muir 2017** pass all four gates; the
rest are honest `CANDIDATE`s with their failing gate shown openly.

A recurring honesty theme: many files set `paper_claimed_*` to **null** when the
source reports win-rate / t-statistic / conditional-mean tables rather than a
mechanical Sharpe or CAGR (common for the technical-rule and book-sourced
strategies). In those cases the only performance claim we stand behind is the
post-gate one measured on our own data.

---

## Sleeve: Momentum / trend-following

Momentum captures under-reaction and herding — winners keep winning over
intermediate horizons. Trend strategies are **bull-biased** by construction and
carry crash risk at trend reversals.

### Jegadeesh & Titman (1993) — cross-sectional momentum
- **File:** `jegadeesh_titman_1993_cross_sectional_momentum.py`
- **Paper:** *Returns to Buying Winners and Selling Losers: Implications for Stock
  Market Efficiency*, Journal of Finance, 1993.
- **Anomaly:** stocks ranked on prior 3–12 month returns continue to outperform/
  underperform over the next 3–12 months — the canonical academic documentation of
  the momentum effect.
- **Regime:** `bull` (momentum is a trend phenomenon).
- **v1 caveat:** the original is a cross-sectional long–short ranking; verify the
  live universe and ranking horizon against the paper. *(See file header.)*

### Moskowitz, Ooi & Pedersen (2012) — Time Series Momentum (TSMOM)
- **File:** `moskowitz_ooi_pedersen_2012_tsmom.py`
- **Paper:** *Time Series Momentum*, Journal of Financial Economics, 2012.
- **Anomaly:** an asset's own past 12-month return predicts its next-month return —
  go long if the trailing return `r_{t-12,t}` is positive, flat/short otherwise.
- **Regime:** `bull`.
- **v1 caveat:** the paper's diversified portfolio takes **long *and* short**
  positions across many assets; the v1 adaptation is long/flat on a narrower
  universe, so the paper-claimed-vs-actual delta is surfaced in the methodology
  block. *(See file header.)*

### Antonacci (2014) — Dual Momentum
- **File:** `antonacci_2014_dual_momentum.py`
- **Paper:** *Risk Premia Harvesting Through Dual Momentum* (SSRN 2042750; JPM
  Vol. 42 No. 1), 2014.
- **Anomaly:** combines **relative** momentum (pick the stronger asset) with
  **absolute** momentum (defensive switch to cash/bonds when trailing return is
  negative) — trend-following with a downside switch.
- **Regime:** `bull` (defends in bear).

### George & Hwang (2004) — 52-Week High proximity momentum
- **File:** `george_hwang_2004_52w_high.py`
- **Paper:** *The 52-Week High and Momentum Investing*, Journal of Finance, 2004.
- **Anomaly:** proximity of price to its 52-week high predicts continued returns —
  a nearness-to-high signal rather than a raw-return rank.
- **Regime:** `bull`.
- **v1 caveat:** the original is **cross-sectional** (rank all stocks by
  high-proximity); the v1 single-name proxy strips the cross-sectional component, so
  the directional alpha is **lower than the paper claims** and the divergence is
  disclosed. *(See file header.)*

### Appel (1979) — MACD signal-line crossover
- **File:** `appel_1979_macd.py`
- **Paper:** MACD trading method (Appel 1979); academic MA-rule evidence in **Brock,
  Lakonishok & LeBaron (1992)**, Journal of Finance 47(5).
- **Anomaly:** smoothed momentum via the convergence/divergence of two EMAs; trade
  the signal-line crossover.
- **Regime:** `regime_neutral`.
- **v1 caveat:** MACD has no peer-reviewed origin paper, so the academic anchor is
  Brock et al. (1992)'s MA-rule tests. **Data-snooping caveat** (Sullivan,
  Timmermann & White 1999) applies. *(See file header.)*

### Brock, Lakonishok & LeBaron (1992) — dual MA crossover (golden cross)
- **File:** `brock_1992_dual_ma_crossover.py`
- **Paper:** *Simple Technical Trading Rules and the Stochastic Properties of Stock
  Returns*, Journal of Finance 47(5):1731–1764, 1992.
- **Anomaly:** long/short on a fast/slow moving-average crossover; the paper's
  rigorous test of the MA-rule family on the DJIA 1897–1986 found buy-signals carry
  predictive content.
- **Regime:** `bull`.
- **v1 caveat:** the paper reports **conditional mean returns and t-statistics, not
  a tradeable Sharpe or CAGR**, so `paper_claimed_*` are null. *(See file header.)*

### Donchian — channel breakout (Four-Week Rule)
- **File:** `donchian_breakout.py`
- **Paper:** Donchian's breakout rule; academic anchor again **Brock, Lakonishok &
  LeBaron (1992)**.
- **Anomaly:** enter on a breakout above the N-day high (and exit on the symmetric
  low) — the classic trend-capture mechanism.
- **Regime:** `bull`.
- **v1 caveat:** no peer-reviewed origin; anchored on Brock et al. (1992).
  Data-snooping caveat (Sullivan, Timmermann & White 1999) applies; the performance
  claim we stand behind is the post-gate one, `paper_claimed_*` null. *(See file
  header.)*

---

## Sleeve: Mean-reversion / pairs (relative-value, market-neutral)

These strategies bet on convergence — a spread, ratio, or residual that has
diverged should revert. Built to be **regime-neutral** because the bet is on the
*relationship*, not market direction.

### Gatev, Goetzmann & Rouwenhorst (2006) — pairs trading (distance method)
- **Files:** `gatev_2006_pairs_distance.py`, `gatev_2006_pairs_ewa_ewc.py`,
  `gatev_2006_pairs_gld_slv.py`, `gatev_2006_pairs_ko_pep.py`,
  `gatev_2006_portfolio_of_pairs.py`
- **Paper:** *Pairs Trading: Performance of a Relative-Value Arbitrage Rule*, Review
  of Financial Studies 19, 2006.
- **Anomaly:** match securities by minimum sum-of-squared normalized-price distance;
  when a matched pair's normalized prices diverge beyond a threshold, short the
  winner / long the loser and hold to convergence.
- **Regime:** `regime_neutral`.
- **Five implementations:** four are **single specific pairs** (EWA/EWC country
  ETFs, GLD/SLV gold-silver ratio, KO/PEP consumer staples, plus the generic
  distance pair) and one is the **portfolio-of-pairs** faithful-scale method.
- **v1 caveat (important):** the paper's headline ~11% annualized excess return
  belongs to a **diversified portfolio of many pairs**, *not* a single pair. The
  `gatev_2006_portfolio_of_pairs.py` file reproduces the paper's actual design at
  the paper's actual scale (re-form pairs every 6 months); the single-pair files
  explicitly note that a lone pair is **not comparable** to the paper's diversified
  ~11%. *(See file headers.)*

### Engle & Granger (1987) — cointegration pairs
- **File:** `engle_granger_1987_cointegration_pairs.py`
- **Paper:** *Co-integration and Error Correction: Representation, Estimation, and
  Testing*, Econometrica, 1987 (with Vidyamurthy 2004 for the pairs application).
- **Anomaly:** where the distance method trades the *price ratio*, this trades the
  **cointegration residual** — fit a cointegrating relationship, model the spread's
  reversion with an Ornstein–Uhlenbeck half-life, and trade deviations.
- **Regime:** `regime_neutral` (relative-value by design).
- **v1 caveat:** Engle–Granger is the econometric *framework*, not a trading paper;
  the trading application follows Vidyamurthy (2004). *(See file header.)*

### Elliott, van der Hoek & Malcolm (2005) — Kalman-filter dynamic-hedge pairs
- **File:** `elliott_2005_kalman_pairs.py`
- **Paper:** *Pairs Trading*, Quantitative Finance, 2005.
- **Anomaly:** model the hedge ratio as a **time-varying state** estimated by a
  Kalman filter, so the pair's spread adapts as the relationship drifts — more
  robust than a static OLS hedge.
- **Regime:** `regime_neutral`.

### Avellaneda & Lee (2010) — PCA / eigenportfolio statistical arbitrage
- **File:** `avellaneda_lee_2010_pca_statarb.py`
- **Paper:** *Statistical Arbitrage in the U.S. Equities Market*, Quantitative
  Finance, 2010.
- **Anomaly:** decompose returns into principal-component (eigenportfolio) factors;
  trade the mean-reverting **residual** of each name against its factor exposure —
  market-neutral residual reversion.
- **Regime:** `regime_neutral` (market-neutral by construction).
- **v1 caveat:** the PCA-residual approach reads from every `self.datas[i]` each
  bar; verify the live universe matches the paper's residual construction. *(See
  file header.)*

### Bollinger (2001) — lower-band mean reversion
- **File:** `bollinger_2001_band_reversion.py`
- **Paper:** *Bollinger on Bollinger Bands* (McGraw-Hill book), 2001.
- **Anomaly:** buy when price touches the lower band (volatility-scaled distance from
  a moving average), expecting reversion to the mean.
- **Regime:** `regime_neutral`.
- **v1 caveat:** the authoritative reference is a **book, not a peer-reviewed
  paper**, and it describes the bands qualitatively without a mechanical Sharpe/CAGR;
  bands widen in volatile regimes and contract in calm ones, so a fixed-distance
  rule behaves differently across regimes. `paper_claimed_*` null. *(See file
  header.)*

### Connors & Alvarez (2009) — RSI(2) mean reversion
- **File:** `connors_alvarez_2009_rsi2.py`
- **Paper:** *Short Term Trading Strategies That Work* (book), 2009.
- **Anomaly:** short-term mean reversion using a 2-period RSI, entered only inside a
  longer-term uptrend filter.
- **Regime:** `regime_neutral` (mean reversion inside an uptrend filter).
- **v1 caveat:** book source, not peer-reviewed; reports **win-rate / average-gain
  tables** rather than a clean Sharpe/CAGR, so `paper_claimed_*` are null. *(See
  file header.)*

---

## Sleeve: Value / yield

### Fama & French (1988) — dividend-yield predictability
- **File:** `low_tan_wermers_2004_dividend_yield.py`
- **Paper:** *Dividend Yields and Expected Stock Returns*, Journal of Financial
  Economics, 1988.
- **Anomaly:** the dividend yield (D/P) of stocks predicts subsequent returns — a
  value/yield tilt.
- **Regime:** `bear` (value/defensive tilt).
- **v1 caveat:** the live implementation is a **high-D/P-sort proxy**, *not a true
  dividend sort*; the file name references Low, Tan & Wermers (2004) but the
  documented anchor and methodology are the Fama–French (1988) D/P study. Treat as a
  yield-tilt proxy. *(See file header.)*

---

## Sleeve: Quality / defensive

### Arnott, Harvey, Kalesnik & Linnainmaa (2019) — defensive quality
- **File:** `arnott_2019_defensive_quality.py`
- **Paper:** *Alice's Adventures in Factorland: Three Blunders That Plague Factor
  Investing*, Journal of Portfolio Management, 2019.
- **Anomaly:** a defensive/quality tilt informed by the paper's catalogue of naive
  factor-investing blunders (using the market as a beta reference rather than
  chasing raw factor backtests).
- **Regime:** `bear` (defensive).
- **v1 caveat:** the paper is a *critique-and-prescription* on factor investing, not
  a single mechanical strategy; the implementation operationalizes its defensive
  prescription. *(See file header.)*

---

## Sleeve: Risk-parity / allocation / volatility management

These are **allocation overlays** — how to size and balance, not what single
anomaly to chase.

### Maillard, Roncalli & Teïletche (2010) — risk parity / inverse-volatility
- **File:** `maillard_2010_risk_parity.py`
- **Paper:** *The Properties of Equally Weighted Risk Contribution Portfolios*,
  Journal of Portfolio Management, 2010.
- **Anomaly:** size positions so each contributes **equal risk** (equal-risk
  contribution / inverse-volatility), rather than equal capital — a diversification
  overlay designed to hold across regimes.
- **Regime:** `regime_neutral`.
- **Relation to the optimizer:** this is the strategy-level cousin of the
  Hierarchical Risk Parity objective documented in
  [`methodology.md`](methodology.md) §11.

### Moreira & Muir (2017) — volatility-managed portfolios ✅ *passes the gate*
- **File:** `moreira_muir_2017_volatility_managed.py`
- **Paper:** *Volatility-Managed Portfolios*, Journal of Finance, 2017.
- **Anomaly:** scale exposure **inversely to recent realized volatility** — contract
  in high-vol regimes, expand in calm ones. Reduces drawdowns and improves Sharpe
  versus a static-exposure baseline; exploits the weak/negative relationship between
  current volatility and next-period return.
- **Regime:** `bear` (outperforms in bear/high-vol regimes).
- **Status:** one of the two strategies that **passes all four admission gates**
  today.
- **v1 note:** the volatility signal is a rolling realized-volatility estimate (the
  paper uses one-month realized vol). *(See file header.)*

### Faber (2007) — SMA200 tactical asset allocation ✅ *passes the gate*
- **File:** `faber_2007_sma200_timing.py`
- **Paper:** *A Quantitative Approach to Tactical Asset Allocation*, Journal of
  Wealth Management, 2007.
- **Anomaly:** hold the asset while price is above its 200-day SMA; move to cash
  (T-bills) when it falls below — a simple trend filter that cuts drawdowns.
- **Regime:** `bull` (works in trending markets).
- **Status:** one of the two strategies that **passes all four admission gates**
  today.

---

## Sleeve: Seasonality

### Ariel (1987) — turn-of-the-month effect
- **File:** `ariel_1987_turn_of_month.py`
- **Paper:** *A Monthly Effect in Stock Returns*, Journal of Financial Economics,
  1987 (corroborated by Lakonishok & Smidt 1988).
- **Anomaly:** essentially all of the market's cumulative gain over 1963–1981 accrued
  in the first half of trading months; trade the turn-of-month window.
- **Regime:** `regime_neutral`.
- **v1 caveat:** a calendar-window strategy; the file notes `paper_claimed_*` are
  null (the paper reports the effect, not a tradeable Sharpe). *(See file header.)*

---

## Sleeve: Baseline / capital preservation

These are not alpha bets — they are the references everything else is measured
against, and the defensive floor.

### Buy-and-Hold baseline
- **File:** `pipeline_buy_hold.py`
- **Anchor:** internal baseline (no paper).
- **Role:** the long-only SPY buy-and-hold benchmark against which paper-grounded
  strategies are compared. Backtest results are **real**, regenerated via
  `scripts/regen_buy_hold_fixture.py` over 2004-01-02 → 2026-04-30 (includes the
  2008–09 crisis and the 2022 correction).
- **Regime:** `bull` (long-only, bull-biased).

### Capital Preservation — T-Bill / USYC allocation
- **File:** `capital_preservation_tbill.py`
- **Anchor:** internal (no paper); a short-duration Treasury / USYC proxy.
- **Role:** the defensive baseline that works in any regime — the destination the
  trend filters (Faber, Antonacci's absolute-momentum switch) rotate *into* when
  risk-off. Maps naturally to the `fixed_income` / `conservative` risk profiles.
- **Regime:** `regime_neutral` (defensive baseline).

---

## How to read this library

- **Paper anchor strength varies and is disclosed.** Journal-of-Finance/JFE papers
  (Jegadeesh–Titman, Moreira–Muir, Gatev et al., George–Hwang, Fama–French) are
  stronger anchors than practitioner books (Bollinger, Connors–Alvarez) or
  rules anchored on a *related* academic test (MACD/Donchian → Brock et al. 1992).
- **`paper_claimed_*` null ≠ a weak strategy.** It means the source reported
  t-stats/win-rates rather than a mechanical Sharpe/CAGR; the number we stand behind
  is always the post-gate one on our own data.
- **A paper anchor does not equal Tier-1 admission.** Only Faber 2007 and
  Moreira–Muir 2017 pass all four gates today; the rest are honest `CANDIDATE`s with
  their failing gate visible. See [`admission-criteria.md`](admission-criteria.md).
- **Regime tags drive sizing, not just labeling.** A `bull`-tagged strategy is sized
  down by the regime-conditional γ multiplier in `risk_off`/`crisis` regimes (see
  [`methodology.md`](methodology.md) §10).
