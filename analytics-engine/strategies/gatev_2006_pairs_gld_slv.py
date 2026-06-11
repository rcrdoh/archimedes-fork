"""Pairs Trading (GLD/SLV gold-silver ratio) — Gatev, Goetzmann & Rouwenhorst 2006.

A precious-metals relative-value pair: SPDR Gold Shares (GLD) vs iShares Silver
Trust (SLV). The gold/silver ratio is one of the oldest watched relative-value
relationships in markets; both are monetary/industrial precious metals that
co-move with real rates and risk sentiment, but with silver the more volatile
leg. Same distance / z-score logic as the flagship pair (imports
``PairsDistanceTrading``); only the traded pair and passport metadata differ.
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
    "Distance pairs trading on the gold/silver ratio: SPDR Gold (GLD) vs iShares "
    "Silver (SLV). Trade the z-score of close_GLD / close_SLV, long-cheap / "
    "short-rich dollar-neutral on >2-sigma divergence, unwind on reversion. "
    "Both are precious metals driven by real rates and risk sentiment."
)

METHODOLOGY_TEXT = (
    "Gatev, Goetzmann & Rouwenhorst (2006) trade the divergence of historically "
    "co-moving normalized price series, opening at >2 sigma and closing on "
    "reversion. GLD/SLV expresses the classic gold/silver ratio: both metals are "
    "monetary stores of value sensitive to real interest rates and risk appetite, "
    "so they share a long-run relationship, while silver's larger industrial "
    "demand and thinner market make it the more volatile leg — the divergences "
    "the rule trades.\n\n"
    "v1 Archimedes adaptation: the shared streaming single-pair implementation "
    "(``PairsDistanceTrading``) — price ratio close_GLD / close_SLV, 252-bar "
    "rolling z-score, open dollar-neutral when |z| >= 2.0, close when |z| <= 0.5, "
    "gross ~1.0x (0.5 per leg).\n\n"
    "Provenance note: this is a commodity relative-value pair, not an equity pair "
    "like the ones GGR study, and the dollar-neutral ratio trade does not adjust "
    "for the metals' different volatilities — a Phase 1.2 Kalman dynamic-hedge "
    "variant handles that. The paper reports no clean single-pair number, so "
    "paper_claimed_* are null; the honest backtest fixture is authoritative."
)

PAPER_CLAIMED_SHARPE: float | None = None
PAPER_CLAIMED_CAGR: float | None = None
PAPER_CLAIMED_MAX_DD: float | None = None

ASSET_UNIVERSE: list[str] = ["GLD", "SLV"]
POSITION_SIZING = "equal_weight"
REBALANCE_FREQUENCY = "daily"
RISK_PROFILES: list[str] = ["moderate", "aggressive"]

CURATOR_WALLET: str | None = None
CURATOR_NOTE = (
    "The precious-metals member of the pairs sleeve. Complements GLD/GDX (gold "
    "spot vs miners) with a gold-vs-silver relative-value angle. Caveat for the "
    "passport reader: a fixed dollar-neutral ratio trade ignores that SLV is "
    "materially more volatile than GLD, so a static hedge can leave residual "
    "directional exposure — read the gate verdict accordingly."
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
