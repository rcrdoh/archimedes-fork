"""Paper / corpus browser endpoints — /api/papers/*."""

from __future__ import annotations

import json

from fastapi import APIRouter, Query

from archimedes.db import get_session
from archimedes.services.corpus_categories import label_for as _category_label

papers_router = APIRouter(prefix="/api/papers", tags=["papers"])


@papers_router.get("/")
async def list_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    search: str | None = None,
):
    """Paginated corpus catalog. DB-backed with file fallback."""
    from archimedes.models.corpus_store import PaperRecord

    with get_session() as session:
        query = session.query(PaperRecord)

        if category:
            query = query.filter(PaperRecord.categories.contains(category))
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                (PaperRecord.title.ilike(pattern)) | (PaperRecord.abstract.ilike(pattern))
            )

        total = query.count()
        rows = (
            query.order_by(PaperRecord.published.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        papers = [
            {
                "arxiv_id": r.arxiv_id,
                "title": r.title,
                "primary_category": r.primary_category,
                "category_label": _category_label(r.primary_category),
                "categories": json.loads(r.categories) if r.categories else [],
                "published": r.published,
                "abstract": r.abstract[:200] + "..." if len(r.abstract) > 200 else r.abstract,
            }
            for r in rows
        ]

    if total == 0 and not category and not search:
        from archimedes.services.strategy_fusion import load_corpus
        corpus = load_corpus()
        all_papers = [
            {
                "arxiv_id": p.arxiv_id,
                "title": p.title,
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
        papers = all_papers[start:start + page_size]

    return {"total": total, "page": page, "page_size": page_size, "papers": papers}


@papers_router.get("/{arxiv_id}")
async def get_paper(arxiv_id: str):
    """Single paper detail + citing strategies (bidirectional provenance)."""
    from archimedes.models.corpus_store import PaperRecord
    from archimedes.models.strategy_store import strategies_by_paper
    from fastapi import HTTPException

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
            pass

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

    from archimedes.services.strategy_fusion import load_corpus
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
        pass

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


# ── Corpus Overview ──────────────────────────────────────────────


@papers_router.get("/corpus/overview")
async def get_corpus_overview():
    """High-level library breakdown: category mix, year distribution, totals."""
    from collections import Counter
    from archimedes.models.corpus_store import PaperRecord
    from sqlalchemy import func

    with get_session() as session:
        total = session.query(func.count(PaperRecord.arxiv_id)).scalar() or 0

        if total > 0:
            cat_rows = (
                session.query(PaperRecord.primary_category, func.count(PaperRecord.arxiv_id))
                .group_by(PaperRecord.primary_category)
                .order_by(func.count(PaperRecord.arxiv_id).desc())
                .all()
            )
            category_counts = Counter()
            for cat, cnt in cat_rows:
                category_counts[cat] = cnt

            year_rows = (
                session.query(
                    func.substr(PaperRecord.published, 1, 4).label("year"),
                    func.count(PaperRecord.arxiv_id),
                )
                .filter(PaperRecord.published != "")
                .group_by("year")
                .order_by("year")
                .all()
            )
            year_dist = [(yr, cnt) for yr, cnt in year_rows if yr and yr.isdigit()]

            return {
                "total_papers": total,
                "source": "database",
                "categories": [
                    {"name": cat, "label": _category_label(cat), "count": cnt}
                    for cat, cnt in category_counts.most_common(20)
                ],
                "year_distribution": [{"year": yr, "count": cnt} for yr, cnt in year_dist],
            }

    from archimedes.services.strategy_fusion import load_corpus

    corpus = load_corpus()
    category_counts: Counter = Counter()
    year_counts: Counter = Counter()
    for p in corpus:
        category_counts[p.primary_category] += 1
        for c in p.categories:
            category_counts[c] += 1
        if p.published:
            year = p.published[:4]
            if year.isdigit():
                year_counts[year] += 1

    top_categories = category_counts.most_common(20)
    year_dist = sorted(year_counts.items())

    return {
        "total_papers": len(corpus),
        "source": "file",
        "categories": [
            {"name": cat, "label": _category_label(cat), "count": cnt}
            for cat, cnt in top_categories
        ],
        "year_distribution": [{"year": yr, "count": cnt} for yr, cnt in year_dist],
    }


@papers_router.get("/corpus/graph")
async def get_corpus_graph(
    sample: int = 500,
    lod: int = 1,
):
    """Similarity graph nodes/edges for the corpus."""
    import json as _json
    from collections import defaultdict
    from archimedes.models.corpus_store import PaperRecord
    from sqlalchemy import func

    with get_session() as session:
        total = session.query(func.count(PaperRecord.arxiv_id)).scalar() or 0
        if total == 0:
            return {"status": "empty", "nodes": [], "edges": [], "total_papers": 0}

        papers = (
            session.query(PaperRecord.arxiv_id, PaperRecord.title, PaperRecord.categories, PaperRecord.cluster_id, PaperRecord.topic_label)
            .limit(sample)
            .all()
        )

        nodes = []
        edges = []
        cat_papers = defaultdict(list)

        for p in papers:
            label = p.topic_label or p.primary_category if hasattr(p, 'primary_category') else None
            try:
                cats = _json.loads(p.categories) if p.categories else []
            except (_json.JSONDecodeError, TypeError):
                cats = []
            if not cats:
                cats = ["uncategorized"]

            nodes.append({
                "id": p.arxiv_id,
                "title": p.title[:80] if p.title else p.arxiv_id,
                "cluster": p.cluster_id or cats[0],
                "label": label,
                "categories": cats[:3],
            })

            for c in cats[:3]:
                cat_papers[c].append(p.arxiv_id)

        edge_set = set()
        for cat, pids in cat_papers.items():
            for i in range(min(len(pids), 20)):
                for j in range(i + 1, min(len(pids), 20)):
                    pair = tuple(sorted([pids[i], pids[j]]))
                    if pair not in edge_set:
                        edge_set.add(pair)
                        edges.append({"source": pair[0], "target": pair[1], "weight": 1, "type": "category_cooccurrence"})

        return {
            "status": "metadata_derived",
            "note": "Category co-occurrence graph from metadata. Embedding-based similarity pending KB pipeline port (#101).",
            "total_papers": total,
            "sampled": len(nodes),
            "nodes": nodes,
            "edges": edges[:2000],
        }


@papers_router.get("/corpus/kg")
async def get_corpus_kg(
    entity: str | None = None,
    depth: int = 1,
):
    """Knowledge-graph subgraph filtered by entity."""
    import json as _json
    from collections import defaultdict
    from archimedes.models.corpus_store import PaperRecord
    from sqlalchemy import func, or_

    with get_session() as session:
        total = session.query(func.count(PaperRecord.arxiv_id)).scalar() or 0
        if total == 0:
            return {"status": "empty", "entities": [], "relations": [], "total_papers": 0}

        q = session.query(PaperRecord)
        if entity:
            like = f"%{entity}%"
            q = q.filter(
                or_(
                    PaperRecord.title.ilike(like),
                    PaperRecord.abstract.ilike(like),
                    PaperRecord.authors.ilike(like),
                    PaperRecord.categories.ilike(like),
                )
            )
        papers = q.limit(200).all()

        entities = {}
        relations = []

        for p in papers:
            entities[f"paper:{p.arxiv_id}"] = {
                "type": "paper",
                "id": p.arxiv_id,
                "label": p.title[:100] if p.title else p.arxiv_id,
            }

            try:
                authors = _json.loads(p.authors) if p.authors else []
            except (_json.JSONDecodeError, TypeError):
                authors = []
            for a in authors[:5]:
                a_key = f"author:{a}"
                if a_key not in entities:
                    entities[a_key] = {"type": "author", "id": a, "label": a}
                relations.append({"source": f"paper:{p.arxiv_id}", "target": a_key, "type": "authored_by"})

            try:
                cats = _json.loads(p.categories) if p.categories else []
            except (_json.JSONDecodeError, TypeError):
                cats = []
            for c in cats[:3]:
                c_key = f"category:{c}"
                if c_key not in entities:
                    entities[c_key] = {"type": "category", "id": c, "label": c}
                relations.append({"source": f"paper:{p.arxiv_id}", "target": c_key, "type": "belongs_to"})

        return {
            "status": "metadata_derived",
            "note": "Author/category KG from metadata. Full REBEL/SciSpacy KG pending KB pipeline port (#101).",
            "total_papers": total,
            "filtered": len(papers),
            "entities": list(entities.values()),
            "relations": relations[:2000],
        }
