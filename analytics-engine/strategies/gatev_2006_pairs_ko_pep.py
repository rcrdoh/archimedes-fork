"""Pairs Trading (KO/PEP consumer-staples pair) — Gatev, Goetzmann & Rouwenhorst 2006.

A second-wave application of the same distance / z-score relative-value rule as
the flagship GLD/GDX pair, but on Coca-Cola (KO) vs PepsiCo (PEP): two large-cap
consumer-staples beverage names with a durable same-industry economic linkage.
The strategy *logic* is identical (it imports ``PairsDistanceTrading``); only the
traded pair and its passport metadata differ. Market-neutral by construction.
"""

from __future__ import annotations

PAPER_ARXIV_ID: str | None = None
PAPER_TITLE = "Pairs Trading: Performance of a Relative-Value Arbitrage Rule"
PAPER_AUTHORS: list[str] = ["Evan Gatev", "William N. Goetzmann", "K. Geert Rouwenhorst"]
PAPER_VENUE = "The Review of Financial Studies"
PAPER_YEAR = 2006
PAPER_DOI = "10.1093/rfs/hhj020"
PAPER_CITATION_COUNT = 2400  # Snapshot 2026-06; verify via Semantic Scholar.

# Relative-value / market-neutral — designed to be regime-agnostic.
REGIME_TAG: str = "regime_neutral"

METHODOLOGY_SUMMARY = (
    "Distance pairs trading on Coca-Cola (KO) vs PepsiCo (PEP). Trade the price "
    "ratio's z-score: when |z| diverges past 2 sigma, go long the cheap leg / "
    "short the rich leg dollar-neutral; unwind as the spread reverts. Two "
    "same-industry consumer-staples names with a strong fundamental tether."
)

METHODOLOGY_TEXT = (
    "Gatev, Goetzmann & Rouwenhorst (2006) match securities into pairs by minimum "
    "distance between normalized historical price series, then trade divergences "
    "of more than two formation-period standard deviations. KO/PEP is a textbook "
    "same-industry pair: both are global consumer-staples beverage companies whose "
    "revenues, input costs (sugar, aluminium, PET), and demand cycle co-move, which "
    "is the kind of fundamental linkage GGR argue underpins durable convergence.\n\n"
    "v1 Archimedes adaptation: the shared streaming single-pair implementation "
    "(``PairsDistanceTrading``). We compute the price ratio (close_KO / close_PEP), "
    "its rolling mean and standard deviation over a 252-bar window, then a z-score. "
    "Open dollar-neutral (long cheap / short rich) when |z| >= 2.0 and close when "
    "|z| <= 0.5; gross exposure capped at ~1.0x (0.5 per leg).\n\n"
    "Provenance note: the paper's headline ~11% figure is for a diversified "
    "portfolio of the top 20 equity pairs, NOT a single pair, and it reports no "
    "clean single-pair Sharpe or max-drawdown. We therefore leave paper_claimed_* "
    "null rather than attach a non-comparable number — the honest backtest metrics "
    "in backtest_fixtures.json are authoritative."
)

# No clean single-pair number in the source → all null (provenance discipline).
PAPER_CLAIMED_SHARPE: float | None = None
PAPER_CLAIMED_CAGR: float | None = None
PAPER_CLAIMED_MAX_DD: float | None = None

ASSET_UNIVERSE: list[str] = ["KO", "PEP"]
POSITION_SIZING = "equal_weight"  # dollar-neutral 0.5 per leg
REBALANCE_FREQUENCY = "daily"
RISK_PROFILES: list[str] = ["moderate", "aggressive"]

CURATOR_WALLET: str | None = None
CURATOR_NOTE = (
    "The canonical equity 'cola pair'. Unlike GLD/GDX (a commodity-linkage pair), "
    "KO/PEP is a same-sector substitute pair, so it diversifies the market-neutral "
    "sleeve across a different convergence mechanism. Expect long, slow spread "
    "cycles — corporate fundamentals drift slowly, so realised holding periods are "
    "longer than the commodity pairs."
)
EXTRACTION_LLM: str | None = None

STATUS = "candidate"

# Real backtest metrics are authoritative in backtest_fixtures.json (computed by
# scripts/regen_fixtures.py via engine.run_pairs_backtest on KO/PEP). Documentation
# fallbacks left null until the fixture is generated.
BACKTEST_SHARPE: float | None = None
BACKTEST_CAGR: float | None = None
BACKTEST_MAX_DD: float | None = None
BACKTEST_WIN_RATE: float | None = None
BACKTEST_CALMAR: float | None = None
BACKTEST_CORR_SPY: float | None = None


# Reuse the flagship pairs logic verbatim — only the traded pair + passport differ.
from gatev_2006_pairs_distance import PairsDistanceTrading  # noqa: E402,F401
