"""Database setup — SQLAlchemy async engine + session factory.

Uses DATABASE_URL env var (set by docker-compose to Postgres).
Falls back to local SQLite for development.
"""

from __future__ import annotations

import os
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from archimedes.models.chat import Base

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./archimedes_chat.db")


def _get_engine_kwargs() -> dict:
    """Return engine kwargs appropriate for the database type."""
    if DATABASE_URL.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    # Postgres
    return {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}


engine = create_engine(DATABASE_URL, **_get_engine_kwargs())
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """Create all tables (idempotent for hackathon — no Alembic needed)."""
    Base.metadata.create_all(bind=engine)
    logger.info(f"Database tables created at {DATABASE_URL}")


def get_session() -> Session:
    """Get a new DB session. Use as context manager."""
    return SessionLocal()
