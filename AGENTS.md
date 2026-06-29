# AGENTS.md — ARC Ecosystem Context System (+ Trading Tools)

> **Purpose:** Router that maps any task to the correct source namespace and skill.
> Covers 10 source repositories: 7 ARC/Circle ecosystem repos + 3 trading tool projects
> (titanoboa Vyper dev framework, freqtrade trading bot, hummingbot market-making bot).
>
> **How to use:** Read this file first. Identify which source(s) the task concerns.
> Filter the Skill Directory to that namespace (plus any `shared__*` rows).
> Load only the skills you need — do not load all skills at once.

## System Context

**Unified skill system** for two groups of repos:
- **ARC Ecosystem** (7 repos): quantitative-finance vaults (archimedes + archimedes-fork-1),
  nanopayments (arc-nanopayments), prediction-market off-chain backend (cypherlexicon-offchain),
  on-chain contracts (auction-prediction-market, vyper-agentic-payments), and ARC/Circle
  developer knowledge base (arc-canteen-context). Built on Arc testnet (Chain ID 5042002).
- **Trading Tools** (3 repos): titanoboa (Vyper/EVM dev framework), freqtrade (crypto trading bot),
  hummingbot (crypto market-making bot). Independent projects with no code sharing between them
  or with the ARC ecosystem.

## Source Directory

| Namespace | Source Path | Project Name | Primary Domains |
| --- | --- | --- | --- |
| `archimedes` | `/home/ricardo/github/archimedes` | Archimedes | q-fin, smart-contracts, AI-agents |
| `archimedes-fork-1` | `/home/ricardo/github/archimedes-fork-1` | Archimedes (fork) | q-fin, smart-contracts, AI-agents, Circle-wallets |
| `arc-nanopayments` | `/home/ricardo/github/arc-nanopayments` | ARC Nanopayments | x402, gateway, wallets |
| `cypherlexicon-offchain` | `/home/ricardo/github/CypherLexicon-offchain` | CypherLexicon Offchain | prediction-markets, AI-evaluation |
| `auction-prediction-market` | `/home/ricardo/github/auction-prediction-market` | Auction Prediction Market | solidity-contracts, foundry |
| `arc-canteen-context` | `/home/ricardo/.arc-canteen/context` | ARC Canteen Context | arc-docs, circle-docs, sdks |
| `vyper-agentic-payments` | `/home/ricardo/github/vyper-agentic-payments` | Vyper Agentic Payments | vyper-contracts, agentic-payments, hackathon |
| `titanoboa` | `/home/ricardo/github/titanoboa` | Titanoboa | vyper-dev, evm-simulation, blockchain-forking |
| `freqtrade` | `/home/ricardo/github/freqtrade` | Freqtrade | crypto-trading, backtesting, ML-trading |
| `hummingbot` | `/home/ricardo/github/hummingbot` | Hummingbot | market-making, exchange-connectors, hft |

## Skill Directory

### ARC Ecosystem (7 sources, 36 skills)
See each namespace's skills via their individual SKILL.md files. Key prefixes:
- `archimedes__*` (7 skills) — backend, smart-contracts, analytics-engine, agents, infrastructure, payments, ui
- `archimedes-fork-1__*` (6 skills) — backend, analytics-engine, smart-contracts, ui, infrastructure, docs, wallet-setup
- `arc-nanopayments__*` (4 skills) — dashboard, x402-gateway, wallet-management, supabase-auth
- `cypherlexicon-offchain__*` (5 skills) — auction-service, prediction-market-backend, blockchain-layer, ai-agents, frontend
- `auction-prediction-market__*` (2 skills) — contracts, deployment-testing
- `arc-canteen-context__*` (6 skills) — arc-docs, circle-docs, clob-client, polymarket-sdk, builder-relayer, real-time-data
- `vyper-agentic-payments__*` (6 skills) — contracts, tests, challenges, examples, docs, scripts-deploy
- `shared__*` (2 skills) — arc-blockchain, prediction-market-contracts

### titanoboa (7 skills)
| Skill | Source | Description | Triggers |
| --- | --- | --- | --- |
| `titanoboa__core-api` | titanoboa | Public API, Env singleton, load/deploy/fork entry points | on-demand |
| `titanoboa__vyper-contracts` | titanoboa | Vyper contract loading, compilation, deployment | on-demand |
| `titanoboa__evm-layer` | titanoboa | PyEVM wrapper, fast mode, gas metering | on-demand |
| `titanoboa__forking-network` | titanoboa | Mainnet forking, RPC layer, real-chain deployment | on-demand |
| `titanoboa__testing` | titanoboa | Pytest plugin, Vyper coverage, Hypothesis fuzzing | on-demand |
| `titanoboa__developer-tools` | titanoboa | Debugger, IPython/Jupyter magics, Etherscan | on-demand |
| `titanoboa__deployments-verification` | titanoboa | Deployments DB, contract verification | on-demand |

### freqtrade (10 skills)
| Skill | Source | Description | Triggers |
| --- | --- | --- | --- |
| `freqtrade__trading-engine` | freqtrade | Main bot loop, Worker, FreqtradeBot orchestrator | freqtradebot, worker |
| `freqtrade__exchange-integration` | freqtrade | CCXT exchange abstraction, WebSocket, 20+ connectors | exchange, ccxt |
| `freqtrade__strategy-engine` | freqtrade | IStrategy interface, parameters, DataProvider | strategy, IStrategy |
| `freqtrade__backtesting` | freqtrade | Historical backtesting engine, order matching | backtesting, backtest |
| `freqtrade__hyperopt` | freqtrade | Optuna hyperparameter optimization | hyperopt, optuna |
| `freqtrade__freqai` | freqtrade | ML models, data kitchen, RL, PyTorch | freqai, prediction model |
| `freqtrade__risk-management` | freqtrade | Pairlists, protections, stop-loss, leverage | pairlist, protection, stoploss |
| `freqtrade__rpc-ui` | freqtrade | Telegram, Discord, Webhook, REST API (FastAPI) | telegram, discord, rpc |
| `freqtrade__data-management` | freqtrade | OHLCV data download, history, conversion | data download, ohlcv |
| `freqtrade__configuration` | freqtrade | Config loading, JSON schema, env var overrides | config, configuration |

### hummingbot (8 skills)
| Skill | Source | Description | Triggers |
| --- | --- | --- | --- |
| `hummingbot__exchange-connectors` | hummingbot | Connector framework, 100+ exchange implementations | connector, exchange connector |
| `hummingbot__v1-strategies` | hummingbot | V1 strategies: PMM, XEMM, AMM arb, liquidity mining | v1 strategy, pure market making |
| `hummingbot__v2-framework` | hummingbot | V2 controller/executor, pydantic models, backtesting | v2 strategy, controller, executor |
| `hummingbot__core-engine` | hummingbot | Clock, event system, C++ order book, API throttler | on-demand |
| `hummingbot__market-data` | hummingbot | Order book, candles, liquidation feeds | market data, order book, candles |
| `hummingbot__cli-tui` | hummingbot | prompt_toolkit TUI, CLI commands, config | cli, command, tui |
| `hummingbot__remote-control` | hummingbot | MQTT remote interface | mqtt, remote control |
| `hummingbot__dex-gateway` | hummingbot | Gateway middleware for DEX/AMM protocols | gateway, dex, amm |

## How to Navigate

1. Identify which source(s) the task concerns using the Source Directory.
2. Filter the Skill Directory to that namespace prefix (plus `shared__*` rows relevant to it).
3. Load only the skills actually needed — do not load skills from unrelated namespaces.
4. Cross-source tasks (e.g. "deploy contracts and update the off-chain backend") load both source-specific skills plus the relevant `shared__*` skill.

## Critical Cross-System Rules

1. **Arc testnet (Chain ID 5042002)** is the single live chain for ARC sources. Never use mainnet without explicit confirmation.
2. **USDC (6 decimals)** is the native gas token on Arc. Never assume ETH-style gas handling.
3. **Each source's SKILL.md uses absolute paths** — there is no implicit "current source" context in a multi-source `.agents/skills/` folder.
4. **Never apply one source's conventions to another** without checking that source's own SKILL.md constraints.
5. **Secrets NEVER committed** in any source. All use `.env.example` patterns.
6. **`archimedes-fork-1` is a fork of the original `archimedes` repo** — shares architecture lineage but has own team, deploy, and AWS account.
7. **titanoboa, freqtrade, and hummingbot are independent projects** — they share no code. Do not assume CCXT patterns from freqtrade apply to hummingbot's custom connectors, or vice versa.
8. **hummingbot v1 vs v2**: V1 strategies are monolithic; V2 uses controller/executor pattern. Check which framework a task targets before writing code.

## Deployment Note

This `.agents/skills/` folder is auto-loaded by OpenHands **only if** `/home/ricardo/github/docs` is the working directory OpenHands is invoked against. If any individual source repo is opened independently, you must copy or symlink this `.agents/` folder into that repo's root for auto-discovery, or load skills explicitly by path.

## Adding a New Source

1. Derive one namespace per Step 0 (use the path-derived slug, lowercased).
2. Repeat Steps 1–8 for that source only.
3. Add rows to the Source Directory and Skill Directory tables above.
4. Do not regenerate or rename existing namespaces' skills.


# Git Feature Branch Workflow

As the OpenHands agent, use this workflow when implementing a feature requested
in chat. The feature branch itself is the deliverable — no pull request is
needed.

### 1. Create Branch
Create a new git branch with this naming pattern:
agent/task-{TIMESTAMP}-{feature-name}
Example: `agent/task-1704067200-auth-feature`

Command:
```bash
git checkout -b agent/task-$(date +%s)-{feature-name}
```

### 2. Implement Feature
Write the code for the requested feature:
- Create new files as needed
- Follow existing code patterns
- Add comments where appropriate

### 3. Commit Code
Commit your changes with a clear message:
```bash
git commit -m "[AGENT:feature-name] {description of what was implemented}

Co-authored-by: openhands <openhands@all-hands.dev>"
```

### 4. Push Branch
Push your branch to remote:
```bash
git push origin agent/task-{TIMESTAMP}-{feature-name}
```

The code is now in its own feature branch, ready for review. No pull request
is created — the branch is published and handled separately.