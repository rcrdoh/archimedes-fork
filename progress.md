# Progress

## Status
In Progress — Issue #172 (WelcomeProfileModal + personalized header) complete. Deployed to main.

## Tasks

### Completed (this session)
- **#172** — WelcomeProfileModal on first wallet connect + personalized header. All fields optional (display_name, email, interests, attribution, marketing_opt_in). Header shows "Welcome, <name>". Backend: user_profiles table + GET/POST /api/user/profile. Copy: "Your Vaults", "Your Traces", "Your Strategies".
- **#167** — Generate page: single unified form (removed mode picker). Backend `_pick_pipeline()` auto-routes fusion/architect/agent.
- Fix: asset_market_service test ABI path resolution (parents[3]→parents[2]).

### Also Completed (prior sessions)
- **#177** — Nginx security headers
- **#178** — CORS lockdown
- **#166** — Landing sidebar parity + CTA differentiation
- **#169** — Corpus default Catalog tab + plain-English labels
- **#170** — Reasoning verify arcscan enhancement
- **#171** — Portfolio traces honesty
- **#173** — Agents subpackage refactor

## Files Changed (this session)
- `backend/archimedes/models/user_profile.py` — NEW: UserProfile ORM (wallet PK, all optional fields)
- `backend/archimedes/api/user_routes.py` — NEW: GET/POST /api/user/profile router
- `backend/archimedes/api/user_schemas.py` — NEW: Pydantic schemas for profile
- `backend/archimedes/main.py` — wired user_router
- `backend/archimedes/db.py` — import UserProfile model
- `ui/src/components/WelcomeProfileModal.jsx` — NEW: modal with all optional fields + Skip button
- `ui/src/components/Layout.jsx` — personalized "Welcome, <name>" header + modal trigger on first connect
- `ui/src/components/Portfolio.jsx` — copy: "Your Vaults", "Your Traces"
- `ui/src/components/Strategies.jsx` — copy: "Your Strategies"
- `backend/tests/test_user_routes.py` — NEW: 8 tests for user profile CRUD
- `backend/tests/services/test_asset_market_service.py` — fixed ABI path resolution

## Validation
- `pytest -q` → 383 passed, 2 skipped, 0 failures
- `npm run build` → clean
- AC: `curl -s /api/user/profile/<unknown>` → 404 ✓
- AC: `curl -X POST /api/user/profile -d '{...}'` → 200 ✓
- AC: WelcomeProfileModal appears on first wallet connect (localStorage gate)
- AC: Header shows "Welcome, <name>" when display_name set
- AC: "Your strategies", "Your vaults", "Your traces" copy in UI

## Remaining (assigned to t2o2)
- #168 — Explore page real oracle prices
- #174 — /api/health/amm + agent-runner vault poll
- #175 — End-to-end testnet smoke
- #176 — Migrate secrets to AWS SSM
- #179 — Rate limiting (slowapi)
- #180 — Dependabot + secret scanning
- #181 — User-data minimization
- #152–#165 — Track C/E (KB pipeline, passport unification, etc.)
