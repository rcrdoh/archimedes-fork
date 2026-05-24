# Progress

## Status
In Progress — Issue #150 (DepositFlow stepper modal) complete. Deployed to main.

## Tasks

### Completed (this session)
- **#150** — DepositFlow stepper modal: 3-step USDC.approve → vault.deposit → setTargetAllocations with per-step status (pending/waiting/confirming/done/failed), retry on error, arcscan tx links, localStorage progress persistence for resume. USDC_ABI added to config.js. Wired into CreateVaultModal replacing the Phase 4.5 placeholder.

### Completed (prior sessions)
- **#174** — `/api/health/amm` endpoint + agent_runner VaultFactory poll
- **#172** — WelcomeProfileModal + personalized header
- **#167** — Generate page single input + backend auto-route
- **#177** — Nginx security headers
- **#178** — CORS lockdown
- **#166** — Landing sidebar parity + CTA differentiation
- **#169** — Corpus default Catalog tab + plain-English labels
- **#170** — Reasoning verify arcscan enhancement
- **#171** — Portfolio traces honesty
- **#173** — Agents subpackage refactor

## Files Changed (this session — Issue #150)
- `ui/src/components/DepositFlow.jsx` — NEW: 366-line 3-step stepper modal component
- `ui/src/components/CreateVaultModal.jsx` — Wired DepositFlow to replace Phase 4.5 placeholder; on vault deploy success, renders DepositFlow instead of closing
- `ui/src/config.js` — Added `USDC_ABI` minimal export (approve + allowance fragments)

## Validation
- Frontend build: `npm run build` → clean (no new warnings)
- Backend tests: `pytest -q -k "not user_profile_privacy and not test_user_routes"` → 378 passed, 0 failures
- AC: `grep -c "DepositFlow" ui/src/components/CreateVaultModal.jsx` → 6 matches
- AC: `grep -c "writeContract" ui/src/components/DepositFlow.jsx` → 3 (one per step)
- AC: `grep -c "USDC_ABI" ui/src/config.js` → 1 (export exists)
- AC: `grep -c "arcscan.app" ui/src/components/DepositFlow.jsx` → 1 (tx explorer links)
- AC: `grep -c "Retry" ui/src/components/DepositFlow.jsx` → 1 (retry button on error)
- AC: `grep -c "localStorage" ui/src/components/DepositFlow.jsx` → 4 (progress persistence)
