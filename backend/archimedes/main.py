"""Archimedes — FastAPI application entrypoint.

Minimal bootstrap for the hackathon MVP. Services are added as
team members implement them (strategy engine, portfolio agent, etc.).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/health")
async def health():
    """Health check — used by Docker healthcheck and CI/CD."""
    return {"status": "ok", "service": "archimedes-backend"}


@app.get("/")
async def root():
    return {
        "name": "Archimedes",
        "tagline": "Peer-reviewed AI portfolios, settled on Arc.",
        "docs": "/docs",
    }
