"""Chat message model — per-vault chat for the Archimedes marketplace.

Design decisions (hackathon MVP per ecosystem-design-spec.md § 16–17):
  - Fully open: any connected wallet can read/write in any vault chat
  - Wallet address = identity (no profiles, DMs, reactions)
  - AI messages: is_ai=True, triggered by @archimedes mentions or rebalance events
  - Persistence: SQLite for local dev, Postgres in Docker — both via SQLAlchemy
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String, Text, Boolean, Integer, DateTime, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all Archimedes models."""
    pass


class ChatMessage(Base):
    """A single chat message in a vault's chat room."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vault_address: Mapped[str] = mapped_column(String(42), nullable=False, index=True)
    wallet_address: Mapped[str] = mapped_column(String(42), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Composite index for efficient vault + time-ordered queries
    __table_args__ = (
        Index("ix_chat_vault_created", "vault_address", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "vault_address": self.vault_address,
            "wallet_address": self.wallet_address,
            "message": self.message,
            "is_ai": self.is_ai,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
