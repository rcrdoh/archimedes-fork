"""Paper / corpus browser endpoints — /api/papers/*."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query

from archimedes.db import get_session
from archimedes.services.corpus_categories import label_for as _category_label

logger = logging.getLogger(__name__)

papers_router = APIRouter(prefix="/api/papers", tags=["papers"])


@papers_router.get("/")
async def list_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    search: str | None = None,
    processed_only: bool = Query(
        True,
        description=(
            "If true (default), only return papers the KB pipeline has fully "
            "processed (i.e. have a non-null cluster_id from BERTopic). The "
            "papers table holds 10K rows of arxiv metadata but the KB pipeline "
            "has only run on ~1K so far; setting this to false reveals the raw "
            "metadata-only rows that have no embeddings/topic labels/triples."
        ),
    ),
):
    """Paginated corpus catalog. DB-backed with file fallback.

    Defaults to ``processed_only=true`` so the catalog reflects what the
    user can actually inspect end-to-end (paper detail + topic cluster +
    similarity neighbors). The raw 10K-row metadata table is preserved
    as a superset; the runner-state endpoint reports the processed
    paper_count separately.
    """
    from archimedes.models.corpus_store import PaperRecord

    with get_session() as session:
        query = session.query(PaperRecord)

        if processed_only:
            query = query.filter(PaperRecord.cluster_id.isnot(None))
        if category:
            query = query.filter(PaperRecord.categories.contains(category))
        if search:
            pattern = f"%{search}%"
            query = query.filter((PaperRecord.title.ilike(pattern)) | (PaperRecord.abstract.ilike(pattern)))

        total = query.count()
        rows = query.order_by(PaperRecord.published.desc()).offset((page - 1) * page_size).limit(page_size).all()

        papers = [
            {
                "arxiv_id": r.arxiv_id,
                "title": r.title,
                "authors": json.loads(r.authors) if r.authors else [],
                "primary_category": r.primary_category,
                "category_label": _category_label(r.primary_category),
                "categories": json.loads(r.categories) if r.categories else [],
                "published": r.published,
                "abstract": r.abstract[:200] + "..." if len(r.abstract) > 200 else r.abstract,
            }
            for r in rows
        ]

    if total == 0 and not category and not search:
        from archimedes.agents.strategy_fusion import load_corpus

        corpus = load_corpus()
        all_papers = [
            {
                "arxiv_id": p.arxiv_id,
                "title": p.title,
                "authors": list(getattr(p, "authors", []) or []),
                "primary_category": p.primary_category,
                "category_label": _category_label(p.primary_category),
                "categories": list(p.categories),
                "published": p.published,
                "abstract": p.abstract[:200] + "..." if len(p.abstract) > 200 else p.abstract,
            }
            for p in corpus
        ]
        total = len(all_papers)
        start = (page - 1) * page_size
        papers = all_papers[start : start + page_size]

    return {"total": total, "page": page, "page_size": page_size, "papers": papers}


@papers_router.get("/{arxiv_id}")
async def get_paper(arxiv_id: str):
    """Single paper detail + citing strategies (bidirectional provenance)."""
    from fastapi import HTTPException

    from archimedes.models.corpus_store import PaperRecord
    from archimedes.models.strategy_store import strategies_by_paper

    with get_session() as session:
        record = session.query(PaperRecord).filter(PaperRecord.arxiv_id == arxiv_id).first()

    if record is not None:
        citing_strategies = []
        try:
            with get_session() as session:
                records = strategies_by_paper(session, arxiv_id)
                citing_strategies = [
                    {"id": r.id, "name": r.strategy_name, "status": r.status, "method": r.generation_method}
                    for r in records
                ]
        except Exception:
            logger.debug("citing-strategies lookup failed", exc_info=True)

        return {
            "arxiv_id": record.arxiv_id,
            "title": record.title,
            "authors": json.loads(record.authors) if record.authors else [],
            "primary_category": record.primary_category,
            "category_label": _category_label(record.primary_category),
            "categories": json.loads(record.categories) if record.categories else [],
            "published": record.published,
            "abstract": record.abstract,
            "pdf_url": record.pdf_url,
            "source": record.source,
            "citing_strategies": citing_strategies,
        }

    from archimedes.agents.strategy_fusion import load_corpus

    corpus = load_corpus()
    paper = next((p for p in corpus if p.arxiv_id == arxiv_id), None)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    citing_strategies = []
    try:
        with get_session() as session:
            records = strategies_by_paper(session, arxiv_id)
            citing_strategies = [
                {"id": r.id, "name": r.strategy_name, "status": r.status, "method": r.generation_method}
                for r in records
            ]
    except Exception:
        logger.debug("citing-strategies lookup failed", exc_info=True)

    return {
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "primary_category": paper.primary_category,
        "category_label": _category_label(paper.primary_category),
        "categories": list(paper.categories),
        "published": paper.published,
        "abstract": paper.abstract,
        "citing_strategies": citing_strategies,
    }


# Legacy /corpus/overview, /corpus/graph, /corpus/kg endpoints deleted
# per CLAUDE.md + Issue #382. Canonical corpus endpoints are at /api/corpus/*.
