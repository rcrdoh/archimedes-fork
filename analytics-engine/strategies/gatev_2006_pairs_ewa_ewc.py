"""Pairs Trading (EWA/EWC country-ETF pair) — Gatev, Goetzmann & Rouwenhorst 2006.

The textbook cointegration pair: iShares MSCI Australia (EWA) vs iShares MSCI
Canada (EWC). Both track commodity-exporter economies with similar terms-of-trade
sensitivity, which is why this pair is the standard worked example in the
stat-arb / cointegration literature. Same distance / z-score logic as the
flagship pair (imports ``PairsDistanceTrading``); only the traded pair and
passport metadata differ. Market-neutral by construction.
"""

from __future__ import annotations

PAPER_ARXIV_ID: str | None = None
PAPER_TITLE = "Pairs Trading: Performance of a Relative-Value Arbitrage Rule"
PAPER_AUTHORS: list[str] = ["Evan Gatev", "William N. Goetzmann", "K. Geert Rouwenhorst"]
PAPER_VENUE = "The Review of Financial Studies"
PAPER_YEAR = 2006
PAPER_DOI = "10.1093/rfs/hhj020"
PAPER_CITATION_COUNT = 2400  # Snapshot 2026-06; verify via Semantic Scholar.

REGIME_TAG: str = "regime_neutral"

METHODOLOGY_SUMMARY = (
    "Distance pairs trading on iShares MSCI Australia (EWA) vs iShares MSCI "
    "Canada (EWC). Both are commodity-exporter country ETFs with co-moving "
    "terms of trade; trade the z-score of their price ratio, long-cheap / "
    "short-rich dollar-neutral on >2-sigma divergence, unwind on reversion."
)

METHODOLOGY_TEXT = (
    "Gatev, Goetzmann & Rouwenhorst (2006) trade pairs whose normalized price "
    "series have historically tracked, opening on >2-sigma divergence and closing "
    "on reversion. EWA/EWC is the most-cited worked example of a cointegrated pair "
    "in the practitioner stat-arb literature: Australia and Canada are both "
    "resource-exporting economies with similar commodity terms-of-trade exposure, "
    "so their equity-index ETFs share a long-run relationship even though either "
    "can drift in the short run.\n\n"
    "v1 Archimedes adaptation: the shared streaming single-pair implementation "
    "(``PairsDistanceTrading``) — price ratio close_EWA / close_EWC, 252-bar "
    "rolling z-score, open dollar-neutral when |z| >= 2.0, close when |z| <= 0.5, "
    "gross ~1.0x (0.5 per leg).\n\n"
    "Provenance note: this distance implementation uses the price-ratio z-score, "
    "NOT a formal Engle-Granger cointegration test — the tested-cointegration "
    "variant is a separate Phase 1.1 strategy. The paper reports a diversified "
    "top-pairs portfolio return, not a clean single-pair Sharpe/CAGR, so "
    "paper_claimed_* are null; the honest backtest fixture is authoritative."
)

PAPER_CLAIMED_SHARPE: float | None = None
PAPER_CLAIMED_CAGR: float | None = None
PAPER_CLAIMED_MAX_DD: float | None = None

ASSET_UNIVERSE: list[str] = ["EWA", "EWC"]
POSITION_SIZING = "equal_weight"
REBALANCE_FREQUENCY = "daily"
RISK_PROFILES: list[str] = ["moderate", "aggressive"]

CURATOR_WALLET: str | None = None
CURATOR_NOTE = (
    "The canonical cointegration teaching pair (it appears in Chan's "
    "'Algorithmic Trading' and most stat-arb course notes). Useful as a "
    "macro-linked diversifier: its convergence is driven by shared commodity "
    "exposure rather than a single-company tether, so it behaves differently "
    "from the equity (KO/PEP) and precious-metals (GLD/SLV) pairs."
)
EXTRACTION_LLM: str | None = None

STATUS = "candidate"

BACKTEST_SHARPE: float | None = None
BACKTEST_CAGR: float | None = None
BACKTEST_MAX_DD: float | None = None
BACKTEST_WIN_RATE: float | None = None
BACKTEST_CALMAR: float | None = None
BACKTEST_CORR_SPY: float | None = None


from gatev_2006_pairs_distance import PairsDistanceTrading  # noqa: E402,F401
