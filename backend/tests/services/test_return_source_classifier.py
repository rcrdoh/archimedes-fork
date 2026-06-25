"""Hermetic unit tests for return_source_classifier (T2.5).

No network, no Redis, no DB — pure function of strategy fields. Covers the
keyword mapping for each return source, the rigor-override → noise rule, the
broad-market universe fallback, and that the classification serializes onto the
StrategyResponse passport schema.
"""

from __future__ import annotations

import pytest
from archimedes.api.schemas import StrategyResponse
from archimedes.services.return_source_classifier import (
    ReturnSource,
    StrategyView,
    classify_return_source,
    classify_strategy,
)

# ── Keyword mapping: risk_premium ─────────────────────────────────────


@pytest.mark.parametrize(
    "title,methodology",
    [
        ("Time Series Momentum", ""),
        ("Value and Momentum Everywhere", ""),
        ("Volatility-Managed Portfolios", ""),
        ("Carry", ""),
        ("A Monthly Effect in Stock Returns", ""),
        # An opaque title whose risk-premium nature lives in the methodology
        # (a trend-following signal). The classifier reads title + methodology.
        ("Simple Technical Trading Rules", "Trend-following filter on cross-sectional return."),
    ],
)
def test_risk_premium_strategies(title, methodology):
    src, note = classify_return_source(StrategyView(paper_title=title, methodology_summary=methodology))
    assert src is ReturnSource.RISK_PREMIUM, f"{title!r} should map to risk_premium"
    assert note  # durability note is non-empty


def test_opaque_title_with_no_keyword_is_noise_not_guessed():
    # The classifier must NOT hallucinate a source from an opaque title that
    # carries no economic keyword — honest "noise" beats a fabricated label.
    src, _ = classify_return_source(
        StrategyView(paper_title="Simple Technical Trading Rules and the Stochastic Properties of Stock Returns")
    )
    assert src is ReturnSource.NOISE


# ── Keyword mapping: mispricing ───────────────────────────────────────


@pytest.mark.parametrize(
    "title",
    [
        "Pairs Trading: Performance of a Relative-Value Arbitrage Rule",
        "Co-integration and Error Correction",
        "Statistical Arbitrage in the US Equities Market",
        "Pairs Trading",  # Elliott Kalman
        "RSI-2 Mean-Reversion",
        "Bollinger Band Reversal",
    ],
)
def test_mispricing_strategies(title):
    src, _ = classify_return_source(StrategyView(paper_title=title))
    assert src is ReturnSource.MISPRICING, f"{title!r} should map to mispricing"


def test_mispricing_wins_over_risk_premium_on_overlap():
    # "Time Series Momentum" pairs strategy → arbitrage keyword is more specific
    # and is checked first, so mispricing wins.
    src, _ = classify_return_source(
        StrategyView(
            paper_title="Momentum pairs arbitrage",
            methodology_summary="A statistical arbitrage spread on a momentum pair.",
        )
    )
    assert src is ReturnSource.MISPRICING


# ── Keyword mapping: productive_growth ────────────────────────────────


@pytest.mark.parametrize(
    "title,methodology",
    [
        ("A Quantitative Approach to Tactical Asset Allocation", "200-day moving average on broad index"),
        ("Buy-and-Hold Baseline", "Buy and hold the index."),
        ("Index Tracking", "Hold a broad market index."),
    ],
)
def test_productive_growth_strategies(title, methodology):
    src, _ = classify_return_source(StrategyView(paper_title=title, methodology_summary=methodology))
    assert src is ReturnSource.PRODUCTIVE_GROWTH


def test_broad_market_universe_fallback():
    # No methodology keyword hit, but a purely broad-market universe → growth.
    src, _ = classify_return_source(
        StrategyView(
            paper_title="Untitled baseline",
            methodology_summary="Hold these tickers.",
            asset_universe=("SPY", "BIL"),
        )
    )
    assert src is ReturnSource.PRODUCTIVE_GROWTH


# ── noise: no economic source ─────────────────────────────────────────


def test_no_keyword_no_universe_is_noise():
    src, note = classify_return_source(StrategyView(paper_title="???", methodology_summary="some opaque rule"))
    assert src is ReturnSource.NOISE
    assert "overfit" in note.lower() or "data-mined" in note.lower()


def test_explained_edge_keeps_source_despite_failed_gate():
    # A momentum strategy that FAILED the rigor gate is still risk_premium —
    # its return source is unchanged; the rigor verdict communicates the failure
    # separately. We don't double-punish an explained edge by stripping its label.
    src, _ = classify_return_source(
        StrategyView(
            paper_title="Time Series Momentum",
            passes_rigor_gate=False,
            dsr_p_value=0.42,  # insignificant
        )
    )
    assert src is ReturnSource.RISK_PREMIUM


def test_unexplained_edge_failing_rigor_gets_stronger_noise_note():
    # No economic keyword AND failed the gate on an insignificant DSR → noise,
    # with the stronger "data-mined" note that names the rigor failure.
    src, note = classify_return_source(
        StrategyView(
            paper_title="Proprietary signal",
            methodology_summary="opaque rule with no documented source",
            passes_rigor_gate=False,
            dsr_p_value=0.42,
        )
    )
    assert src is ReturnSource.NOISE
    assert "rigor gate" in note.lower()


def test_unevaluated_strategy_keeps_taxonomy():
    # No backtest yet (dsr_p_value is None) → keep the taxonomy label.
    src, _ = classify_return_source(
        StrategyView(paper_title="Pairs Trading", passes_rigor_gate=False, dsr_p_value=None)
    )
    assert src is ReturnSource.MISPRICING


def test_passing_strategy_keeps_taxonomy():
    src, _ = classify_return_source(
        StrategyView(paper_title="Volatility-Managed Portfolios", passes_rigor_gate=True, dsr_p_value=0.01)
    )
    assert src is ReturnSource.RISK_PREMIUM


# ── Adapter + determinism ─────────────────────────────────────────────


def test_classify_strategy_adapter_returns_strings():
    class _Stub:
        paper_title = "Time Series Momentum"
        methodology_summary = ""
        asset_universe = ("SPY",)
        deflated_sharpe_ratio = 1.0
        dsr_p_value = 0.01
        passes_rigor_gate = True

    source, note = classify_strategy(_Stub())
    assert source == "risk_premium"
    assert isinstance(note, str) and note


def test_classifier_is_deterministic():
    view = StrategyView(paper_title="Pairs Trading", methodology_summary="cointegration spread")
    assert classify_return_source(view) == classify_return_source(view)


# ── Passport serialization ────────────────────────────────────────────


def test_return_source_serializes_on_passport_schema():
    resp = StrategyResponse(
        id="s1",
        methodology_summary="m",
        asset_universe=["SPY"],
        position_sizing="equal_weight",
        rebalance_frequency="weekly",
        status="validated",
        return_source="risk_premium",
        return_source_note="Compensated exposure to a priced risk factor.",
    )
    dumped = resp.model_dump()
    assert dumped["return_source"] == "risk_premium"
    assert dumped["return_source_note"].startswith("Compensated")


def test_return_source_defaults_to_noise_on_schema():
    resp = StrategyResponse(
        id="s2",
        methodology_summary="m",
        asset_universe=[],
        position_sizing="equal_weight",
        rebalance_frequency="weekly",
        status="candidate",
    )
    assert resp.return_source == "noise"
    assert resp.return_source_note == ""
