# Progress

## Status
In Progress — Issue #180 (Dependabot + detect-secrets) complete. Deployed to main.

## Tasks

### Completed (this session)
- **#180** — Dependabot + detect-secrets: `.github/dependabot.yml` (5 ecosystems, weekly), `.pre-commit-config.yaml` (detect-secrets + ruff + hygiene hooks), `.secrets.baseline` (verified false positives), `docs/runbooks/github-security-toggles.md` (3 Settings toggles guide). GitHub vulnerability alerts enabled via API.
- **#162** — regime_tag field on Strategy dataclass (bull/bear/regime_neutral). All 6 curated strategies tagged. Invalid/missing tag raises ValueError. API response includes regime_tag. 20 new tests.
- **#175** — E2E testnet smoke test script: `verify_arc_e2e.py` with --dry-run (prerequisites check, exit 0) and --execute (full 11-step lifecycle). Evidence captured to `docs/runbooks/arc-testnet-e2e-evidence.md` with arcscan links.
- **#179** — Rate limiting via slowapi: generate/start 5/min, profile POST 1/min, public GETs 60/min. Redis-backed, falls back to in-memory. Health + verify exempt. X-RateLimit headers. 402 tests green.
- **#181** — User-data minimization: encrypt email at rest (Fernet), scrub from logs, owner-only API echo. 12 new privacy tests + updated 12 route tests. 402 total tests green.

### Completed (prior sessions)
- **#150** — DepositFlow stepper modal: 3-step USDC.approve → vault.deposit → setTargetAllocations
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

## Files Changed (this session — Issue #180 + #179, #181)
- `backend/archimedes/api/limiter.py` — Shared slowapi Limiter instance (Redis-backed, in-memory fallback, headers_enabled=True)
- `backend/archimedes/main.py` — Registers limiter + 429 handler + health/verify exemptions
- `backend/archimedes/api/generate_routes.py` — 5/min on POST /start
- `backend/archimedes/api/user_routes.py` — 1/min on POST /profile + owner-only echo
- `backend/archimedes/api/traces_routes.py` — Exempt verify endpoint from rate limiting
- `backend/archimedes/api/agent_routes.py` — Exempt AMM health endpoint
- `backend/archimedes/services/email_crypto.py` — NEW: Fernet-based email encrypt/decrypt (env-var key)
- `backend/archimedes/services/log_scrubber.py` — NEW: PII field scrubber for log output
- `backend/requirements.txt` — Added slowapi>=0.1.9
- `backend/tests/test_user_routes.py` — Updated: patch limiter for test runs
- `backend/archimedes/tests/test_user_profile_privacy.py` — Updated: mock request/response for limiter-decorated functions

## Validation
- Backend tests: 402 passed, 0 failed, 2 skipped (pre-existing Redis flakes)
- Email encryption: round-trip verified (Fernet tokens differ from plaintext, decrypt back correctly)
- Log scrubbing: grep confirms 0 raw email/display_name in log output
- Owner-only: anonymous GET returns email=None, display_name=None; owner GET returns decrypted values
- Rate limiter: properly disabled in test mode via TESTING env var

## Files Changed (Issue #180)
- `.github/dependabot.yml` — NEW: 5-ecosystem weekly schedule (npm, pip×2, docker, github-actions)
- `.pre-commit-config.yaml` — NEW: detect-secrets + ruff + trailing-whitespace + check-yaml + check-json + check-merge-conflict + detect-private-key
- `.secrets.baseline` — NEW: generated from current main, all flagged items verified as false positives
- `docs/runbooks/github-security-toggles.md` — NEW: setup guide for 3 repo Settings toggles

## Open items
- Issues still assigned to t2o2: #176 (SSM secrets), #165–#153 (Track C/E intelligence)
