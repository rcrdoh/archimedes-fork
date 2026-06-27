#!/usr/bin/env python3
"""Top-level wrapper for the asset-universe doc generator.

Exists so the command documented in issue #757 runs exactly as written::

    PYTHONPATH=backend python scripts/gen_asset_universe_doc.py          # write the doc
    PYTHONPATH=backend python scripts/gen_asset_universe_doc.py --check   # exit 1 if stale (CI)

It is a thin delegate to the real generator that lives in the backend package
(``backend/archimedes/scripts/gen_asset_universe_doc.py``); ``PYTHONPATH=backend``
makes ``archimedes`` importable. The module form
``python -m archimedes.scripts.gen_asset_universe_doc`` keeps working too.
"""

from __future__ import annotations

from archimedes.scripts.gen_asset_universe_doc import main

if __name__ == "__main__":
    raise SystemExit(main())
