# Progress

## Status
In Progress — Issue #174 (AMM health endpoint + agent_runner VaultFactory poll) complete. Deployed to main.

## Tasks

### Completed (this session)
- **#174** — `/api/health/amm` endpoint reporting per-pool AMM liquidity (symbol, status, liquidity_usdc, oracle_price, reserves). `agent_runner._discover_new_vaults()` polls VaultFactory.getAllVaults() each tick to auto-discover user-created vaults. 3 new tests.

### Completed (prior sessions)
- **#172** — WelcomeProfileModal + personalized header
- **#167** — Generate page single input + backend auto-route
- **#177** — Nginx security headers
- **#178** — CORS lockdown
- **#166** — Landing sidebar parity + CTA differentiation
- **#169** — Corpus default Catalog tab + plain-English labels
- **#170** — Reasoning verify arcscan enhancement
- **#171** — Portfolio traces honesty
- **#173** — Agents subpackage refactor

## Files Changed (this session — Issue #174)
- `backend/archimedes/api/schemas.py` — Added `AMMPoolHealth` + `AMMHealthResponse` Pydantic models
- `backend/archimedes/api/agent_routes.py` — Added `GET /api/agent/health/amm` endpoint
- `backend/archimedes/chain/agent_runner.py` — Added `_known_vaults` set + `_discover_new_vaults()` method for VaultFactory polling
- `backend/tests/test_api_routes.py` — Added 3 tests: amm_health_endpoint, amm_health_returns_all_synth_pools, amm_health_pool_status_values

## Validation
- `pytest -q -k "amm or health or Agent"` → 7 passed
- `pytest -q -k "not user_profile_privacy and not test_user_routes"` → 378 passed, 0 failures
- AC: `grep -n "VaultFactory.*getAllVaults\|_discover_new_vaults" backend/archimedes/chain/agent_runner.py` → 4 matches
- AC: `grep -n "/health/amm" backend/archimedes/api/agent_routes.py` → 1 match
- AC: Schema includes `["last_update","liquidity_usdc","oracle_price","symbol","status","reserve_token","reserve_usdc"]`
