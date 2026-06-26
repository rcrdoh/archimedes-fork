"""``docs/asset-universe.md`` is generated from the SSOT and must stay in sync (#757).

Hermetic: pure in-memory render vs the committed file — no DB / Redis / RPC / .env.
"""

from __future__ import annotations

import re
from pathlib import Path

from archimedes.universe import COMPLIANCE_FLAGGED_SINGLE_STOCKS, ON_CHAIN_SYNTHS


def _doc_path() -> Path:
    import archimedes  # backend/archimedes/__init__.py → parents: archimedes, backend, <repo>

    return Path(archimedes.__file__).resolve().parents[2] / "docs" / "asset-universe.md"


def test_asset_universe_doc_is_in_sync() -> None:
    # A SSOT edit that forgets to regenerate the doc fails CI here.
    from archimedes.scripts.gen_asset_universe_doc import render_doc

    committed = _doc_path().read_text(encoding="utf-8")
    assert committed == render_doc(), (
        "docs/asset-universe.md is stale vs the SSOT — regenerate with "
        "`python -m archimedes.scripts.gen_asset_universe_doc`."
    )


def test_asset_universe_doc_lists_every_synth() -> None:
    # Every on-chain synth AND every compliance-held single stock must be documented.
    text = _doc_path().read_text(encoding="utf-8")
    for sym in ON_CHAIN_SYNTHS:
        assert f"`{sym}`" in text, f"on-chain synth {sym} missing from docs/asset-universe.md"
    for sym in COMPLIANCE_FLAGGED_SINGLE_STOCKS:
        assert f"`{sym}`" in text, f"compliance-flagged {sym} missing from docs/asset-universe.md"


def test_on_chain_table_has_exactly_one_row_per_synth() -> None:
    # Stronger than "symbol appears somewhere": the on-chain TABLE must have exactly one
    # row per deploy-eligible synth (guards a symbol appearing only in prose / the
    # compliance list while its table row is missing). Table rows start `| `sXXX` |`;
    # the compliance list renders symbols inline (not as table rows), so it won't match.
    text = _doc_path().read_text(encoding="utf-8")
    rows = re.findall(r"^\| `(s[A-Za-z0-9]+)` \|", text, flags=re.MULTILINE)
    assert set(rows) == set(ON_CHAIN_SYNTHS), (
        f"on-chain table rows != SSOT. only-in-table={sorted(set(rows) - set(ON_CHAIN_SYNTHS))} "
        f"only-in-ssot={sorted(set(ON_CHAIN_SYNTHS) - set(rows))}"
    )
    assert len(rows) == len(set(rows)) == len(ON_CHAIN_SYNTHS), "duplicate or missing table rows"
