"""Strategy architect — the interactive Claude orchestrator (Dan's lane).

This is the "AI citizen reasoning out loud" path: a user describes what they
want in plain language, picks a risk profile, and Claude (the Maestro) selects
and weights paper-grounded strategies from the curated library, narrating its
reasoning. Deterministic Workers downstream (Step 2 guardrail, Step 3 reasoning
trace) take it from there — Claude never computes a number that has to be
auditable.

Boundary vs. Chuan's `IAgentOrchestrator`: that is the autonomous
"maintain the portfolio" loop. This is the interactive "design me a portfolio"
request. They share `LocalStrategyProvider` and (later) the weight guardrail.

LLM-backend seam: `LLMBackend` is a Protocol. `ClaudeBackend` is the hackathon
default (hosted). `CannedBackend` keeps the feature demoable and testable with
no API key. A local Ollama backend is the post-hackathon / schedule-permitting
flex — `submodules/KnowledgeBase/papers_analysis/summarize.py` shows the swap.

References:
- `docs/specs/component-interfaces-spec.md` — Dan owns the strategy lane
- `docs/specs/strategy-passport-spec.md` — provenance the proposal must carry
- `backend/archimedes/models/portfolio.py` — RiskProfile, RISK_PROFILE_PARAMS
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from archimedes.models.portfolio import RISK_PROFILE_PARAMS, RiskProfile
from archimedes.models.strategy import Strategy
from archimedes.services.strategy_provider import (
    LocalStrategyProvider,
    default_provider,
)

logger = logging.getLogger(__name__)

# Match the model string already used by chat_service.py so the team has one
# Claude version to reason about. Override per-call via the backend constructor;
# Opus (`claude-opus-4-7`) is the upgrade lever for the flagship reasoning moment.
DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096


# ── LLM backend seam ────────────────────────────────────────────


class LLMBackend(Protocol):
    """Minimal text-completion seam. Claude now; Ollama-swappable later."""

    @property
    def model_id(self) -> str:
        """Identifier recorded for provenance (passport / trace)."""
        ...

    def complete(self, system: str, user: str) -> str:
        """Return the model's raw text response to a single user turn."""
        ...


class ClaudeBackend:
    """Hosted Claude via the Anthropic SDK (already a project dependency).

    `anthropic` is imported lazily inside `complete` so this module stays
    importable in dependency-light environments (tests, AST tooling) — the
    same pattern chat_service.py uses.
    """

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        import anthropic

        self._model = model
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._client = anthropic.Anthropic(api_key=self._api_key) if self._api_key else None

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def complete(self, system: str, user: str) -> str:
        import anthropic

        client = self._client or anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text.strip() if response.content else ""


class CannedBackend:
    """Deterministic offline fallback — equal-weights the candidates.

    Keeps the endpoint demoable with no API key and gives the parser a stable
    fixture in tests. Mirrors chat_service.py's canned-response degradation.
    The rationale text is explicit that this is a fallback so it never
    masquerades as model reasoning in a trace.
    """

    model_id = "canned-fallback"

    def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        ids = re.findall(r'"strategy_id"\s*:\s*"([0-9a-f]+)"', user)
        if not ids:
            ids = re.findall(r"\bid=([0-9a-f]{8,})", user)
        ids = ids[:4] or ["__none__"]
        w = round(1.0 / len(ids), 4)
        selected = [
            {
                "strategy_id": sid,
                "weight": w,
                "rationale": "Equal-weight fallback (no LLM backend available).",
                "paper_citation": "",
            }
            for sid in ids
        ]
        return json.dumps(
            {
                "selected": selected,
                "overall_reasoning": (
                    "Offline fallback: equal-weighted the risk-profile-eligible "
                    "library. Not model reasoning — connect ANTHROPIC_API_KEY for "
                    "a real paper-grounded construction."
                ),
                "risk_notes": "Fallback allocation; downstream guardrail still applies.",
            }
        )


# ── Output artifact (the seam Step 2 / Step 3 consume) ──────────


@dataclass(frozen=True)
class StrategySelection:
    """One strategy Claude chose, with its rationale and provenance."""

    strategy_id: str
    weight: float  # Raw model-proposed fraction; guardrail (Step 2) normalizes.
    rationale: str
    paper_citation: str = ""


@dataclass
class ArchitectProposal:
    """A complete strategy-construction proposal.

    Pre-guardrail: weights are the model's raw suggestion and need not sum to
    1.0 — `services` Step 2 normalizes/caps/applies the USYC floor. Carries the
    LLM id so the passport (`extraction_llm`) and reasoning trace can record
    provenance honestly.
    """

    intent: str
    risk_profile: str
    capital_usdc: float
    regime: str | None
    selected: list[StrategySelection]
    overall_reasoning: str
    risk_notes: str
    model_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def strategies_referenced(self) -> list[str]:
        """Strategy IDs, for `ReasoningTrace.strategies_referenced` (Step 3)."""
        return [s.strategy_id for s in self.selected]

    @property
    def raw_weights(self) -> dict[str, float]:
        """strategy_id → raw proposed weight, for the Step 2 guardrail."""
        return {s.strategy_id: s.weight for s in self.selected}


# ── Prompt construction ─────────────────────────────────────────


_SYSTEM_PROMPT = """You are Archimedes, an AI portfolio architect. You construct \
portfolios from a curated library of strategies, each grounded in a peer-reviewed \
quantitative-finance paper.

Hard rules:
- Choose ONLY from the candidate strategies provided. Never invent a strategy or \
a strategy_id. If none fit, return an empty selection and say why.
- Backtests for these strategies are NOT yet evaluated in this build. Do NOT \
invent Sharpe ratios, returns, or backtest numbers. Reason from the paper \
methodology and the user's stated goal, and say plainly that empirical \
validation is pending.
- Never promise or forecast returns. Frame everything in terms of process, \
methodology, and the risk profile.
- Respect the risk profile's USYC (cash-yield) floor and ceiling.
- Weights are fractions in [0, 1]. They need not sum to 1 — a downstream \
deterministic guardrail normalizes, caps per-strategy exposure, and enforces \
the USYC floor. Propose your intended relative emphasis.

Output STRICT JSON ONLY (no prose, no markdown fences), exactly this schema:
{
  "selected": [
    {"strategy_id": "<id from candidates>", "weight": <float 0..1>,
     "rationale": "<why this fits the user's intent and risk profile>",
     "paper_citation": "<author year — title>"}
  ],
  "overall_reasoning": "<the portfolio thesis, in plain language, honest about \
what is and isn't yet validated>",
  "risk_notes": "<key risks and the selection-bias caveat>"
}"""


def _serialize_strategy(s: Strategy) -> dict:
    """Passport-faithful view for the model. Backtest fields intentionally
    absent — they are not computed yet and the model is told not to invent."""
    return {
        "strategy_id": s.id,
        "paper_title": s.paper_title,
        "paper_authors": s.paper_authors,
        "paper_year": s.paper_year,
        "paper_venue": s.paper_venue,
        "methodology_summary": s.methodology_summary,
        "asset_universe": s.asset_universe,
        "risk_profiles": s.risk_profiles,
        "position_sizing": s.position_sizing.value,
        "rebalance_frequency": s.rebalance_frequency.value,
        "paper_grounded": s.is_paper_grounded,
        "backtest_status": "not_yet_evaluated",
    }


def _build_user_prompt(
    intent: str,
    risk_profile: RiskProfile,
    capital_usdc: float,
    regime: str | None,
    candidates: list[Strategy],
) -> str:
    params = RISK_PROFILE_PARAMS[risk_profile]
    payload = {
        "user_intent": intent,
        "risk_profile": risk_profile.value,
        "risk_profile_params": params,
        "capital_usdc": capital_usdc,
        "current_regime": regime or "unknown (regime detection not yet wired)",
        "candidate_strategies": [_serialize_strategy(s) for s in candidates],
    }
    return json.dumps(payload, indent=2)


# ── Robust JSON extraction ──────────────────────────────────────


def extract_json(text: str) -> dict:
    """Pull the first balanced JSON object out of an LLM response.

    Tolerates ```json fences and surrounding prose. Raises ValueError if no
    parseable object is found so the caller can degrade explicitly rather
    than silently shipping an empty portfolio.
    """
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            c = cleaned[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = cleaned.find("{", start + 1)
    raise ValueError("no parseable JSON object in LLM response")


# ── The architect ───────────────────────────────────────────────


class StrategyArchitect:
    """Turns a free-text request into a paper-grounded strategy proposal.

    Owner: Dan. Pure service — no FastAPI, no on-chain. Wired into a route
    in Step 4; the guardrail (Step 2) and trace (Step 3) consume
    `ArchitectProposal`.
    """

    def __init__(
        self,
        provider: LocalStrategyProvider | None = None,
        backend: LLMBackend | None = None,
    ) -> None:
        self._provider = provider or default_provider()
        self._backend = backend or default_backend()

    def _candidates(self, risk_profile: RiskProfile) -> list[Strategy]:
        scoped = self._provider.get_strategies_for_risk_profile(risk_profile.value)
        if scoped:
            return scoped
        # No profile-tagged strategies (e.g. sparse library): fall back to the
        # whole library rather than returning nothing, and let the model judge.
        logger.info(
            "no strategies tagged for risk_profile=%s; offering full library",
            risk_profile.value,
        )
        return self._provider.list_strategies()

    def propose(
        self,
        intent: str,
        risk_profile: RiskProfile | str,
        capital_usdc: float,
        regime: str | None = None,
    ) -> ArchitectProposal:
        if isinstance(risk_profile, str):
            risk_profile = RiskProfile(risk_profile)

        candidates = self._candidates(risk_profile)
        valid_ids = {s.id for s in candidates}

        system = _SYSTEM_PROMPT
        user = _build_user_prompt(
            intent, risk_profile, capital_usdc, regime, candidates
        )

        raw = self._backend.complete(system, user)
        try:
            parsed = extract_json(raw)
        except ValueError:
            logger.warning("architect: unparseable LLM output; empty proposal")
            return ArchitectProposal(
                intent=intent,
                risk_profile=risk_profile.value,
                capital_usdc=capital_usdc,
                regime=regime,
                selected=[],
                overall_reasoning=(
                    "Could not parse a valid construction from the model. No "
                    "allocation proposed — safer than shipping a guess."
                ),
                risk_notes="Model output was not valid JSON.",
                model_id=self._backend.model_id,
            )

        selected: list[StrategySelection] = []
        for item in parsed.get("selected", []):
            sid = str(item.get("strategy_id", ""))
            if sid not in valid_ids:
                # Anti-hallucination: drop any id not in the offered candidates.
                logger.warning("architect: dropping unknown strategy_id %r", sid)
                continue
            try:
                weight = float(item.get("weight", 0.0))
            except (TypeError, ValueError):
                weight = 0.0
            weight = max(0.0, min(1.0, weight))  # sanity clamp; Step 2 normalizes
            selected.append(
                StrategySelection(
                    strategy_id=sid,
                    weight=weight,
                    rationale=str(item.get("rationale", "")).strip(),
                    paper_citation=str(item.get("paper_citation", "")).strip(),
                )
            )

        return ArchitectProposal(
            intent=intent,
            risk_profile=risk_profile.value,
            capital_usdc=capital_usdc,
            regime=regime,
            selected=selected,
            overall_reasoning=str(parsed.get("overall_reasoning", "")).strip(),
            risk_notes=str(parsed.get("risk_notes", "")).strip(),
            model_id=self._backend.model_id,
        )


def default_backend() -> LLMBackend:
    """Hosted Claude when a key is present; canned fallback otherwise."""
    claude = ClaudeBackend()
    if claude.available:
        return claude
    logger.warning(
        "ANTHROPIC_API_KEY not set — strategy architect using canned fallback"
    )
    return CannedBackend()


def default_architect() -> StrategyArchitect:
    """Factory mirroring `default_provider()`. Used by the Step 4 route."""
    return StrategyArchitect()
