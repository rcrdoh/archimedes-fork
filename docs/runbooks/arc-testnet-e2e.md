# Arc Testnet E2E Smoke Test Runbook

> **Purpose:** Step-by-step verification that the Archimedes vault lifecycle works
> end-to-end on Arc testnet. Run before demos and after any contract/backend change.
>
> **Script:** `backend/archimedes/scripts/verify_arc_e2e.py`
>
> **Evidence output:** `docs/runbooks/arc-testnet-e2e-evidence.md`

## Prerequisites

1. **Arc testnet RPC** — set `RPC` in `.env` (from `arc-canteen login`)
2. **Dev wallet** — fresh wallet with NO mainnet funds. Set `DEV_WALLET_PRIVATE_KEY` in `.env`
3. **Testnet USDC** — get from [faucet.circle.com](https://faucet.circle.com) (20 USDC / 2h)
4. **Arc ETH for gas** — the Arc faucet provides native ETH for gas
5. **Docker stack running** — `docker compose up -d --build`
6. **Contract addresses** — `VAULT_FACTORY_ADDRESS` and `REASONING_TRACE_REGISTRY_ADDRESS` in `.env`

## Quick start

```bash
# Step 0: Check prerequisites (no signing, no on-chain writes)
cd backend
python -m archimedes.scripts.verify_arc_e2e --dry-run

# Step 1: Execute the full E2E test
python -m archimedes.scripts.verify_arc_e2e --execute

# Or with explicit wallet key:
python -m archimedes.scripts.verify_arc_e2e --execute --wallet 0xYOUR_KEY
```

## What the test does

| Step | Action | On-chain? |
|------|--------|-----------|
| 1 | Connect to Arc RPC, verify Chain ID 5042002 | Read |
| 2 | Setup wallet, check ETH balance | Read |
| 3 | Check USDC balance (≥10 USDC recommended) | Read |
| 4 | Create vault via VaultFactory.createVault() | **Write** |
| 5 | Approve USDC for vault | **Write** |
| 6 | Deposit 10 USDC into vault | **Write** |
| 7 | Set target allocations (60% sSPY / 40% USDC) | **Write** |
| 8 | Verify vault state (totalAssets, getHoldings) | Read |
| 9 | Check agent runner status | Read |
| 10 | Poll for rebalance trace (max 5 min) | Read |
| 11 | Verify trace on-chain via /api/traces/{id}/verify | Read |

## Evidence

Every step records:
- Step name + pass/fail status
- Timestamp
- Transaction hashes (with Arcscan links)
- Vault address, trace ID, verification result

Output goes to `docs/runbooks/arc-testnet-e2e-evidence.md`.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "RPC URL not set" | Run `arc-canteen login` or set `RPC` in `.env` |
| "No wallet private key" | Generate: `cast wallet new`. Set `DEV_WALLET_PRIVATE_KEY` in `.env` |
| "USDC balance low" | Get from [faucet.circle.com](https://faucet.circle.com) |
| "TX reverted" at createVault | Check gas / Arc ETH balance. Check VaultFactory is deployed |
| "No trace found" | Agent runner may not have ticked yet. Check `docker compose logs backend` |
| "Trace not verified" | Agent may not have anchored the trace on-chain yet. Wait and retry |

## Arcscan links

- **Arcscan:** `https://testnet.arcscan.app`
- **Example TX:** `https://testnet.arcscan.app/tx/0x...`
- **Example vault:** `https://testnet.arcscan.app/address/0x...`

## Security notes

- **Never commit private keys** — `.env` is gitignored
- **Use a fresh dev wallet** — never one with real assets
- **The --wallet flag passes the key via CLI arg** — clear your shell history after use
- **E2E evidence file contains only addresses and TX hashes** — no private keys
