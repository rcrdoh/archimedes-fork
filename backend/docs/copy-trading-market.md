# Copy Trading Market

## Overview

The Copy Trading Market lets strategy creators monetize live strategies and lets subscribers copy-trade them. It consists of:

- **Tab 1 — Publish button**: A "Publish to Market" button on the Strategy Passport page that deploys an isolated copy of the strategy with its own vault and vault<>strategy mapping, then lists it in the market.
- **Tab 2 — Market tab**: Browse published strategies, see their subscriptors, and subscribe to copy-trade them.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Tab 1 (Strategy Passport)                                   │
│                                                             │
│  [Publish to Market]                                        │
│       │                                                     │
│       ▼                                                     │
│  1. Create vault on chain (same as passport button)         │
│  2. Deploy isolated Type 2 container with fresh vault/mapping│
│  3. Create vault<>strategy mapping in new container          │
│  4. Mark strategy as 'live' in off-chain DB                 │
│  5. Expose /api/market/events/{id} for Type 3 subscription  │
│  6. Deploy Type 3 replicator container for metering         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Tab 2 (Market)                                              │
│                                                             │
│  GET /api/market/strategies → list published strategies     │
│       │                                                     │
│       ▼                                                     │
│  [Subscribe]                                                │
│       │                                                     │
│       ▼                                                     │
│  1. Configure Arc agent → ephemeral wallet                  │
│  2. Fund wallet (GAS_FUND_AMOUNT + DEPOSIT_AMOUNT)          │
│  3. Transfer to Circle Gateway Wallet deposit()             │
│  4. Create subscriber vault on chain                        │
│  5. Deploy Type 3 replicator container                      │
│  6. Operations unlocked when vault > threshold              │
└─────────────────────────────────────────────────────────────┘
```

## DB Schema

### `published_strategies`
| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| strategy_id | String | Strategy identifier (from original Tab 1) |
| description | Text | Human-readable strategy description for the market |
| creator_wallet | String | Wallet address of the strategy creator |
| vault_address | String | Isolated vault address for this published instance |
| status | String | `draft`, `live`, `paused`, `retired` |
| funding_threshold | Float | Minimum vault balance (USDC) for operations |
| created_at | DateTime | When published |
| updated_at | DateTime | Last update |

### `subscriptions`
| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| published_strategy_id | Integer | FK to published_strategies |
| subscriber_wallet | String | Subscriber's wallet address |
| vault_address | String | Subscriber's vault address |
| deposit_amount | Float | USDC amount deposited |
| funding_threshold | Float | Min vault balance for operations |
| status | String | `active`, `paused`, `retired` |
| created_at | DateTime | When subscribed |

### `subscription_actions`
| Column | Type | Description |
|--------|------|-------------|
| id | Integer | Primary key |
| subscription_id | Integer | FK to subscriptions |
| action_type | String | e.g. `rebalance`, `trade`, `allocation` |
| action_data | JSON | Action payload |
| created_at | DateTime | When action was recorded |

## API Endpoints

All endpoints under `/api/market/`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/publish` | Publish a strategy to the market (Tab 1) |
| GET | `/strategies` | List published strategies |
| GET | `/strategies/{id}` | Strategy detail + subscriptors |
| POST | `/subscribe` | Subscribe to a published strategy |
| POST | `/retire` | Retire funds from a subscription |
| GET | `/subscriptions/{id}/threshold` | Check vault threshold status |
| GET | `/events/{strategy_id}` | Publisher event feed (Type 3 subscribe) |

### POST /api/market/publish

Triggers the 7-step publish chain:
1. Creates vault on chain (same as passport button)
2. Deploys isolated Type 2 Agent container
3. Creates vault<>strategy mapping in new container
4. Marks strategy as live in off-chain DB
5. Gating: operations only if vault > funding threshold
6. Exposes `/api/market/events/{strategy_id}` event feed
7. Launches Type 3 replicator container for metering

**Request body:**
```json
{
  "strategy_id": "string (required)",
  "description": "string (optional)",
  "funding_threshold": "float (optional, default: 10.0)"
}
```

### POST /api/market/subscribe

Subscribe flow:
1. Generate ephemeral wallet via Arc agent
2. Fund with GAS_FUND_AMOUNT + DEPOSIT_AMOUNT (USDC)
3. Transfer into Circle Gateway Wallet `deposit()`
4. Create vault on chain
5. Deploy Type 3 replicator container

**Request body:**
```json
{
  "published_strategy_id": "int (required)",
  "deposit_amount": "float (required)"
}
```

## Type 3 Agent (`agent_replicator.py`)

### Relationship to Type 2 Agent

The Type 3 Agent **reuses** the following from Type 2 Agent's existing code:

| Type 2 Component | Type 3 Reuse |
|-----------------|--------------|
| CLI bootstrap (`python -m archimedes.chain.agent_runner`) | Same pattern: `python -m archimedes.chain.agent_replicator` |
| Vault availability check (`_get_managed_vaults()`) | `_resolve_vaults()` — reads from env or DB subscription |
| Vault<>strategy mapping lookup (`_get_vault_strategy_ids()`) | **Directly imported** — same DB query against `VaultMetadata` |
| Vault balance/threshold gating (`totalAssets()` → threshold comparison) | `_check_vault_threshold()` — same on-chain call |
| Main asyncio loop with configurable `AGENT_INTERVAL_SECONDS` | Same `while True → tick → sleep` loop structure |

### What Type 3 replaces

| Type 2 Operational Loop | Type 3 Operational Loop |
|------------------------|------------------------|
| Evaluate strategy signals | Subscribe to publisher endpoint |
| Compute target allocations | Fetch events from publisher feed |
| Rebalance (set target allocs) | **Check vault threshold** (reused gating) |
| Execute trades via DEX | Replicate publisher actions (stub) |
| Publish reasoning traces | Track consumption for metering |

### Publisher Event Contract

The Type 2 Agent (publisher) pushes events to an in-memory buffer after each rebalance/execute. The Type 3 Agent polls `GET /api/market/events/{strategy_id}`.

**Event format:**
```json
{
  "type": "rebalance | trade | allocation | heartbeat",
  "data": {
    "vault_address": "0x...",
    "trades": [{"symbol": "ETH", "direction": "buy", "amount": 1.5}],
    "reasoning": "...",
    "tick_id": "..."
  },
  "timestamp": "2026-06-26T12:00:00.000Z",
  "id": "rebalance_0_..."
}
```

**The Type 3 Agent:**
1. Polls the publisher endpoint for new events
2. For each event of type `rebalance`, `trade`, or `allocation`:
   - Records it as a `SubscriptionAction` in the DB
   - (Production: executes the same on-chain operation in subscriber's vault)
3. Tracks consumption for billing/metering

## Docker Services

### `replicator` (Type 3 Agent)
- Defined in `docker-compose.yml`
- Runs `python -m archimedes.chain.agent_replicator`
- One instance per subscription (started dynamically)
- Environment: `PUBLISH_ENDPOINT`, `SUBSCRIPTION_ID`, `AGENT_VAULT_ADDRESSES`, `MARKET_FUNDING_THRESHOLD`

### `published-agent` (Type 2 Agent — isolated)
- Template in `docker-compose.yml`
- Started dynamically for each published strategy
- Environment: `PUBLISHED_STRATEGY_ID`, `AGENT_VAULT_ADDRESSES`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKET_FUNDING_THRESHOLD` | `10.0` | Global default funding threshold (USDC) |
| `BUYER_PRIVATE_KEY` | — | Funder wallet private key for Arc agent |
| `GAS_FUND_AMOUNT` | `0.01` | USDC gas funding amount |
| `DEPOSIT_AMOUNT` | `1.0` | USDC deposit amount into Circle wallet |
| `DOCKER_NETWORK` | `archimedes_default` | Docker network for containers |
| `PUBLISHED_AGENT_INTERVAL_SECONDS` | `300` | Tick interval for published agents |
| `BACKEND_INTERNAL_URL` | `http://backend:8000` | Internal backend URL for containers |

## Assumptions

1. **Market metadata fields**: Strategy description is user-provided at publish time. If not provided, the system uses `"Strategy {strategy_id[:12]}"` as a fallback.

2. **Type 3 Agent consumption/metering schema**: The exact metering schema is not specified upstream. Currently, each replicated action is logged as a `SubscriptionAction` record with `action_type` and `action_data`. A future billing system would aggregate these records. Treat this as an assumption to flag and confirm.

3. **Funding threshold defaults**: If a strategy does not specify a `funding_threshold`, the global default `MARKET_FUNDING_THRESHOLD` (10.0 USDC) is used. Per-strategy thresholds can be set at publish time via the `funding_threshold` field.

4. **Arc nanopayments agent**: The Arc agent (`agent.mts`) is an external service. Integration is via a stub (`_configure_arc_agent()`) that generates an ephemeral wallet and funds it. Real credentials (`BUYER_PRIVATE_KEY`) are required for production.

5. **Circle Gateway Wallet**: The Circle Gateway Wallet `deposit()` call is a stub. Real integration requires Circle API credentials and a deployed Gateway Wallet contract.

6. **Docker SDK availability**: The dynamic container creation (`container_manager.py`) requires the Docker SDK and appropriate permissions. When unavailable (e.g., in CI), containers are simulated and operations proceed with `"simulated"` status.

7. **Smart contract vault creation**: Assumes existing `ArchimedesVaultFactory.createVault()` interface from the deployed contract at `ARC_VAULT_FACTORY_ADDRESS`. The `create_vault()` function in `market_routes.py` mirrors the passport button's vault creation flow.

8. **Publisher event feed durability**: Events are stored in an in-memory buffer (max 1000 events). For production, this should be replaced with Redis pub/sub or a message queue to survive container restarts.

## Deployment

### Production
```bash
# Set required env vars in .env
export BUYER_PRIVATE_KEY=0x...
export MARKET_FUNDING_THRESHOLD=10.0

# Deploy with new services
docker compose up --build -d
```

### Testing
```bash
cd backend
pytest tests/test_market.py -v
pytest tests/test_market_integration.py -v
```

### Verification
1. Navigate to a strategy passport page (Tab 1)
2. Click "Publish to Market" (requires wallet + rigor gate pass)
3. Switch to Market tab (Tab 2) — strategy should appear
4. Click to expand — "No subscriptors yet"
5. Click "Subscribe" with deposit amount
6. Verify subscription appears under the strategy's subscriptors
