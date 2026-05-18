"""Archimedes — FastAPI application entrypoint.

Minimal bootstrap for the hackathon MVP. All routes are wired to
chain services that read/write Arc smart contracts.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env into os.environ at import time for modules that use os.getenv()
# (circle_signer, oracle_updater) — pydantic ChainSettings handles ARC_ vars itself.
from dotenv import load_dotenv
load_dotenv("../.env", override=True)  # Project root .env first (has real secrets)
load_dotenv(".env", override=False)  # Backend-local .env fills in any missing (no override)

from archimedes.api.routes import (
    agent_router,
    assets_router,
    vaults_router,
    strategies_router,
    traces_router,
    regime_router,
    swap_router,
    config_router,
)
from archimedes.api.chat_routes import chat_router
from archimedes.api.marketplace_routes import marketplace_router
from archimedes.api.risk_routes import risk_router
from archimedes.api.selection_bias_routes import selection_bias_router
from archimedes.db import init_db

app = FastAPI(
    title="Archimedes",
    description="Peer-reviewed AI portfolios, settled on Arc.",
    version="0.1.0",
)

# Allow the Next.js frontend to call the API during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database (creates chat tables if needed)
init_db()


@app.on_event("startup")
async def _startup_populate_rigor_gate():
    """On first startup, compute and persist selection-bias rigor gate fields.

    Idempotent: only populates strategies that don't yet have DSR/PBO values.
    Skips entirely if the backtest_results table is empty.
    """
    import logging
    _logger = logging.getLogger("archimedes.startup")
    try:
        from archimedes.services.strategy_provider import default_provider
        from archimedes.db import get_session
        from archimedes.models.backtest_store import BacktestResultRecord

        provider = default_provider()
        strategies = provider.list_strategies()
        if not strategies:
            return

        strategy_ids = [s.id for s in strategies]
        with get_session() as session:
            rows = session.query(BacktestResultRecord).filter(
                BacktestResultRecord.strategy_id.in_(strategy_ids)
            ).all()

            # Check if any need rigor gate computation
            needs_rigor = [r for r in rows if r.deflated_sharpe_ratio is None]
            if not needs_rigor:
                _logger.info("startup: all %d backtest rows have rigor gate fields", len(rows))
                return

        _logger.info("startup: computing rigor gate for %d strategies...", len(needs_rigor))

        # Call the rigor gate endpoint logic (triggers full computation + persist)
        from archimedes.api.selection_bias_routes import evaluate_rigor_gate
        import asyncio
        result = await evaluate_rigor_gate()
        _logger.info(
            "startup: rigor gate computed — %d/%d passing",
            result.passing, result.total,
        )
    except Exception as exc:
        _logger.warning("startup: rigor gate population failed (non-fatal): %s", exc)

# Wire all routers
app.include_router(assets_router)
app.include_router(vaults_router)
app.include_router(strategies_router)
app.include_router(traces_router)
app.include_router(regime_router)
app.include_router(swap_router)
app.include_router(config_router)
app.include_router(agent_router)
app.include_router(chat_router)
app.include_router(marketplace_router)
app.include_router(risk_router)
app.include_router(selection_bias_router)


@app.get("/health")
async def health():
    """Health check — used by Docker healthcheck and CI/CD."""
    from archimedes.chain.client import chain_client

    connected = await chain_client.is_connected()
    return {
        "status": "ok" if connected else "degraded",
        "service": "archimedes-backend",
        "chain_connected": connected,
    }


@app.get("/")
async def root():
    return {
        "name": "Archimedes",
        "tagline": "Peer-reviewed AI portfolios, settled on Arc.",
        "docs": "/docs",
    }
