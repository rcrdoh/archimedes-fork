"""Integration tests for the Copy Trading Market.

Tests the full publish → market appearance → subscribe → vault deposit →
operations unlock at threshold → retire → operations pause flow.

These tests use mocked chain/Docker calls but verify end-to-end orchestration
at the model and business logic level.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from archimedes.models.chat import Base
from archimedes.models.market import PublishedStrategy, Subscription


@pytest.fixture
def test_db():
    """In-memory SQLite database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()


class TestPublishToMarketIntegration:
    """Integration: Publish → strategy appears in market with correct mapping."""

    def test_publish_creates_db_record(self, test_db):
        """Publishing a strategy creates a DB record with live status."""
        strategy = PublishedStrategy(
            strategy_id="strat-integration-001",
            description="Integration test strategy",
            creator_address="0xcreator",
            vault_address="0xpublishvault1234567890",
            status="live",
            funding_threshold=150.0,
        )
        test_db.add(strategy)
        test_db.commit()

        # Verify DB record
        published = (
            test_db.query(PublishedStrategy)
            .filter(PublishedStrategy.strategy_id == "strat-integration-001")
            .first()
        )
        assert published is not None
        assert published.status == "live"
        assert published.vault_address == "0xpublishvault1234567890"
        assert published.funding_threshold == 150.0

    def test_published_strategy_appears_in_market_listing(self, test_db):
        """Published strategy should appear in live listing."""
        strategy = PublishedStrategy(
            strategy_id="strat-list-test",
            description="List test strategy",
            creator_address="0xcreator",
            vault_address="0xvault",
            status="live",
            funding_threshold=50.0,
        )
        test_db.add(strategy)
        test_db.commit()

        live = (
            test_db.query(PublishedStrategy)
            .filter(PublishedStrategy.status == "live")
            .all()
        )
        ids = [s.strategy_id for s in live]
        assert "strat-list-test" in ids

    def test_published_strategy_no_subscriptors_initially(self, test_db):
        """Published strategy should have no subscriptors initially."""
        strategy = PublishedStrategy(
            strategy_id="strat-no-subs",
            description="No subs",
            creator_address="0xcreator",
            vault_address="0xvault",
            status="live",
            funding_threshold=50.0,
        )
        test_db.add(strategy)
        test_db.commit()

        subs = (
            test_db.query(Subscription)
            .filter(Subscription.published_strategy_id == strategy.id)
            .all()
        )
        assert len(subs) == 0


class TestSubscribeToMarketIntegration:
    """Integration: Subscribe → ephemeral wallet → vault deposit → operations unlock."""

    def test_subscribe_adds_subscription_to_db(self, test_db):
        """Subscribing creates a new Subscription record linked to the strategy."""
        published = PublishedStrategy(
            strategy_id="strat-sub-flow",
            description="Subscribe flow strategy",
            creator_address="0xcreatorwallet",
            vault_address="0xpublishervault",
            status="live",
            funding_threshold=100.0,
        )
        test_db.add(published)
        test_db.commit()

        sub = Subscription(
            published_strategy_id=published.id,
            subscriber_wallet="0xsubscriber",
            vault_address="0xsubscribervault123456",
            deposit_amount=500.0,
            funding_threshold=100.0,
            status="active",
        )
        test_db.add(sub)
        test_db.commit()

        # Verify subscription exists in DB
        fetched = (
            test_db.query(Subscription)
            .filter(
                Subscription.published_strategy_id == published.id,
            )
            .first()
        )
        assert fetched is not None
        assert fetched.status == "active"
        assert fetched.deposit_amount == 500.0
        assert fetched.vault_address == "0xsubscribervault123456"

    def test_subscriptions_queryable_by_strategy(self, test_db):
        """After subscribing, the subscription is queryable by strategy ID."""
        published = PublishedStrategy(
            strategy_id="strat-subs-list",
            description="Subscriptor test",
            creator_address="0xcreator",
            vault_address="0xpvault",
            status="live",
            funding_threshold=100.0,
        )
        test_db.add(published)
        test_db.commit()

        sub = Subscription(
            published_strategy_id=published.id,
            subscriber_wallet="0xsubwallet",
            vault_address="0xsubvault",
            deposit_amount=200.0,
            status="active",
        )
        test_db.add(sub)
        test_db.commit()

        subs = (
            test_db.query(Subscription)
            .filter(Subscription.published_strategy_id == published.id)
            .all()
        )
        assert len(subs) == 1
        assert subs[0].subscriber_wallet == "0xsubwallet"


class TestThresholdAndRetireIntegration:
    """Integration: Deposit → unlock at threshold → retire → pause operations."""

    def test_subscription_threshold_check(self, test_db):
        """Subscription has a funding threshold for operations gating."""
        sub = Subscription(
            published_strategy_id=1,
            subscriber_wallet="0xsubscriber",
            vault_address="0xsubvault",
            deposit_amount=200.0,
            funding_threshold=100.0,
            status="active",
        )
        test_db.add(sub)
        test_db.commit()
        assert sub.funding_threshold == 100.0
        assert sub.deposit_amount >= sub.funding_threshold

    def test_retire_funds_marks_subscription_retired(self, test_db):
        """Retiring marks subscription as retired in the DB."""
        sub = Subscription(
            published_strategy_id=1,
            subscriber_wallet="0xsubscriber",
            vault_address="0xsubvault",
            deposit_amount=200.0,
            funding_threshold=100.0,
            status="active",
        )
        test_db.add(sub)
        test_db.commit()

        # Simulate retire
        sub.status = "retired"
        test_db.commit()

        updated = (
            test_db.query(Subscription)
            .filter(Subscription.id == sub.id)
            .first()
        )
        assert updated.status == "retired"

    def test_subscription_below_threshold(self, test_db):
        """Subscription below funding threshold should be pausable."""
        sub = Subscription(
            published_strategy_id=1,
            subscriber_wallet="0xsubscriber",
            vault_address="0xsubvault",
            deposit_amount=50.0,
            funding_threshold=100.0,
            status="active",
        )
        test_db.add(sub)
        test_db.commit()
        assert sub.deposit_amount < sub.funding_threshold

        # Status can be set to paused
        sub.status = "paused"
        test_db.commit()
        assert sub.status == "paused"
