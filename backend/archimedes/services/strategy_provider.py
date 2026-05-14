"""Strategy provider service — Dan's implementation of `IStrategyProvider`.

Source of truth is the analytics-engine strategy directory
(`analytics-engine/strategies/*.py`). Each file is a self-describing
paper-grounded strategy: a `bt.Strategy` subclass plus module-level
constants that encode the passport metadata.

The provider does not import backtrader. It reads the metadata via AST so
the backend can list and serve strategies without pulling the backtest
engine into the API process.

References:
- `docs/specs/component-interfaces-spec.md` — Dan owns IStrategyProvider
- `docs/specs/strategy-passport-spec.md` — passport schema
- `analytics-engine/src/archimedes_analytics_engine/strategy_loader.py` —
  parallel runtime loader used by the backtest engine
"""

from __future__ import annotations

import ast
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from archimedes.models.strategy import (
    PositionSizing,
    RebalanceFrequency,
    Strategy,
    StrategyStatus,
)

logger = logging.getLogger(__name__)


# Constants the analytics-engine strategy_loader recognizes plus passport
# extensions specific to the provider. Anything not present is treated as
# missing rather than an error — strategies remain valid with partial
# metadata.
_METADATA_KEYS: tuple[str, ...] = (
    "PAPER_ARXIV_ID",
    "PAPER_TITLE",
    "PAPER_AUTHORS",
    "PAPER_VENUE",
    "PAPER_YEAR",
    "PAPER_DOI",
    "PAPER_CITATION_COUNT",
    "METHODOLOGY_SUMMARY",
    "METHODOLOGY_TEXT",
    "PAPER_CLAIMED_SHARPE",
    "PAPER_CLAIMED_CAGR",
    "PAPER_CLAIMED_MAX_DD",
    "ASSET_UNIVERSE",
    "POSITION_SIZING",
    "REBALANCE_FREQUENCY",
    "RISK_PROFILES",
    "RISK_CONSTRAINTS",
    "CURATOR_WALLET",
    "CURATOR_NOTE",
    "EXTRACTION_LLM",
)


# Keyword heuristic for risk profile inference when a strategy file does
# not declare RISK_PROFILES explicitly. Lowercased substring match.
_RISK_PROFILE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "conservative": ("mean reversion", "low-vol", "bond", "defensive", "yield"),
    "moderate": ("trend", "balanced", "factor", "value", "carry"),
    "aggressive": ("momentum", "high-conviction", "concentrated", "growth"),
    "hyper_risky": ("leveraged", "leverage", "sector concentration", "volatility short"),
}


def _read_module_constants(path: Path) -> dict[str, Any]:
    """Parse a Python file and return its module-level constant assignments.

    Uses `ast.literal_eval` on right-hand sides so backtrader (or any other
    import) is never executed. Only literals of the standard JSON-ish shape
    are recoverable; anything more exotic is silently skipped.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    out: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is None:
                continue  # bare annotation, no value to read
            targets = [node.target]
            value_node = node.value
        else:
            continue
        for target in targets:
            if target.id not in _METADATA_KEYS:
                continue
            try:
                out[target.id] = ast.literal_eval(value_node)
            except (ValueError, SyntaxError) as exc:
                logger.debug("skip non-literal %s in %s: %s", target.id, path, exc)
    return out


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_methodology(metadata: dict[str, Any]) -> str:
    text = metadata.get("METHODOLOGY_TEXT") or metadata.get("METHODOLOGY_SUMMARY") or ""
    return str(text).strip()


def _methodology_hash(metadata: dict[str, Any]) -> str:
    canonical = _canonical_methodology(metadata)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _strategy_id(metadata: dict[str, Any], code_hash: str) -> str:
    """Deterministic ID: hash of arxiv_id (or DOI, or title) + methodology hash."""
    paper_key = (
        metadata.get("PAPER_ARXIV_ID")
        or metadata.get("PAPER_DOI")
        or metadata.get("PAPER_TITLE")
        or code_hash
    )
    payload = f"{paper_key}|{_methodology_hash(metadata)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


def _infer_risk_profiles(methodology_summary: str) -> list[str]:
    text = methodology_summary.lower()
    matched = [
        profile
        for profile, keywords in _RISK_PROFILE_KEYWORDS.items()
        if any(kw in text for kw in keywords)
    ]
    return matched or ["moderate"]


def _to_strategy(path: Path, metadata: dict[str, Any], code_hash: str) -> Strategy:
    methodology_summary = str(metadata.get("METHODOLOGY_SUMMARY") or metadata.get("METHODOLOGY_TEXT") or "")
    methodology_text = metadata.get("METHODOLOGY_TEXT")
    risk_profiles = metadata.get("RISK_PROFILES") or _infer_risk_profiles(methodology_summary)

    position_sizing_raw = str(metadata.get("POSITION_SIZING") or "equal_weight").lower()
    try:
        position_sizing = PositionSizing(position_sizing_raw)
    except ValueError:
        logger.warning("unknown POSITION_SIZING=%s in %s, defaulting", position_sizing_raw, path)
        position_sizing = PositionSizing.EQUAL_WEIGHT

    rebalance_raw = str(metadata.get("REBALANCE_FREQUENCY") or "weekly").lower()
    try:
        rebalance_frequency = RebalanceFrequency(rebalance_raw)
    except ValueError:
        logger.warning("unknown REBALANCE_FREQUENCY=%s in %s, defaulting", rebalance_raw, path)
        rebalance_frequency = RebalanceFrequency.WEEKLY

    paper_year = metadata.get("PAPER_YEAR")
    if paper_year is not None:
        paper_year = int(paper_year)

    return Strategy(
        id=_strategy_id(metadata, code_hash),
        paper_arxiv_id=str(metadata.get("PAPER_ARXIV_ID") or ""),
        paper_title=str(metadata.get("PAPER_TITLE") or path.stem),
        paper_authors=list(metadata.get("PAPER_AUTHORS") or []),
        methodology_summary=methodology_summary,
        methodology_text=methodology_text if isinstance(methodology_text, str) else None,
        asset_universe=list(metadata.get("ASSET_UNIVERSE") or []),
        signals=[],
        position_sizing=position_sizing,
        rebalance_frequency=rebalance_frequency,
        risk_constraints=dict(metadata.get("RISK_CONSTRAINTS") or {}) | {"risk_profiles": risk_profiles},
        status=StrategyStatus.CANDIDATE,
        extraction_reasoning="",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        paper_venue=metadata.get("PAPER_VENUE"),
        paper_year=paper_year,
        paper_doi=metadata.get("PAPER_DOI"),
        paper_citation_count=metadata.get("PAPER_CITATION_COUNT"),
        methodology_hash=_methodology_hash(metadata),
        extraction_llm=metadata.get("EXTRACTION_LLM"),  # None for hand-curated
        extraction_prompt_hash=None,
        curator_wallet=metadata.get("CURATOR_WALLET"),
        curator_validation_at=None,
        curator_note=metadata.get("CURATOR_NOTE"),
        strategy_code_path=str(path),
        strategy_code_hash=code_hash,
        on_chain_registration_tx=None,
    )


class LocalStrategyProvider:
    """File-system-backed `IStrategyProvider`.

    Owner: Dan. Wired into the agent orchestrator via dependency injection
    in `archimedes.api.routes`.

    Reload semantics: strategies are loaded eagerly on construction and
    cached in-memory. Call `refresh()` to re-scan the directory after a
    new strategy file lands.
    """

    def __init__(self, strategies_dir: Path) -> None:
        self._strategies_dir = strategies_dir
        self._strategies: dict[str, Strategy] = {}
        self.refresh()

    def refresh(self) -> int:
        """Re-scan the strategies directory. Returns the loaded count."""
        if not self._strategies_dir.exists():
            logger.warning("strategies dir not found: %s", self._strategies_dir)
            self._strategies = {}
            return 0

        loaded: dict[str, Strategy] = {}
        for path in sorted(self._strategies_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                metadata = _read_module_constants(path)
                if not metadata.get("PAPER_TITLE"):
                    logger.debug("no PAPER_TITLE in %s, skipping", path)
                    continue
                code_hash = _hash_file(path)
                strategy = _to_strategy(path, metadata, code_hash)
                loaded[strategy.id] = strategy
            except Exception as exc:  # noqa: BLE001 — defensive on startup
                logger.exception("failed to load strategy %s: %s", path, exc)
        self._strategies = loaded
        logger.info("loaded %d strategies from %s", len(loaded), self._strategies_dir)
        return len(loaded)

    # ── IStrategyProvider ───────────────────────────────────

    def list_strategies(
        self,
        status: StrategyStatus | None = None,
        asset_universe: list[str] | None = None,
    ) -> list[Strategy]:
        results = list(self._strategies.values())
        if status is not None:
            results = [s for s in results if s.status == status]
        if asset_universe:
            wanted = set(asset_universe)
            results = [s for s in results if wanted.intersection(s.asset_universe)]
        return results

    def get_strategy(self, strategy_id: str) -> Strategy | None:
        return self._strategies.get(strategy_id)

    def get_strategies_for_risk_profile(self, risk_profile_name: str) -> list[Strategy]:
        wanted = risk_profile_name.lower()
        return [
            s
            for s in self._strategies.values()
            if wanted in (s.risk_constraints.get("risk_profiles") or [])
        ]

    def extract_from_paper(self, arxiv_id: str) -> Strategy | None:
        """Demo-feature stub. Real implementation arrives in the arxiv pipeline.

        Returns None for now. The pipeline will live in
        `archimedes.services.arxiv_pipeline` and use the KnowledgeBase
        `extract.py` pattern (PyMuPDF cache) plus a Claude API call to
        synthesize the methodology, then write a new `.py` file into the
        analytics-engine strategies directory and call `self.refresh()`.
        """
        logger.info("extract_from_paper(%s): not yet implemented", arxiv_id)
        return None


def default_provider(repo_root: Path | None = None) -> LocalStrategyProvider:
    """Construct a provider pointing at `analytics-engine/strategies/`.

    `repo_root` defaults to four levels up from this file (the archimedes
    repo root). Override for tests.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[3]
    return LocalStrategyProvider(repo_root / "analytics-engine" / "strategies")
