# Progress

## Status
In Progress

## Tasks
### Completed
- [x] #153 CorpusGraph + CorpusKG frontend components

## Files Changed
- `ui/src/components/CorpusGraph.jsx` (NEW) — Force-directed SPECTER2 similarity graph using react-force-graph-2d
- `ui/src/components/CorpusKG.jsx` (NEW) — Knowledge graph SVG viewer with entity search
- `ui/src/components/CorpusExplorer.jsx` — Replaced inline canvas graph + KGViewer with new components
- `ui/package.json` + `ui/package-lock.json` — Added react-force-graph-2d dependency

## Notes
- CorpusGraph uses `react-force-graph-2d` for interactive force-directed layout
- CorpusKG renders SVG-based entity graph with search filter
- Both components fall back gracefully on 503 / empty data
- No stale "metadata-derived" placeholder text remains in UI
- Frontend build clean, 488 backend tests passing
