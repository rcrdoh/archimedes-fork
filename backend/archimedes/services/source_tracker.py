"""Source Tracking — Xia et al. 2026 § 4.3.

Every agent decision trace records the content hashes of papers it consulted,
binding the decision to a specific, verifiable corpus snapshot.

This module provides helpers for:
  - Building ``consulted_paper_hashes`` lists from paper dicts.
  - Verifying that claimed source papers exist in the corpus.

Reference: Xia et al. 2026 (arxiv 2605.19337), § 4.3.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_consulted_hashes(papers: list[dict[str, Any]]) -> list[str]:
    """Extract a sorted list of ``{arxiv_id}:{content_hash}`` strings.

    Parameters
    ----------
    papers : list[dict]
        Paper dicts with ``arxiv_id`` and optionally ``content_hash``
        or ``pdf_sha256`` fields.

    Returns
    -------
    list[str]
        Sorted list of ``arxiv_id:hash`` strings for deterministic ordering.
    """
    entries: list[str] = []
    for p in papers:
        arxiv_id = p.get("arxiv_id", "")
        content_hash = p.get("content_hash") or p.get("pdf_sha256") or ""
        if arxiv_id:
            entries.append(f"{arxiv_id}:{content_hash}")
    return sorted(entries)


def verify_source_papers(
    consulted_hashes: list[str],
    corpus: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify that all consulted papers exist in the current corpus.

    Parameters
    ----------
    consulted_hashes : list[str]
        ``arxiv_id:hash`` strings from a trace.
    corpus : list[dict]
        Current paper corpus dicts.

    Returns
    -------
    dict
        ``{"verified": bool, "missing": list[str], "hash_mismatch": list[str]}``
    """
    corpus_by_id: dict[str, str] = {}
    for p in corpus:
        aid = p.get("arxiv_id", "")
        ch = p.get("content_hash") or p.get("pdf_sha256") or ""
        if aid:
            corpus_by_id[aid] = ch

    missing: list[str] = []
    hash_mismatch: list[str] = []

    for entry in consulted_hashes:
        parts = entry.split(":", 1)
        arxiv_id = parts[0]
        claimed_hash = parts[1] if len(parts) > 1 else ""

        if arxiv_id not in corpus_by_id:
            missing.append(arxiv_id)
        elif claimed_hash and corpus_by_id[arxiv_id] != claimed_hash:
            hash_mismatch.append(arxiv_id)

    return {
        "verified": len(missing) == 0 and len(hash_mismatch) == 0,
        "missing": missing,
        "hash_mismatch": hash_mismatch,
    }
