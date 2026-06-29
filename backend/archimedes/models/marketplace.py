"""Marketplace container ORM model.

Tracks Docker containers spawned by the marketplace router.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from archimedes.db import Base


class MarketplaceContainer(Base):
    __tablename__ = "marketplace_containers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_id: Mapped[str] = mapped_column(String(72), nullable=False, unique=True)
    container_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    creator_wallet: Mapped[str] = mapped_column(String(42), nullable=False, default="")
    subscriber_wallet: Mapped[str] = mapped_column(String(42), nullable=False, default="")
    sub_id: Mapped[str] = mapped_column(String(68), nullable=False, default="")
    pool_id: Mapped[str] = mapped_column(String(66), nullable=False, default="")
    vault_address: Mapped[str] = mapped_column(String(42), nullable=False, default="")
    publisher_endpoint: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "container_id": self.container_id,
            "container_name": self.container_name,
            "role": self.role,
            "strategy_id": self.strategy_id,
            "creator_wallet": self.creator_wallet,
            "subscriber_wallet": self.subscriber_wallet,
            "sub_id": self.sub_id,
            "pool_id": self.pool_id,
            "vault_address": self.vault_address,
            "publisher_endpoint": self.publisher_endpoint,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
        }
