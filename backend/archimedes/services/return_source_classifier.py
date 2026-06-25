"""Return-source classification — label each strategy by its dominant
economic return source (T2.5).

The rigor gate (DSR/PBO/OOS) tells you *whether* a strategy's edge survives
multiple-testing correction. It does **not** tell you *why* the edge exists.
This module answers the "why" with an honest, deterministic heuristic: every
validated strategy is tagged with one of four return sources, plus a short
durability note the passport renders next to the rigor metrics.

The four return sources (most-durable to least):

- ``risk_premium``     — compensated, persistent exposure to a priced risk factor
                         (time-series/cross-sectional momentum, carry, value,
                         volatility-managed). Survives because bearing the risk is
                         unpleasant; the premium is the payment for holding it.
- ``mispricing``       — a relative-value / arbitrage edge that exists because a
                         price relationship is temporarily wrong (pairs, stat-arb,
                         cointegration, single-name relative-value). Durable only
                         while the inefficiency and the capital to exploit it persist.
- ``productive_growth``— broad-market / index beta: the return of owning productive
                         enterprise (buy-and-hold, SPY/index, tactical asset
                         allocation across broad sleeves). The most fundamental and
                         durable source — it is the economy compounding.
- ``noise``            — no identifiable economic source; the backtest edge is most
                         likely overfit / data-mined. Assigned when the rigor gate
                         is failed with a weak/insignificant Deflated Sharpe, OR when
                         nothing in the methodology maps to a real source.

Design rules (kept honest + simple, per T2.5):

1. **Deterministic.** Pure function of fields already on the passport
   (paper title, methodology summary, asset universe, DSR / rigor signals).
   No LLM call, no randomness, no network.
2. **Rigor overrides taxonomy.** A strategy that failed the rigor gate with a
   statistically *insignificant* DSR is labelled ``noise`` regardless of how its
   methodology reads — an uncompensated, overfit edge has no durable source even
   if it is "momentum-shaped." Strategies that simply have *no backtest yet*
   (DSR unknown) keep their taxonomy label; we don't punish "not yet measured."
3. **Keyword mapping is explicit and auditable.** The mapping below is the
   contract; it lives in ``_SOURCE_KEYWORDS`` so a reviewer can read it in one place.

The classifier reads a small structural view of a strategy rather than the
``StrategyPassport`` dataclass directly, so it can be exercised hermetically in
unit tests without constructing a full passport.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "ReturnSource",
    "StrategyView",
    "classify_return_source",
    "classify_strategy",
]


class ReturnSource(str, Enum):
    """Dominant economic source of a strategy's return."""

    RISK_PREMIUM = "risk_premium"
    MISPRICING = "mispricing"
    PRODUCTIVE_GROWTH = "productive_growth"
    NOISE = "noise"


@dataclass(frozen=True)
class StrategyView:
    """Minimal structural view of a strategy for classification.

    Built from the fields already present on every ``StrategyPassport`` /
    ``StrategyPassportRecord`` so the classifier never needs the full object.
    """

    paper_title: str = ""
    methodology_summary: str = ""
    asset_universe: tuple[str, ...] = ()
    deflated_sharpe_ratio: float | None = None
    dsr_p_value: float | None = None
    passes_rigor_gate: bool = False


# ── Keyword → return source mapping (the auditable contract) ──────────────
#
# Each (source, keywords) pair below is matched against the lowercased
# concatenation of paper title + methodology summary. Order matters: the
# first source whose keyword set hits wins, so the list is ordered from the
# most specific / strongest signal (single-name arbitrage) to the broadest
# (productive growth). The economic rationale for each mapping:
#
#   risk_premium      — momentum (TSMOM / cross-sectional), carry, value,
#                       volatility-managed, trend, seasonality-as-risk: all are
#                       compensated factor exposures documented in the asset-
#                       pricing literature.
#   mispricing        — pairs / stat-arb / cointegration / mean-reversion /
#                       relative-value: a temporary price error, not a premium.
#   productive_growth — buy-and-hold, index, tactical asset allocation, broad
#                       equity beta: owning the productive economy.
#
# A strategy with no keyword hit and no rigor evidence falls through to noise.
_SOURCE_KEYWORDS: tuple[tuple[ReturnSource, tuple[str, ...]], ...] = (
    (
        ReturnSource.MISPRICING,
        (
            "pairs",
            "stat-arb",
            "statistical arbitrage",
            "arbitrage",
            "cointegration",
            "co-integration",
            "relative-value",
            "relative value",
            "mean-reversion",
            "mean reversion",
            "kalman",
            "rsi-2",
            "bollinger",
            # NOTE: "spread" is deliberately NOT a keyword — long/short *factor*
            # portfolios also "earn a spread" (e.g. Betting Against Beta), so it
            # produced false-positive mispricing labels on risk-premium factors.
        ),
    ),
    (
        ReturnSource.RISK_PREMIUM,
        (
            "momentum",
            "tsmom",
            "time series momentum",
            "time-series momentum",
            "carry",
            "value",
            "volatility-managed",
            "volatility managed",
            "vol-managed",
            "trend",
            "trend-following",
            "trend following",
            "seasonal",
            "monthly effect",
            "risk premi",  # "risk premium" / "risk premia"
            # Established cross-sectional factor premia — each is a documented,
            # compensated risk exposure in the asset-pricing literature.
            "quality",  # Quality-minus-Junk (Asness et al.)
            "dividend",  # dividend-yield tilt (matches "dividend yield")
            "betting against beta",
            "low-beta",
            "low beta",
            "factor",
        ),
    ),
    (
        ReturnSource.PRODUCTIVE_GROWTH,
        (
            "buy-and-hold",
            "buy and hold",
            "buy & hold",
            "index",
            "tactical asset allocation",
            "asset allocation",
            "moving average",
            "200-day",
            "sma200",
            "broad market",
        ),
    ),
)

# Broad-market tickers — when the entire universe is broad index/treasury
# exposure and nothing more specific matched, the source is productive growth.
_BROAD_MARKET_TICKERS = frozenset({"SPY", "VOO", "VTI", "QQQ", "IWM", "DIA", "NIKKEI", "TREASURY", "BIL", "AGG", "TLT"})


# Durability notes — one honest sentence per source. Rendered on the passport.
_DURABILITY_NOTES: dict[ReturnSource, str] = {
    ReturnSource.RISK_PREMIUM: (
        "Compensated exposure to a priced risk factor — durable while the factor "
        "stays unpleasant enough that the premium persists."
    ),
    ReturnSource.MISPRICING: (
        "Relative-value edge from a temporary price error — durable only while the "
        "inefficiency and the capital to arbitrage it persist; decays as it crowds."
    ),
    ReturnSource.PRODUCTIVE_GROWTH: (
        "Broad-market beta — the return of owning the productive economy. The most "
        "fundamental and durable source, but undifferentiated from passive holding."
    ),
    ReturnSource.NOISE: (
        "No identifiable economic source; the backtest edge is most likely overfit "
        "or data-mined. Treat any apparent alpha as fragile."
    ),
}

# Stronger note when the rigor evidence *confirms* the no-source verdict: the
# strategy both lacks an economic explanation AND failed the rigor gate with an
# insignificant Deflated Sharpe. This is the clearest "data-mined" case.
_NOISE_NOTE_RIGOR_CONFIRMED = (
    "No identifiable economic source, and the edge failed the rigor gate with a "
    "statistically insignificant Deflated Sharpe — the backtest result is most "
    "likely data-mined. Do not deploy on the strength of the backtest alone."
)


def _rigor_says_noise(view: StrategyView) -> bool:
    """True when the rigor evidence affirmatively marks the edge as noise.

    A failed rigor gate *with a statistically insignificant* Deflated Sharpe is
    the honest signal of an uncompensated / overfit edge. We require BOTH a
    failed gate AND an insignificant DSR (p >= 0.05) so that a strategy which is
    simply unevaluated (DSR unknown) is never mislabelled noise.

    NOTE: this is applied only as a *tie-breaker* for strategies whose
    methodology maps to no known economic source (see ``classify_return_source``).
    A momentum strategy that fails the gate keeps its ``risk_premium`` source —
    its return source is still a risk premium; that it doesn't survive rigor is
    communicated separately by the rigor verdict. We don't double-punish an
    explained edge by also stripping its (honest) source label.
    """
    if view.passes_rigor_gate:
        return False
    if view.dsr_p_value is None:
        return False
    return view.dsr_p_value >= 0.05


def _taxonomy_source(view: StrategyView) -> ReturnSource | None:
    """Return the keyword/universe-derived source, or None if nothing matched."""
    haystack = f"{view.paper_title} {view.methodology_summary}".lower()
    for source, keywords in _SOURCE_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            return source

    # Universe fallback: a purely broad-market universe with no specific
    # methodology keyword is productive-growth beta (e.g. an index baseline).
    universe = {t.upper() for t in view.asset_universe}
    if universe and universe <= _BROAD_MARKET_TICKERS:
        return ReturnSource.PRODUCTIVE_GROWTH

    return None


def classify_return_source(view: StrategyView) -> tuple[ReturnSource, str]:
    """Classify a strategy's dominant return source.

    Returns ``(ReturnSource, durability_note)``. Deterministic and side-effect
    free — pure function of the fields on ``view``.

    Precedence:
      1. Methodology taxonomy (keyword mapping, then broad-market universe).
         An explained edge keeps its source label regardless of rigor.
      2. If taxonomy found NO source, fall back: a failed gate with an
         insignificant DSR is affirmatively ``noise`` (overfit, no source);
         anything else is ``noise`` too (nothing mapped to a real source).
    """
    source = _taxonomy_source(view)
    if source is not None:
        return source, _DURABILITY_NOTES[source]

    # No economic source in the methodology → noise. The rigor signal doesn't
    # change the label (both branches are noise) but it strengthens the note:
    # an unmapped edge that *also* failed the gate on an insignificant DSR is the
    # clearest data-mined case.
    note = _NOISE_NOTE_RIGOR_CONFIRMED if _rigor_says_noise(view) else _DURABILITY_NOTES[ReturnSource.NOISE]
    return ReturnSource.NOISE, note


def classify_strategy(strategy) -> tuple[str, str]:
    """Convenience adapter: classify a ``StrategyPassport`` / passport-like object.

    Accepts anything exposing ``paper_title``, ``methodology_summary``,
    ``asset_universe`` and the rigor fields. Returns ``(return_source_value,
    durability_note)`` as plain strings for direct assignment onto API schemas.
    """
    view = StrategyView(
        paper_title=getattr(strategy, "paper_title", "") or "",
        methodology_summary=getattr(strategy, "methodology_summary", "") or "",
        asset_universe=tuple(getattr(strategy, "asset_universe", ()) or ()),
        deflated_sharpe_ratio=getattr(strategy, "deflated_sharpe_ratio", None),
        dsr_p_value=getattr(strategy, "dsr_p_value", None),
        passes_rigor_gate=bool(getattr(strategy, "passes_rigor_gate", False)),
    )
    source, note = classify_return_source(view)
    return source.value, note
