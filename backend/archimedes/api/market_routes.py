"""Market endpoints — /api/market/* for copy-trading market.

Tab 2: Published strategies browse, subscription, and fund retirement.
Tab 1: Publish trigger endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from archimedes.api.auth_siwe import require_verified_wallet
from archimedes.api.limiter import limiter
from archimedes.db import get_session
from archimedes.models.market import PublishedStrategy, Subscription, SubscriptionAction
from archimedes.models.chat import VaultMetadata
from archimedes.services.docker_manager import (
    is_container_running,
    start_publisher_agent,
    start_replicator_agent,
    start_subscriber_replicator,
    stop_container,
)

logger = logging.getLogger(__name__)

market_router = APIRouter(prefix="/api/market", tags=["market"])

# ─── Schemas ─────────────────────────────────────────────────


class PublishRequest(BaseModel):
    strategy_id: str
    description: str = ""
    metadata: dict[str, Any] = {}
    funding_threshold: float | None = None  # Override global default


class PublishResponse(BaseModel):
    id: int
    strategy_id: str
    vault_address: str
    description: str
    status: str
    publisher_service_name: str
    replicator_service_name: str
    publish_endpoint: str
    funding_threshold: float
    message: str


class SubscribeRequest(BaseModel):
    published_strategy_id: int
    deposit_amount: float = Field(ge=1.0, description="Investment amount in USDC")


class SubscribeResponse(BaseModel):
    id: int
    subscription_id: int
    ephemeral_wallet_address: str
    vault_address: str
    status: str
    message: str


class RetireRequest(BaseModel):
    subscription_id: int
    retire_amount: float | None = None  # Granular amount to retire; None = full deposit


class RetireResponse(BaseModel):
    subscription_id: int
    status: str
    vault_under_threshold: bool
    message: str


class SubscriptorInfo(BaseModel):
    wallet: str
    vault_address: str
    deposit_amount: float
    status: str
    created_at: str | None


class PublishedStrategyDetail(BaseModel):
    id: int
    strategy_id: str
    vault_address: str
    creator_address: str
    description: str
    metadata: dict[str, Any]
    funding_threshold: float
    status: str
    publish_endpoint: str
    created_at: str | None
    subscriptors: list[SubscriptorInfo]


class PublishedStrategySummary(BaseModel):
    id: int
    strategy_id: str
    vault_address: str
    creator_address: str
    description: str
    funding_threshold: float
    status: str
    subscriptor_count: int
    created_at: str | None


class PublishedListResponse(BaseModel):
    strategies: list[PublishedStrategySummary]
    total: int


class UnpublishRequest(BaseModel):
    published_strategy_id: int


class MySubscriptionResponse(BaseModel):
    id: int
    published_strategy_id: int
    subscriber_wallet: str
    ephemeral_wallet_address: str
    vault_address: str
    deposit_amount: float
    funding_threshold: float
    status: str
    arc_payment_ref: str
    created_at: str | None
    container_running: bool


class UnsubscribeRequest(BaseModel):
    subscription_id: int


# ─── Default threshold ──────────────────────────────────────

_GLOBAL_FUNDING_THRESHOLD = float(os.getenv("MARKET_FUNDING_THRESHOLD", "10.0"))


# ─── Arc Agent / Circle stubs ───────────────────────────────
# These are integration stubs for external services. Real credentials
# are not available in this environment, so they are implemented as
# mockable interfaces.

async def _arc_generate_ephemeral_wallet() -> tuple[str, str]:
    """Generate an ephemeral wallet via the Arc nanopayments agent (agent.mts).

    Returns (ephemeral_address, payment_ref).
    Integration stub: in production, calls agent.mts generateEphemeralWallet().
    """
    # Stub: return a deterministic test address + ref
    import hashlib
    import uuid

    ref = f"arc_pay_{uuid.uuid4().hex[:16]}"
    # Simulate ephemeral keypair generation
    raw = hashlib.sha256(f"ephemeral:{ref}".encode()).hexdigest()
    addr = f"0x{raw[:40]}"
    logger.info("[ARC STUB] Generated ephemeral wallet %s (ref: %s)", addr[:10], ref)
    return addr, ref


async def _arc_fund_ephemeral_wallet(ephemeral_address: str, payment_ref: str) -> None:
    """Fund an ephemeral wallet via Arc nanopayments agent.

    1. Transfer GAS_FUND_AMOUNT (native USDC for gas) from BUYER_PRIVATE_KEY.
    2. Transfer DEPOSIT_AMOUNT (ERC-20 USDC) from BUYER_PRIVATE_KEY.
    3. Both go into the Circle Gateway Wallet's deposit().

    Integration stub: in production, calls agent.mts fundEphemeralWallet().
    """
    gas_amount = float(os.getenv("GAS_FUND_AMOUNT", "0.01"))
    deposit_amount = float(os.getenv("DEPOSIT_AMOUNT", "1.0"))
    buyer_key = os.getenv("BUYER_PRIVATE_KEY", "")
    logger.info(
        "[ARC STUB] Funded ephemeral %s: gas=%s USDC, deposit=%s USDC (buyer_key=%s...)",
        ephemeral_address[:10],
        gas_amount,
        deposit_amount,
        buyer_key[:6] if buyer_key else "unset",
    )


async def _circle_deposit(vault_address: str, amount: float, from_wallet: str) -> str:
    """Deposit USDC into a vault via Circle Gateway Wallet.

    Calls the Vault contract's deposit() function.
    Integration stub: in production, uses circle_signer or raw key.

    Returns a mock transaction hash.
    """
    import hashlib
    import time

    raw = hashlib.sha256(f"deposit:{vault_address}:{amount}:{time.time()}".encode()).hexdigest()
    tx_hash = f"0x{raw[:64]}"
    logger.info(
        "[CIRCLE STUB] Deposited %s USDC into vault %s from %s - tx: %s",
        amount,
        vault_address[:10],
        from_wallet[:10],
        tx_hash[:16],
    )
    return tx_hash


async def _create_vault_on_chain(owner_wallet: str) -> str:
    """Create a new vault on-chain via VaultFactory.

    Integration stub: in production, calls chain_executor.create_vault().
    Returns a mock vault address.
    """
    import hashlib
    import time

    raw = hashlib.sha256(f"vault:{owner_wallet}:{time.time()}".encode()).hexdigest()
    vault_address = f"0x{raw[:40]}"
    logger.info(
        "[CHAIN STUB] Created vault %s for owner %s",
        vault_address[:10],
        owner_wallet[:10],
    )
    return vault_address


async def _get_vault_balance(vault_address: str) -> float:
    """Get vault balance from on-chain.

    Integration stub: in production, calls chain_executor or vault contract.
    """
    # Stub: return a sufficient balance for testing
    return 100.0


async def _check_vault_threshold(vault_address: str, threshold: float) -> bool:
    """Check if vault balance meets the funding threshold."""
    balance = await _get_vault_balance(vault_address)
    return balance >= threshold


# ─── Publish endpoint (Tab 1 trigger) ───────────────────────


@market_router.post("/publish", response_model=PublishResponse)
@limiter.limit("3/minute")
async def publish_strategy(
    req: PublishRequest,
    request: Request,  # noqa: ARG001
    response: Response,  # noqa: ARG001
    wallet: str = Depends(require_verified_wallet),
):
    """Publish a strategy to the copy-trading market.

    Triggered by Tab 1's Publish button. Executes the 7-step chain:
    1. Deploy isolated Type 2 Agent container config
    2. Create new vault on-chain
    3. Create vault<>strategy mapping for the new container
    4. Update off-chain DB to mark published
    5. Launch Type 2 Agent (publisher) container via Docker SDK
    6. Launch Type 3 Agent (replicator) container via Docker SDK
    7. Update DB rows with actual container info
    """
    logger.info(
        "Publish requested by %s for strategy %s",
        wallet[:10],
        req.strategy_id,
    )

    session = get_session()
    try:
        # Step 1-3: Container config, vault creation, vault<>strategy mapping
        vault_address = await _create_vault_on_chain(wallet)

        meta = VaultMetadata(
            vault_address=vault_address,
            name=f"Published: {req.strategy_id[:20]}",
            symbol=f"p{req.strategy_id[:8].upper()}",
            creator_address=wallet.lower(),
        )
        meta.set_strategy_ids([req.strategy_id])
        session.add(meta)

        # Step 4: Create off-chain DB record (published/live)
        threshold = req.funding_threshold if req.funding_threshold is not None else _GLOBAL_FUNDING_THRESHOLD
        published = PublishedStrategy(
            strategy_id=req.strategy_id,
            vault_address=vault_address,
            creator_address=wallet.lower(),
            description=req.description,
            publisher_service_name="",
            replicator_service_name="",
            publish_endpoint="",
            funding_threshold=threshold,
            status="live",
        )
        if req.metadata:
            published.set_metadata(req.metadata)
        session.add(published)
        session.commit()
        session.refresh(published)

        # Step 5: Launch the Type 2 Agent (publisher) container
        # Use published.id for unique, sequential naming
        pub_name = f"agent-pub-{published.id}"
        pub_endpoint = f"http://{pub_name}:8001/events"

        pub_result = start_publisher_agent(
            published_strategy_id=published.id,
            vault_address=vault_address,
            creator_address=wallet.lower(),
            strategy_id=req.strategy_id,
        )

        # Step 6: Launch the Type 3 Agent (replicator) container
        rep_result = start_replicator_agent(
            published_strategy_id=published.id,
            vault_address=vault_address,
            strategy_id=req.strategy_id,
            publish_endpoint=pub_endpoint,
        )

        # Step 7: Update DB row with actual container info
        published.publisher_service_name = pub_name
        published.replicator_service_name = f"agent-rep-{published.id}"
        published.publish_endpoint = pub_endpoint
        session.commit()

        logger.info(
            "Strategy %s published: vault=%s, publisher=%s (id=%s), replicator=%s (id=%s), endpoint=%s",
            req.strategy_id,
            vault_address[:10],
            pub_name,
            pub_result.get("container_id", "unknown"),
            rep_result.get("container_name", "unknown"),
            rep_result.get("container_id", "unknown"),
            pub_endpoint,
        )

        return PublishResponse(
            id=published.id,
            strategy_id=req.strategy_id,
            vault_address=vault_address,
            description=req.description,
            status="live",
            publisher_service_name=pub_name,
            replicator_service_name=f"agent-rep-{published.id}",
            publish_endpoint=pub_endpoint,
            funding_threshold=threshold,
            message=(
                f"Strategy published. Publisher container: {pub_name}, "
                f"Replicator container: agent-rep-{published.id}"
            ),
        )
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.exception("Publish failed for strategy %s", req.strategy_id)
        raise HTTPException(status_code=500, detail=f"Publish failed: {exc}") from exc
    finally:
        session.close()


# ─── List published strategies (Tab 2 browse) ───────────────


@market_router.get("/strategies", response_model=PublishedListResponse)
async def list_published_strategies(
    status: str = Query("live", description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List published strategies available in the market."""
    session = get_session()
    try:
        query = (
            session.query(PublishedStrategy)
            .filter(PublishedStrategy.status == status)
            .order_by(PublishedStrategy.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        strategies = query.all()

        # Count subscriptors per strategy
        result = []
        for s in strategies:
            sub_count = (
                session.query(Subscription)
                .filter(
                    Subscription.published_strategy_id == s.id,
                    Subscription.status.in_(["active", "funding"]),
                )
                .count()
            )
            result.append(
                PublishedStrategySummary(
                    id=s.id,
                    strategy_id=s.strategy_id,
                    vault_address=s.vault_address,
                    creator_address=s.creator_address,
                    description=s.description or "",
                    funding_threshold=s.funding_threshold,
                    status=s.status,
                    subscriptor_count=sub_count,
                    created_at=s.created_at.isoformat() if s.created_at else None,
                )
            )

        total = (
            session.query(PublishedStrategy)
            .filter(PublishedStrategy.status == status)
            .count()
        )

        return PublishedListResponse(strategies=result, total=total)
    finally:
        session.close()


# ─── Get strategy detail + subscriptors ─────────────────────


@market_router.get("/strategies/{strategy_id}", response_model=PublishedStrategyDetail)
async def get_published_strategy_detail(strategy_id: int):
    """Get full detail for a published strategy, including its subscriptors."""
    session = get_session()
    try:
        s = (
            session.query(PublishedStrategy)
            .filter(PublishedStrategy.id == strategy_id)
            .first()
        )
        if s is None:
            raise HTTPException(status_code=404, detail="Published strategy not found")

        subscriptions = (
            session.query(Subscription)
            .filter(
                Subscription.published_strategy_id == s.id,
                Subscription.status.in_(["active", "funding"]),
            )
            .all()
        )

        subscriptors = [
            SubscriptorInfo(
                wallet=sub.subscriber_wallet,
                vault_address=sub.vault_address,
                deposit_amount=sub.deposit_amount,
                status=sub.status,
                created_at=sub.created_at.isoformat() if sub.created_at else None,
            )
            for sub in subscriptions
        ]

        return PublishedStrategyDetail(
            id=s.id,
            strategy_id=s.strategy_id,
            vault_address=s.vault_address,
            creator_address=s.creator_address,
            description=s.description,
            metadata=s.get_metadata(),
            funding_threshold=s.funding_threshold,
            status=s.status,
            publish_endpoint=s.publish_endpoint,
            created_at=s.created_at.isoformat() if s.created_at else None,
            subscriptors=subscriptors,
        )
    finally:
        session.close()


# ─── Subscribe to a strategy ────────────────────────────────


@market_router.post("/subscribe", response_model=SubscribeResponse)
@limiter.limit("5/minute")
async def subscribe_to_strategy(
    req: SubscribeRequest,
    request: Request,  # noqa: ARG001
    response: Response,  # noqa: ARG001
    wallet: str = Depends(require_verified_wallet),
):
    """Subscribe to a published strategy for copy-trading.

    Flow:
    1. Generate ephemeral wallet via Arc nanopayments agent
    2. Fund ephemeral wallet (GAS_FUND_AMOUNT + DEPOSIT_AMOUNT)
    3. Transfer into Circle Gateway Wallet deposit()
    4. Create vault on-chain for this subscription
    5. Create vault<>strategy mapping
    6. Record subscription in DB
    7. Launch Type 3 Agent (subscriber replicator) container
    8. Check vault threshold → set status to active or funding
    """
    session = get_session()
    try:
        # Verify the published strategy exists and is live
        published = (
            session.query(PublishedStrategy)
            .filter(PublishedStrategy.id == req.published_strategy_id)
            .first()
        )
        if published is None:
            raise HTTPException(status_code=404, detail="Published strategy not found")
        if published.status != "live":
            raise HTTPException(
                status_code=400,
                detail=f"Strategy is not live (status: {published.status})",
            )

        # Step 1: Generate ephemeral wallet via Arc agent
        ephemeral_addr, payment_ref = await _arc_generate_ephemeral_wallet()

        # Step 2+3: Fund ephemeral wallet + Circle deposit
        await _arc_fund_ephemeral_wallet(ephemeral_addr, payment_ref)
        await _circle_deposit(published.vault_address, req.deposit_amount, ephemeral_addr)

        # Step 4: Create vault on-chain for this subscription
        vault_address = await _create_vault_on_chain(wallet)

        # Step 5: Create vault<>strategy mapping for subscription vault
        meta = VaultMetadata(
            vault_address=vault_address,
            name=f"Copy: {published.strategy_id[:20]}",
            symbol=f"c{published.strategy_id[:8].upper()}",
            creator_address=wallet.lower(),
        )
        meta.set_strategy_ids([published.strategy_id])
        session.add(meta)

        # Step 6: Create subscription record
        threshold = published.funding_threshold
        subscription = Subscription(
            published_strategy_id=req.published_strategy_id,
            subscriber_wallet=wallet.lower(),
            ephemeral_wallet_address=ephemeral_addr,
            vault_address=vault_address,
            deposit_amount=req.deposit_amount,
            funding_threshold=threshold,
            status="funding",
            arc_payment_ref=payment_ref,
        )
        session.add(subscription)
        session.commit()
        session.refresh(subscription)

        # Step 7: Launch the Type 3 Agent (subscriber replicator) container
        subscriber_container = start_subscriber_replicator(
            subscription_id=subscription.id,
            published_strategy_id=published.id,
            vault_address=vault_address,
            publish_endpoint=published.publish_endpoint,
        )
        logger.info(
            "Subscriber container launched for subscription %d (container=%s)",
            subscription.id,
            subscriber_container.get("container_id", "unknown"),
        )

        # Step 8: Check threshold immediately and set status
        meets_threshold = await _check_vault_threshold(vault_address, threshold)
        if meets_threshold:
            subscription.status = "active"
        else:
            subscription.status = "funding"
        session.commit()

        logger.info(
            "Subscription created: strategy=%d, subscriber=%s, vault=%s, threshold_met=%s",
            req.published_strategy_id,
            wallet[:10],
            vault_address[:10],
            meets_threshold,
        )

        return SubscribeResponse(
            id=subscription.id,
            subscription_id=subscription.id,
            ephemeral_wallet_address=ephemeral_addr,
            vault_address=vault_address,
            status=subscription.status,
            message=(
                f"Subscribed successfully. Vault: {vault_address[:10]}…, "
                f"Ephemeral wallet: {ephemeral_addr[:10]}…, "
                f"Threshold met: {meets_threshold}"
            ),
        )
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.exception("Subscribe failed")
        raise HTTPException(status_code=500, detail=f"Subscribe failed: {exc}") from exc
    finally:
        session.close()


# ─── Retire funds ───────────────────────────────────────────


@market_router.post("/retire", response_model=RetireResponse)
@limiter.limit("5/minute")
async def retire_funds(
    req: RetireRequest,
    request: Request,  # noqa: ARG001
    response: Response,  # noqa: ARG001
    wallet: str = Depends(require_verified_wallet),
):
    """Retire funds from a subscription.

    If retire_amount is specified, only that amount is notionally retired and
    the vault threshold is re-evaluated against (current_balance - retire_amount).
    If the vault falls under threshold, the subscriber container is stopped.

    If no retire_amount is given, the full vault is retired → subscription
    status becomes "retired" and the subscriber container is stopped.
    """
    session = get_session()
    try:
        subscription = (
            session.query(Subscription)
            .filter(Subscription.id == req.subscription_id)
            .first()
        )
        if subscription is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        if subscription.subscriber_wallet.lower() != wallet.lower():
            raise HTTPException(
                status_code=403,
                detail="Not authorized to retire funds from this subscription",
            )

        retire_amt = req.retire_amount
        effective_balance = subscription.deposit_amount
        if retire_amt is not None and retire_amt > 0:
            # Partial retirement: notionally reduce the balance
            logger.info(
                "Partial retirement: subscription=%d, amount=%s, current_deposit=%s",
                req.subscription_id,
                retire_amt,
                effective_balance,
            )
            effective_balance = max(0.0, effective_balance - retire_amt)
        else:
            # Full retirement
            subscription.status = "retired"
            effective_balance = 0.0

        # Check if effective balance is below threshold
        vault_under = effective_balance < subscription.funding_threshold

        if vault_under:
            # Stop the subscriber container
            container_name = f"agent-sub-{subscription.id}"
            stop_container(container_name)
            if retire_amt is None or retire_amt <= 0:
                subscription.status = "retired"
            else:
                # Partial retire that drops below threshold → pause operations
                subscription.status = "paused"

        session.commit()

        logger.info(
            "Funds retired: subscription=%d, retire_amount=%s, vault_under_threshold=%s, new_status=%s",
            req.subscription_id,
            retire_amt,
            vault_under,
            subscription.status,
        )

        return RetireResponse(
            subscription_id=req.subscription_id,
            status=subscription.status,
            vault_under_threshold=vault_under,
            message=(
                f"Funds retired. Vault {'below' if vault_under else 'above'} threshold. "
                f"Status: {subscription.status}."
            ),
        )
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.exception("Retire failed")
        raise HTTPException(status_code=500, detail=f"Retire failed: {exc}") from exc
    finally:
        session.close()


# ─── Threshold check utility ────────────────────────────────


@market_router.get("/subscriptions/{subscription_id}/threshold")
async def check_subscription_threshold(subscription_id: int):
    """Check if a subscription's vault meets the funding threshold."""
    session = get_session()
    try:
        subscription = (
            session.query(Subscription)
            .filter(Subscription.id == subscription_id)
            .first()
        )
        if subscription is None:
            raise HTTPException(status_code=404, detail="Subscription not found")

        meets = await _check_vault_threshold(
            subscription.vault_address, subscription.funding_threshold
        )
        return {
            "subscription_id": subscription_id,
            "vault_address": subscription.vault_address,
            "funding_threshold": subscription.funding_threshold,
            "threshold_met": meets,
            "status": subscription.status,
        }
    finally:
        session.close()


# ─── Publisher event feed (Type 3 Agent subscribe endpoint) ─


@market_router.get("/events/{strategy_id}")
async def get_strategy_events(
    strategy_id: int,
    since: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Get recent events for a published strategy.

    This is the endpoint that Type 3 Agents poll to get publisher actions.
    """
    from archimedes.chain.event_publisher import get_events_sync

    # Verify strategy exists and is published
    session = get_session()
    try:
        published = (
            session.query(PublishedStrategy)
            .filter(PublishedStrategy.id == strategy_id)
            .first()
        )
        if published is None:
            raise HTTPException(status_code=404, detail="Published strategy not found")

        events = get_events_sync(since=since, limit=limit)
        # Filter events to this strategy's vault
        vault_events = [
            e for e in events
            if e.get("data", {}).get("vault_address", "").lower() == published.vault_address.lower()
        ]
        return {"events": vault_events, "total": len(vault_events)}
    finally:
        session.close()


# ─── My published strategies (Library → Published tab) ─────


@market_router.get("/strategies/mine", response_model=PublishedListResponse)
async def list_my_published_strategies(
    wallet: str = Depends(require_verified_wallet),
):
    """List published strategies belonging to the connected wallet."""
    session = get_session()
    try:
        strategies = (
            session.query(PublishedStrategy)
            .filter(PublishedStrategy.creator_address == wallet.lower())
            .order_by(PublishedStrategy.created_at.desc())
            .all()
        )

        result = []
        for s in strategies:
            sub_count = (
                session.query(Subscription)
                .filter(
                    Subscription.published_strategy_id == s.id,
                    Subscription.status.in_(["active", "funding"]),
                )
                .count()
            )
            result.append(
                PublishedStrategySummary(
                    id=s.id,
                    strategy_id=s.strategy_id,
                    vault_address=s.vault_address,
                    creator_address=s.creator_address,
                    description=s.description or "",
                    funding_threshold=s.funding_threshold,
                    status=s.status,
                    subscriptor_count=sub_count,
                    created_at=s.created_at.isoformat() if s.created_at else None,
                )
            )

        return PublishedListResponse(strategies=result, total=len(result))
    finally:
        session.close()


# ─── Unpublish / Retire a published strategy ───────────────


@market_router.post("/unpublish")
async def unpublish_strategy(
    req: UnpublishRequest,
    wallet: str = Depends(require_verified_wallet),
):
    """Retire a published strategy and tear down its containers."""
    session = get_session()
    try:
        published = (
            session.query(PublishedStrategy)
            .filter(PublishedStrategy.id == req.published_strategy_id)
            .first()
        )
        if published is None:
            raise HTTPException(status_code=404, detail="Published strategy not found")
        if published.creator_address.lower() != wallet.lower():
            raise HTTPException(
                status_code=403,
                detail="Not authorized to unpublish this strategy",
            )

        # Stop publisher and replicator containers
        if published.publisher_service_name:
            stop_container(published.publisher_service_name)
        if published.replicator_service_name:
            stop_container(published.replicator_service_name)

        published.status = "retired"
        session.commit()

        logger.info(
            "Strategy unpublished: id=%d, strategy=%s, containers stopped",
            published.id,
            published.strategy_id,
        )

        return {
            "published_strategy_id": published.id,
            "status": "retired",
            "message": f"Strategy '{published.strategy_id}' retired. Containers stopped.",
        }
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.exception("Unpublish failed")
        raise HTTPException(status_code=500, detail=f"Unpublish failed: {exc}") from exc
    finally:
        session.close()


# ─── My subscription for a given published strategy ────────


@market_router.get("/subscriptions/mine", response_model=MySubscriptionResponse | None)
async def get_my_subscription(
    published_strategy_id: int = Query(..., description="Published strategy ID"),
    wallet: str = Depends(require_verified_wallet),
):
    """Get the connected wallet's active subscription for a given published strategy."""
    session = get_session()
    try:
        subscription = (
            session.query(Subscription)
            .filter(
                Subscription.published_strategy_id == published_strategy_id,
                Subscription.subscriber_wallet == wallet.lower(),
                Subscription.status.in_(["active", "funding"]),
            )
            .first()
        )
        if subscription is None:
            return None

        container_running = is_container_running(f"agent-sub-{subscription.id}")

        return MySubscriptionResponse(
            id=subscription.id,
            published_strategy_id=subscription.published_strategy_id,
            subscriber_wallet=subscription.subscriber_wallet,
            ephemeral_wallet_address=subscription.ephemeral_wallet_address,
            vault_address=subscription.vault_address,
            deposit_amount=subscription.deposit_amount,
            funding_threshold=subscription.funding_threshold,
            status=subscription.status,
            arc_payment_ref=subscription.arc_payment_ref,
            created_at=subscription.created_at.isoformat() if subscription.created_at else None,
            container_running=container_running,
        )
    finally:
        session.close()


# ─── Unsubscribe (hard stop) ───────────────────────────────


@market_router.post("/unsubscribe")
async def unsubscribe(
    req: UnsubscribeRequest,
    wallet: str = Depends(require_verified_wallet),
):
    """Hard-unsubscribe: retire subscription and stop subscriber container."""
    session = get_session()
    try:
        subscription = (
            session.query(Subscription)
            .filter(Subscription.id == req.subscription_id)
            .first()
        )
        if subscription is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        if subscription.subscriber_wallet.lower() != wallet.lower():
            raise HTTPException(
                status_code=403,
                detail="Not authorized to unsubscribe this subscription",
            )

        subscription.status = "retired"
        session.commit()

        # Stop subscriber container
        container_name = f"agent-sub-{subscription.id}"
        stop_container(container_name)

        logger.info(
            "Unsubscribed: subscription=%d, container=%s stopped",
            req.subscription_id,
            container_name,
        )

        return {
            "subscription_id": req.subscription_id,
            "status": "retired",
            "message": f"Subscription {req.subscription_id} retired. Container removed.",
        }
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.exception("Unsubscribe failed")
        raise HTTPException(status_code=500, detail=f"Unsubscribe failed: {exc}") from exc
    finally:
        session.close()
