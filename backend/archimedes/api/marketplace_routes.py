"""Marketplace routes — publisher/subscriber container lifecycle API."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from archimedes.api.auth_siwe import require_verified_wallet
from archimedes.db import get_session
from archimedes.models.marketplace import MarketplaceContainer
from archimedes.services.container_spawner import (
    ContainerSpawnError,
    DockerUnavailableError,
    spawn_publisher,
    spawn_subscriber,
    stop_container,
)

logger = logging.getLogger(__name__)

marketplace_router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


# ── Request / Response models ─────────────────────────────────────────────


class PublishRequest(BaseModel):
    strategy_id: str = Field(..., min_length=1, max_length=128)
    pool_id: str = Field(..., pattern=r"^0x[a-fA-F0-9]{1,64}$")
    vault_address: str = Field("", pattern=r"^(0x[a-fA-F0-9]{40})?$")
    platform_wallet: str = Field("", pattern=r"^(0x[a-fA-F0-9]{40})?$")


class PublishResponse(BaseModel):
    container_id: str
    container_name: str
    publisher_endpoint: str
    strategy_id: str
    vault_address: str
    status: str = "spawned"


class SubscribeRequest(BaseModel):
    strategy_id: str = Field(..., min_length=1, max_length=128)
    pool_id: str = Field(..., pattern=r"^0x[a-fA-F0-9]{1,64}$")
    sub_id: str = Field(..., pattern=r"^0x[a-fA-F0-9]{1,64}$")
    initial_deposit_usdc: int = Field(10_000_000, ge=1_000_000, le=1_000_000_000)


class SubscribeResponse(BaseModel):
    container_id: str
    container_name: str
    strategy_id: str
    sub_id: str
    publisher_endpoint: str
    status: str = "spawned"


class SubscriberSummary(BaseModel):
    subscriber_wallet: str
    sub_id: str
    container_name: str
    status: str
    subscribed_at: str


class PublishedStrategyResponse(BaseModel):
    strategy_id: str
    container_name: str
    publisher_endpoint: str
    creator_wallet: str
    pool_id: str
    vault_address: str
    active_subscriber_count: int
    subscribers: list[SubscriberSummary]
    published_at: str
    status: str


class PublishedStrategyListResponse(BaseModel):
    strategies: list[PublishedStrategyResponse]
    total: int


class MySubscriptionsResponse(BaseModel):
    subscriptions: list[SubscriberSummary]
    total: int


class StopResponse(BaseModel):
    status: str
    container_name: str


# ── Helpers ───────────────────────────────────────────────────────────────


def _subscriber_from_row(row: MarketplaceContainer) -> SubscriberSummary:
    return SubscriberSummary(
        subscriber_wallet=row.subscriber_wallet,
        sub_id=row.sub_id,
        container_name=row.container_name,
        status=row.status,
        subscribed_at=row.created_at.isoformat() if row.created_at else "",
    )


def _published_from_row(
    row: MarketplaceContainer,
    subscribers: list[SubscriberSummary],
    active_count: int,
) -> PublishedStrategyResponse:
    return PublishedStrategyResponse(
        strategy_id=row.strategy_id,
        container_name=row.container_name,
        publisher_endpoint=row.publisher_endpoint,
        creator_wallet=row.creator_wallet,
        pool_id=row.sub_id,  # publisher stores pool_id in sub_id field
        vault_address=row.vault_address,
        active_subscriber_count=active_count,
        subscribers=subscribers,
        published_at=row.created_at.isoformat() if row.created_at else "",
        status=row.status,
    )


# ── Rate limiter keys ─────────────────────────────────────────────────────


def _publish_rate_key(request: Request) -> str:
    return f"marketplace:publish:{request.state.wallet_address}"


def _subscribe_rate_key(request: Request) -> str:
    return f"marketplace:subscribe:{request.state.wallet_address}"


# ── POST /publish ─────────────────────────────────────────────────────────


@marketplace_router.post("/publish", status_code=201)
async def publish_strategy(
    body: PublishRequest,
    request: Request,
    wallet: str = Depends(require_verified_wallet),
):
    """Publish a strategy — spawns a publisher agent container."""
    db = get_session()
    try:
        # Check for existing running publisher
        existing = (
            db.query(MarketplaceContainer)
            .filter(
                MarketplaceContainer.strategy_id == body.strategy_id,
                MarketplaceContainer.role == "publisher",
                MarketplaceContainer.status == "running",
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="Publisher already running for this strategy",
            )

        try:
            result = spawn_publisher(
                strategy_id=body.strategy_id,
                creator_wallet=wallet,
                pool_id=body.pool_id,
                vault_address=body.vault_address,
                platform_wallet=body.platform_wallet,
            )
        except DockerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ContainerSpawnError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        # Persist
        row = MarketplaceContainer(
            container_id=result["container_id"],
            container_name=result["container_name"],
            role="publisher",
            strategy_id=body.strategy_id,
            creator_wallet=wallet,
            sub_id=body.pool_id,  # store pool_id in sub_id field for publisher rows
            vault_address=body.vault_address,
            publisher_endpoint=result["publisher_endpoint"],
            status="running",
            created_at=datetime.now(UTC),
        )
        db.add(row)
        db.commit()

        return PublishResponse(
            container_id=result["container_id"],
            container_name=result["container_name"],
            publisher_endpoint=result["publisher_endpoint"],
            strategy_id=body.strategy_id,
            vault_address=body.vault_address,
            status="spawned",
        )
    finally:
        db.close()


# ── POST /subscribe ───────────────────────────────────────────────────────


@marketplace_router.post("/subscribe", status_code=201)
async def subscribe_strategy(
    body: SubscribeRequest,
    request: Request,
    wallet: str = Depends(require_verified_wallet),
):
    """Subscribe to a published strategy — spawns a subscriber agent container."""
    db = get_session()
    try:
        # Find running publisher
        publisher = (
            db.query(MarketplaceContainer)
            .filter(
                MarketplaceContainer.strategy_id == body.strategy_id,
                MarketplaceContainer.role == "publisher",
                MarketplaceContainer.status == "running",
            )
            .first()
        )
        if publisher is None:
            raise HTTPException(
                status_code=404,
                detail="No running publisher for this strategy",
            )

        # Check for existing running subscriber for this wallet
        existing_sub = (
            db.query(MarketplaceContainer)
            .filter(
                MarketplaceContainer.strategy_id == body.strategy_id,
                MarketplaceContainer.role == "subscriber",
                MarketplaceContainer.subscriber_wallet == wallet,
                MarketplaceContainer.status == "running",
            )
            .first()
        )
        if existing_sub is not None:
            raise HTTPException(
                status_code=409,
                detail="Already subscribed to this strategy",
            )

        try:
            result = spawn_subscriber(
                strategy_id=body.strategy_id,
                subscriber_wallet=wallet,
                pool_id=body.pool_id,
                sub_id=body.sub_id,
                publisher_container_name=publisher.container_name,
                initial_deposit_usdc=body.initial_deposit_usdc,
            )
        except DockerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ContainerSpawnError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        # Persist
        row = MarketplaceContainer(
            container_id=result["container_id"],
            container_name=result["container_name"],
            role="subscriber",
            strategy_id=body.strategy_id,
            subscriber_wallet=wallet,
            sub_id=body.sub_id,
            publisher_endpoint=publisher.publisher_endpoint,
            status="running",
            created_at=datetime.now(UTC),
        )
        db.add(row)
        db.commit()

        return SubscribeResponse(
            container_id=result["container_id"],
            container_name=result["container_name"],
            strategy_id=body.strategy_id,
            sub_id=body.sub_id,
            publisher_endpoint=publisher.publisher_endpoint,
            status="spawned",
        )
    finally:
        db.close()


# ── DELETE /publish/{strategy_id} ────────────────────────────────────────


@marketplace_router.delete("/publish/{strategy_id}")
async def stop_publish(
    strategy_id: str,
    request: Request,
    wallet: str = Depends(require_verified_wallet),
):
    """Stop a publisher container. Only the creator_wallet may stop it."""
    db = get_session()
    try:
        row = (
            db.query(MarketplaceContainer)
            .filter(
                MarketplaceContainer.strategy_id == strategy_id,
                MarketplaceContainer.role == "publisher",
                MarketplaceContainer.status == "running",
            )
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="No running publisher found")

        if row.creator_wallet != wallet:
            raise HTTPException(
                status_code=403,
                detail="Only the creator may stop this publisher",
            )

        try:
            stop_container(row.container_name)
        except DockerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        row.status = "stopped"
        row.stopped_at = datetime.now(UTC)
        db.commit()

        return StopResponse(status="stopped", container_name=row.container_name)
    finally:
        db.close()


# ── DELETE /subscribe/{strategy_id} ──────────────────────────────────────


@marketplace_router.delete("/subscribe/{strategy_id}")
async def stop_subscription(
    strategy_id: str,
    request: Request,
    wallet: str = Depends(require_verified_wallet),
):
    """Stop a subscriber container. Only the subscriber_wallet may stop it.
    Before stopping, forwards unsubscribe to the publisher (best-effort).
    """
    db = get_session()
    try:
        row = (
            db.query(MarketplaceContainer)
            .filter(
                MarketplaceContainer.strategy_id == strategy_id,
                MarketplaceContainer.role == "subscriber",
                MarketplaceContainer.subscriber_wallet == wallet,
                MarketplaceContainer.status == "running",
            )
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="No running subscription found")

        # F1: Forward unsubscribe to publisher (best-effort, never blocks stop)
        pub_row = (
            db.query(MarketplaceContainer)
            .filter(
                MarketplaceContainer.strategy_id == row.strategy_id,
                MarketplaceContainer.role == "publisher",
                MarketplaceContainer.status == "running",
            )
            .first()
        )
        if pub_row and pub_row.publisher_endpoint and row.sub_id:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    await client.post(
                        f"{pub_row.publisher_endpoint}/unsubscribe",
                        json={"sub_id": row.sub_id},
                    )
            except Exception:
                pass  # best-effort — container stop proceeds regardless

        try:
            stop_container(row.container_name)
        except DockerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        row.status = "stopped"
        row.stopped_at = datetime.now(UTC)
        db.commit()

        return StopResponse(status="stopped", container_name=row.container_name)
    finally:
        db.close()


# ── GET /published ────────────────────────────────────────────────────────


@marketplace_router.get("/published")
async def list_published(
    status: str = Query("running"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Return publisher-centric feed of live strategies with nested subscriber counts.

    No auth required — this is the primary feed endpoint for the UI.
    """
    db = get_session()
    try:
        query = db.query(MarketplaceContainer).filter(
            MarketplaceContainer.role == "publisher",
        )

        if status != "all":
            query = query.filter(MarketplaceContainer.status == status)

        total = query.count()
        publishers = query.order_by(MarketplaceContainer.created_at.desc()).offset(offset).limit(limit).all()

        strategies = []
        for pub in publishers:
            subscribers = (
                db.query(MarketplaceContainer)
                .filter(
                    MarketplaceContainer.role == "subscriber",
                    MarketplaceContainer.strategy_id == pub.strategy_id,
                )
                .all()
            )
            sub_summaries = [_subscriber_from_row(s) for s in subscribers]
            active_count = sum(1 for s in subscribers if s.status == "running")

            strategies.append(_published_from_row(pub, sub_summaries, active_count))

        return PublishedStrategyListResponse(strategies=strategies, total=total)
    finally:
        db.close()


# ── GET /published/{strategy_id} ─────────────────────────────────────────


@marketplace_router.get("/published/{strategy_id}")
async def published_detail(strategy_id: str):
    """Return full detail for one published strategy."""
    db = get_session()
    try:
        pub = (
            db.query(MarketplaceContainer)
            .filter(
                MarketplaceContainer.strategy_id == strategy_id,
                MarketplaceContainer.role == "publisher",
            )
            .order_by(MarketplaceContainer.created_at.desc())
            .first()
        )
        if pub is None:
            raise HTTPException(status_code=404, detail="Strategy not found")

        subscribers = (
            db.query(MarketplaceContainer)
            .filter(
                MarketplaceContainer.role == "subscriber",
                MarketplaceContainer.strategy_id == strategy_id,
            )
            .all()
        )
        sub_summaries = [_subscriber_from_row(s) for s in subscribers]
        active_count = sum(1 for s in subscribers if s.status == "running")

        return _published_from_row(pub, sub_summaries, active_count)
    finally:
        db.close()


# ── GET /my-subscriptions ────────────────────────────────────────────────


@marketplace_router.get("/my-subscriptions")
async def my_subscriptions(
    request: Request,
    wallet: str = Depends(require_verified_wallet),
):
    """Return all subscriber containers owned by the authenticated wallet."""
    db = get_session()
    try:
        rows = (
            db.query(MarketplaceContainer)
            .filter(
                MarketplaceContainer.role == "subscriber",
                MarketplaceContainer.subscriber_wallet == wallet,
            )
            .order_by(MarketplaceContainer.created_at.desc())
            .all()
        )
        summaries = [_subscriber_from_row(r) for r in rows]
        return MySubscriptionsResponse(subscriptions=summaries, total=len(summaries))
    finally:
        db.close()
