"""PaperRef — a single paper reference in a strategy passport.

Fusion strategies synthesize from N papers; curated strategies reference 1.
Both use the same PaperRef type so the passport shape is fusion-native.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PaperRef:
    """Reference to a single paper backing (or contributing to) a strategy.

    Attributes
    ----------
    arxiv_id : str | None
        e.g. ``"2509.11420"``.  ``None`` for non-arxiv papers.
    title : str
        Full paper title.
    authors : list[str]
        Author list (up to the first N; ``et al.`` in UI when truncated).
    doi : str | None
        Digital Object Identifier, e.g. ``"10.3905/jwm.2007.674809"``.
    venue : str | None
        Journal / conference / ``"arxiv only"``.
    year : int | None
        Publication year.
    citation_count : int | None
        Snapshot at curation time.
    contribution : str | None
        For fusion strategies — what this paper contributed to the synthesis.
        ``None`` for single-paper curated strategies.
    """

    arxiv_id: str | None = None
    title: str = ""
    authors: list[str] = field(default_factory=list)
    doi: str | None = None
    venue: str | None = None
    year: int | None = None
    citation_count: int | None = None
    contribution: str | None = None
