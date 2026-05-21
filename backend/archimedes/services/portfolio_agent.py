"""LLM-driven portfolio agent.

The rule-based ``StrategySignalEvaluator`` produces per-(strategy × asset)
signals against a hard-coded universe.  This agent layer takes those
signals (plus a global market scan) and asks an LLM to construct the
final portfolio — picking specific instruments (including *individual*
stocks and bonds, not just ETFs), justifying each pick, and anchoring
every position to one of our paper-grounded strategies (the "strategy
passport" model from CLAUDE.md § "Architectural primitives").

If no LLM backend is available, the caller should fall back to the
rule-based aggregation in ``api/routes.py``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from archimedes.services.llm_backend import LLMBackend, make_llm_backend
from archimedes.services.strategy_signal_evaluator import (
    GLOBAL_ASSETS,
    synth_display,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentPick:
    """A single agent-chosen position."""

    ticker: str           # display symbol (e.g. "NVDA", "USD/TRY", "BIST100")
    synth: str            # internal synth code (e.g. "sNVDA")
    asset_class: str      # us_stock, us_bond_long, fx, crypto, ...
    exchange: str
    weight: float         # 0 - 1, fraction of the *synth budget* (not total)
    paper_anchor: str     # which paper-strategy supports this pick
    reasoning: str        # one-sentence justification


@dataclass
class AgentPortfolio:
    """Full agent output: thesis + picks."""

    thesis: str
    picks: list[AgentPick]
    model_id: str
    served_model: str


# ── Response cache ─────────────────────────────────────────────────
# Avoid hammering the LLM for every advisor request.
_RESPONSE_CACHE: dict[str, tuple[AgentPortfolio, float]] = {}
_CACHE_TTL_SEC = 300  # 5 minutes


def _cache_key(regime: str, risk_profile: str, top_synths: tuple[str, ...]) -> str:
    return f"{regime}|{risk_profile}|{','.join(sorted(top_synths))}"


def _build_system_prompt() -> str:
    return (
        "You are Archimedes, an autonomous portfolio-construction agent for a "
        "non-custodial USDC-settled vault on Arc.\n\n"
        "Your responsibility: pick a diversified portfolio of *individual* tradable "
        "instruments (individual stocks, bonds, futures, FX, crypto — not just "
        "broad ETFs unless they are the best vehicle for a thesis). Every pick "
        "MUST be anchored to one of the paper-grounded quant strategies in our "
        "library (the 'strategy passport' model). You may NOT invent strategies — "
        "anchor only to the ones provided in the user prompt.\n\n"
        "PRINCIPLES\n"
        "- Diversify by asset class AND by exchange (US, European, Asian, Turkish, "
        "  metals/futures, FX, crypto).\n"
        "- Prefer individual stocks where you have a specific thesis (e.g. NVDA, ASML "
        "  for AI capex; THYAO, KCHOL for Turkish play; XOM, CVX for energy).\n"
        "- Use individual bond ETFs by maturity (BIL=t-bills, SHY=1-3y, IEF=7-10y, "
        "  TLT=20y+, TIP=inflation-linked) rather than only aggregate funds.\n"
        "- Respect the synth-budget cap. The remainder is held as USDC (the safety "
        "  floor) which the user already knows about — you don't list USDC.\n"
        "- No single pick > 20% of the synth budget.\n"
        "- Pick 5-12 instruments total.\n\n"
        "OUTPUT FORMAT\n"
        "Return ONLY a JSON object, nothing else (no prose before or after). Schema:\n"
        "{\n"
        '  "thesis": "1-2 sentence portfolio thesis tying regime + risk profile to picks",\n'
        '  "picks": [\n'
        '    {"ticker": "NVDA", "weight": 0.12, "paper_anchor": "moskowitz_2012_tsmom",\n'
        '     "reasoning": "12m return +75%, qualifies for TSMOM long; AI capex cycle"},\n'
        "    ...\n"
        "  ]\n"
        "}\n\n"
        "`ticker` MUST be the display symbol shown in the AVAILABLE UNIVERSE table. "
        "Weights are fractions of the synth budget (will be renormalized if needed). "
        "`paper_anchor` MUST be one of the strategy ids listed below."
    )


def _format_universe(scan_universe_synths: set[str]) -> str:
    """Render the available-universe table by asset class."""
    by_class: dict[str, list[tuple[str, str, str]]] = {}
    for synth, (_yf, display, asset_class, exchange) in GLOBAL_ASSETS.items():
        by_class.setdefault(asset_class, []).append((synth, display, exchange))

    parts: list[str] = []
    for asset_class in sorted(by_class):
        rows = by_class[asset_class]
        names = ", ".join(
            f"{d}" + ("*" if s in scan_universe_synths else "")
            for s, d, _e in sorted(rows)
        )
        parts.append(f"  - {asset_class:20s}: {names}")
    return "\n".join(parts)


def _format_market_scan(market_ranking: list[dict]) -> str:
    """Format the top-ranked market opportunities."""
    if not market_ranking:
        return "  (none — live data unavailable)"
    lines: list[str] = []
    for r in market_ranking:
        lines.append(
            f"  {r['display']:12s} {r['asset_class']:18s} "
            f"score={r['score']:+6.2f}  90d_mom={r['momentum_90d']*100:+6.1f}%  "
            f"vol={r['vol_ann']*100:5.1f}%  [{r['exchange']}]"
        )
    return "\n".join(lines)


def _format_strategies(strategies: list[Any]) -> str:
    """Render paper strategies with their backtest stats + signal rules."""
    rule_summary = {
        "faber": "long when price > 200-day SMA, else flat",
        "moreira": "scale exposure by target_vol / realized_vol (vol-managed)",
        "moskowitz": "long if trailing 12m return > 0 (time-series momentum)",
        "george_hwang": "long when within 5% of 52-week high",
        "capital_preservation": "always long the asset (T-bill proxy)",
        "buy_hold": "always long the asset",
    }

    def _summarize_rule(strategy: Any) -> str:
        path = (strategy.strategy_code_path or "").lower()
        title = (strategy.paper_title or "").lower()
        for key, rule in rule_summary.items():
            if key in path or key in title:
                return rule
        return "see paper"

    lines: list[str] = []
    for s in strategies:
        sr = s.real_sharpe if s.real_sharpe is not None else float("nan")
        cagr = (s.real_cagr or 0.0) * 100
        rule = _summarize_rule(s)
        lines.append(
            f"  - id={s.id[:8]}  title={s.paper_title}\n"
            f"      sharpe={sr:.2f}  cagr={cagr:+.1f}%  rigor={'PASS' if s.passes_rigor_gate else 'candidate'}\n"
            f"      signal rule: {rule}"
        )
    return "\n".join(lines)


def _build_user_prompt(
    regime: str,
    regime_confidence: float,
    risk_profile: str,
    usdc_floor: float,
    synth_budget: float,
    market_ranking: list[dict],
    strategies: list[Any],
    scan_universe_synths: set[str],
) -> str:
    return (
        f"## CONTEXT\n"
        f"- regime: {regime} (confidence {regime_confidence:.0%})\n"
        f"- risk_profile: {risk_profile}\n"
        f"- usdc_floor: {usdc_floor:.0%} (held as USDC, you do not allocate this)\n"
        f"- synth_budget: {synth_budget:.0%} (your weights must sum to <= this)\n\n"
        f"## TOP MARKET OPPORTUNITIES (live 90-day risk-adjusted ranking)\n"
        f"{_format_market_scan(market_ranking)}\n\n"
        f"## PAPER STRATEGIES (you must anchor every pick to one of these ids)\n"
        f"{_format_strategies(strategies)}\n\n"
        f"## AVAILABLE UNIVERSE (pick any of these tickers; * = appeared in top scan)\n"
        f"{_format_universe(scan_universe_synths)}\n\n"
        f"## YOUR TASK\n"
        f"Construct the portfolio. Return ONLY JSON per the schema in the system prompt."
    )


# ── Parsing helpers ────────────────────────────────────────────────


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Greedy {...} match as last resort
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _resolve_ticker(ticker: str) -> tuple[str, tuple[str, str, str, str]] | None:
    """Look up an LLM-provided ticker in GLOBAL_ASSETS.

    The LLM is told to use display symbols; this also accepts synth
    codes (sNVDA) and yfinance tickers (NVDA, BRK-B, XU100.IS) as
    fallbacks.
    """
    if ticker in GLOBAL_ASSETS:
        return ticker, GLOBAL_ASSETS[ticker]
    for synth, entry in GLOBAL_ASSETS.items():
        yf_t, display, _ac, _ex = entry
        if ticker == display or ticker == yf_t:
            return synth, entry
    norm = ticker.upper().replace(" ", "")
    for synth, entry in GLOBAL_ASSETS.items():
        yf_t, display, _ac, _ex = entry
        if norm in (display.upper(), yf_t.upper()):
            return synth, entry
    return None


# ── PortfolioAgent ─────────────────────────────────────────────────


class PortfolioAgent:
    """LLM-driven portfolio constructor.

    Construct once at process startup; the held LLM backend caches its
    own client.  Method ``propose_portfolio`` is sync but the caller
    runs it in a thread (the LLM call blocks on the network).
    """

    def __init__(self, backend: LLMBackend | None = None) -> None:
        self._backend: LLMBackend = backend or make_llm_backend()

    @property
    def available(self) -> bool:
        return getattr(self._backend, "available", False)

    @property
    def model_id(self) -> str:
        return getattr(self._backend, "model_id", "unknown")

    def propose_portfolio(
        self,
        regime: str,
        regime_confidence: float,
        risk_profile: str,
        usdc_floor: float,
        synth_budget: float,
        market_ranking: list[dict],
        strategies: list[Any],
        scan_universe_synths: set[str],
    ) -> AgentPortfolio | None:
        if not self.available:
            logger.info("PortfolioAgent unavailable — no LLM backend configured")
            return None

        top_synth_codes = tuple(r["synth"] for r in market_ranking)
        cache_key = _cache_key(regime, risk_profile, top_synth_codes)
        cached = _RESPONSE_CACHE.get(cache_key)
        if cached and (time.time() - cached[1]) < _CACHE_TTL_SEC:
            return cached[0]

        system = _build_system_prompt()
        user = _build_user_prompt(
            regime, regime_confidence, risk_profile,
            usdc_floor, synth_budget, market_ranking,
            strategies, scan_universe_synths,
        )

        try:
            raw = self._backend.complete(system=system, user=user)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("PortfolioAgent LLM call failed: %s", e)
            return None

        data = _extract_json(raw)
        if not data or not isinstance(data, dict):
            logger.warning("PortfolioAgent: could not parse JSON from response: %r", raw[:300])
            return None

        thesis = str(data.get("thesis", "")).strip()
        raw_picks = data.get("picks") or []
        if not isinstance(raw_picks, list):
            logger.warning("PortfolioAgent: picks not a list")
            return None

        picks: list[AgentPick] = []
        for entry in raw_picks:
            if not isinstance(entry, dict):
                continue
            ticker = str(entry.get("ticker", "")).strip()
            if not ticker:
                continue
            resolved = _resolve_ticker(ticker)
            if not resolved:
                logger.info("PortfolioAgent: unknown ticker %r — skipping", ticker)
                continue
            synth, (_yf, display, asset_class, exchange) = resolved
            try:
                weight = float(entry.get("weight", 0.0))
            except (TypeError, ValueError):
                continue
            if weight <= 0:
                continue
            weight = min(weight, 0.20)  # enforce per-asset cap
            picks.append(AgentPick(
                ticker=display,
                synth=synth,
                asset_class=asset_class,
                exchange=exchange,
                weight=weight,
                paper_anchor=str(entry.get("paper_anchor", "")).strip(),
                reasoning=str(entry.get("reasoning", "")).strip(),
            ))

        if not picks:
            logger.warning("PortfolioAgent: parsed zero valid picks from LLM response")
            return None

        # Normalize weights to the synth budget
        total = sum(p.weight for p in picks)
        if total > 0:
            for p in picks:
                p.weight = round(p.weight / total * synth_budget, 4)

        portfolio = AgentPortfolio(
            thesis=thesis or f"{regime} regime, {risk_profile} risk: diversified across asset classes",
            picks=picks,
            model_id=self.model_id,
            served_model=getattr(self._backend, "served_model", self.model_id),
        )
        _RESPONSE_CACHE[cache_key] = (portfolio, time.time())
        return portfolio


# Singleton — constructed lazily to honor env vars set after import.
_AGENT: PortfolioAgent | None = None


def get_portfolio_agent() -> PortfolioAgent:
    global _AGENT  # pylint: disable=global-statement
    if _AGENT is None:
        _AGENT = PortfolioAgent()
    return _AGENT


def synth_for_display(display: str) -> str | None:
    """Convenience for callers that have a display symbol and need the synth."""
    for synth, (_yf, d, _ac, _ex) in GLOBAL_ASSETS.items():
        if d == display:
            return synth
    return None


# Reuse the canonical display helper for callers that import this module
display_for_synth = synth_display
