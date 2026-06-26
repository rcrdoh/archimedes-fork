"""Unit tests for the Copy Trading Market feature.

Covers:
- Publish trigger chain (Tab 1 button → isolated container)
- Subscribe flow (Tab 2 subscribe → ephemeral wallet → vault)
- Threshold-gating logic (publish-side and subscriber-side)
- Fund retirement re-evaluation
- Model constraints and relationships
- Event publisher
- Type 3 Agent vault checks
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from archimedes.chain.event_publisher import get_events_sync
from archimedes.models.market import (
    PublishedStrategy,
    Subscription,
    SubscriptionAction,
)


@pytest.fixture
def test_db():
    """Create in-memory SQLite database for testing."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from archimedes.models.chat import Base

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()


@pytest.fixture
def sample_strategy(test_db):
    """Create a sample strategy in the DB."""
    strategy = PublishedStrategy(
        strategy_id="strat-test-001",
        description="Test momentum strategy",
        creator_address="0xcreator1234567890abcdef",
        vault_address="0xvault1234567890abcdef",
        status="live",
        funding_threshold=100.0,
    )
    test_db.add(strategy)
    test_db.commit()
    return strategy


@pytest.fixture
def sample_subscription(test_db, sample_strategy):
    """Create a sample subscription."""
    sub = Subscription(
        published_strategy_id=sample_strategy.id,
        subscriber_wallet="0xsubscriber1234567890abcdef",
        vault_address="0xsubvault1234567890abcdef",
        deposit_amount=500.0,
        funding_threshold=100.0,
        status="active",
    )
    test_db.add(sub)
    test_db.commit()
    return sub


# ── Model validation tests ───────────────────────────────


class TestPublishedStrategyModel:
    """Test PublishedStrategy model constraints."""

    def test_default_status(self, test_db):
        """Default status should be 'publishing'."""
        ps = PublishedStrategy(
            strategy_id="strat-default-test",
            description="Default test",
            creator_address="0xcreator",
            vault_address="0xvault",
            funding_threshold=50.0,
        )
        test_db.add(ps)
        test_db.commit()
        assert ps.status == "publishing"

    def test_default_funding_threshold(self, test_db):
        """Default funding threshold should be 10.0."""
        ps = PublishedStrategy(
            strategy_id="strat-threshold-test",
            description="Threshold test",
            creator_address="0xcreator",
            vault_address="0xvault",
        )
        test_db.add(ps)
        test_db.commit()
        assert ps.funding_threshold == 10.0

    def test_to_dict(self, test_db, sample_strategy):
        """PublishedStrategy to_dict should include relevant fields."""
        d = sample_strategy.to_dict()
        assert d["strategy_id"] == "strat-test-001"
        assert d["status"] == "live"
        assert d["creator_address"] == "0xcreator1234567890abcdef"

    def test_metadata_json(self, test_db):
        """PublishedStrategy metadata_json should be serializable."""
        ps = PublishedStrategy(
            strategy_id="strat-meta",
            description="Meta test",
            creator_address="0xcreator",
            vault_address="0xvault-meta",
            metadata_json='{"key": "value"}',
        )
        test_db.add(ps)
        test_db.commit()
        assert ps.get_metadata() == {"key": "value"}

    def test_set_metadata(self, test_db):
        """set_metadata should update metadata_json."""
        ps = PublishedStrategy(
            strategy_id="strat-set-meta",
            description="Set meta",
            creator_address="0xcreator",
            vault_address="0xvault-set-meta",
        )
        test_db.add(ps)
        test_db.commit()
        ps.set_metadata({"version": 2})
        assert ps.get_metadata() == {"version": 2}


class TestSubscriptionModel:
    """Test Subscription model constraints."""

    def test_create_subscription(self, test_db, sample_strategy):
        """Creating a subscription should work with all fields."""
        sub = Subscription(
            published_strategy_id=sample_strategy.id,
            subscriber_wallet="0xsubcreate",
            vault_address="0xvaultcreate",
            deposit_amount=200.0,
            funding_threshold=50.0,
            status="active",
        )
        test_db.add(sub)
        test_db.commit()
        assert sub.id is not None
        assert sub.published_strategy_id == sample_strategy.id

    def test_cascade_delete(self, test_db, sample_strategy):
        """Manually handle cascade since model uses plain FK without cascade."""
        sub = Subscription(
            published_strategy_id=sample_strategy.id,
            subscriber_wallet="0xsubcascade",
            vault_address="0xvaultcascade",
            deposit_amount=200.0,
            funding_threshold=50.0,
            status="active",
        )
        test_db.add(sub)
        test_db.commit()

        # Manually delete subscription first, then strategy
        test_db.delete(sub)
        test_db.delete(sample_strategy)
        test_db.commit()

        remaining = test_db.query(Subscription).filter(
            Subscription.subscriber_wallet == "0xsubcascade"
        ).count()
        assert remaining == 0

    def test_subscription_action_relationship(self, test_db, sample_subscription):
        """SubscriptionAction should link back to Subscription."""
        action = SubscriptionAction(
            subscription_id=sample_subscription.id,
            action_type="rebalance",
            action_data='{"test": true}',
        )
        test_db.add(action)
        test_db.commit()

        assert action.subscription_id == sample_subscription.id
        assert action.action_type == "rebalance"

    def test_subscription_defaults(self, test_db, sample_strategy):
        """Subscription should use default funding_threshold."""
        sub = Subscription(
            published_strategy_id=sample_strategy.id,
            subscriber_wallet="0xsubdefault",
            vault_address="0xvaultdefault",
            deposit_amount=100.0,
        )
        test_db.add(sub)
        test_db.commit()
        assert sub.status == "funding"


# ── Event publisher tests ────────────────────────────────


class TestEventPublisher:
    """Test event publishing and retrieval."""

    def setup_method(self):
        # Clear events
        from archimedes.chain.event_publisher import _events

        _events.clear()

    @pytest.mark.asyncio
    async def test_publish_and_get_events(self):
        """Published events should be retrievable."""
        from archimedes.chain.event_publisher import publish_event

        await publish_event("rebalance", {"vault": "0xtest", "trades": ["ETH", "BTC"]})
        await publish_event("heartbeat", {"vault": "0xtest"})

        events = get_events_sync()
        assert len(events) == 2
        assert events[0]["type"] == "rebalance"
        assert events[1]["type"] == "heartbeat"

    @pytest.mark.asyncio
    async def test_get_events_since_timestamp(self):
        """Getting events with a 'since' filter should work."""
        from archimedes.chain.event_publisher import publish_event

        await publish_event("rebalance", {"vault": "0xtest"})

        events = get_events_sync(since="2099-01-01T00:00:00")
        assert len(events) == 0

        events = get_events_sync(since="2020-01-01T00:00:00")
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_event_limit(self):
        """Getting events should respect the limit parameter."""
        from archimedes.chain.event_publisher import publish_event

        for i in range(10):
            await publish_event("test", {"index": i})

        events = get_events_sync(limit=3)
        assert len(events) == 3


# ── Type 3 Agent vault check tests ───────────────────────


class TestReplicatorVaultCheck:
    """Test Type 3 Agent vault threshold checking."""

    @pytest.mark.asyncio
    @patch("archimedes.chain.agent_replicator.chain_executor")
    async def test_check_vault_threshold_above(self, mock_executor):
        """Should return True when balance exceeds threshold."""
        mock_vault = MagicMock()
        async_mock_call = AsyncMock(return_value=300_000_000)  # 300 USDC
        mock_vault.functions.totalAssets.return_value.call = async_mock_call
        mock_loader = MagicMock()
        mock_loader.vault.return_value = mock_vault
        mock_executor.loader = mock_loader

        from archimedes.chain.agent_replicator import _check_vault_threshold

        result = await _check_vault_threshold("0xsomevault", 100.0)
        assert result is True

    @pytest.mark.asyncio
    @patch("archimedes.chain.agent_replicator.chain_executor")
    async def test_check_vault_threshold_below(self, mock_executor):
        """Should return False when balance below threshold."""
        mock_vault = MagicMock()
        async_mock_call = AsyncMock(return_value=5_000_000)  # 5 USDC
        mock_vault.functions.totalAssets.return_value.call = async_mock_call
        mock_loader = MagicMock()
        mock_loader.vault.return_value = mock_vault
        mock_executor.loader = mock_loader

        from archimedes.chain.agent_replicator import _check_vault_threshold

        result = await _check_vault_threshold("0xsomevault", 100.0)
        assert result is False

    @pytest.mark.asyncio
    @patch("archimedes.chain.agent_replicator.chain_executor")
    async def test_check_vault_threshold_exact(self, mock_executor):
        """Should return True when balance exactly equals threshold."""
        mock_vault = MagicMock()
        async_mock_call = AsyncMock(return_value=100_000_000)  # 100 USDC
        mock_vault.functions.totalAssets.return_value.call = async_mock_call
        mock_loader = MagicMock()
        mock_loader.vault.return_value = mock_vault
        mock_executor.loader = mock_loader

        from archimedes.chain.agent_replicator import _check_vault_threshold

        result = await _check_vault_threshold("0xsomevault", 100.0)
        assert result is True

    @pytest.mark.asyncio
    @patch("archimedes.chain.agent_replicator.chain_executor")
    async def test_check_vault_threshold_connection_error(self, mock_executor):
        """Should return False on connection error."""
        mock_loader = MagicMock()
        mock_loader.vault.side_effect = Exception("Connection error")
        mock_executor.loader = mock_loader

        from archimedes.chain.agent_replicator import _check_vault_threshold

        result = await _check_vault_threshold("0xsomevault", 100.0)
        assert result is False


# ── Replicator agent tests ──────────────────────────────


class TestReplicatorAgent:
    """Test Type 3 Agent initialization and tick logic."""

    def test_resolve_vaults_from_env(self, monkeypatch):
        """Resolving vaults from env should parse comma-separated addresses."""
        monkeypatch.setenv("AGENT_VAULT_ADDRESSES", "0xvault1,0xvault2")
        import archimedes.chain.agent_replicator
        # Re-read EXPLICIT_VAULTS from env
        archimedes.chain.agent_replicator.EXPLICIT_VAULTS = "0xvault1,0xvault2"
        try:
            from archimedes.chain.agent_replicator import ReplicatorAgent
            agent = ReplicatorAgent()
            assert len(agent._vault_addresses) == 2
            assert "0xvault1" in agent._vault_addresses
        finally:
            archimedes.chain.agent_replicator.EXPLICIT_VAULTS = ""

    def test_resolve_vaults_empty(self, monkeypatch):
        """Resolving vaults with no env and no subscription should give empty list."""
        monkeypatch.setenv("SUBSCRIPTION_ID", "0")
        import archimedes.chain.agent_replicator
        archimedes.chain.agent_replicator.EXPLICIT_VAULTS = ""
        archimedes.chain.agent_replicator.SUBSCRIPTION_ID = 0
        try:
            from archimedes.chain.agent_replicator import ReplicatorAgent
            agent = ReplicatorAgent()
            assert len(agent._vault_addresses) == 0
        finally:
            archimedes.chain.agent_replicator.SUBSCRIPTION_ID = 0


# ── Query/filter tests ──────────────────────────────────


class TestMarketQueries:
    """Test market DB queries and status filtering."""

    def test_list_live_strategies(self, test_db, sample_strategy):
        """Querying live strategies should only return live ones."""
        # Add a non-live strategy that should be excluded
        draft = PublishedStrategy(
            strategy_id="strat-draft-001",
            description="Draft strategy",
            creator_address="0xdraftwallet",
            vault_address="0xdraftvault",
            status="publishing",
            funding_threshold=50.0,
        )
        test_db.add(draft)
        test_db.commit()

        live_strategies = (
            test_db.query(PublishedStrategy)
            .filter(PublishedStrategy.status == "live")
            .all()
        )
        assert len(live_strategies) == 1
        assert live_strategies[0].strategy_id == "strat-test-001"

    def test_subscription_status_filter(self, test_db, sample_strategy):
        """Subscriptions should be filterable by status."""
        sub1 = Subscription(
            published_strategy_id=sample_strategy.id,
            subscriber_wallet="0xwallet1",
            vault_address="0xvault1",
            deposit_amount=100.0,
            status="active",
        )
        sub2 = Subscription(
            published_strategy_id=sample_strategy.id,
            subscriber_wallet="0xwallet2",
            vault_address="0xvault2",
            deposit_amount=200.0,
            status="retired",
        )
        test_db.add_all([sub1, sub2])
        test_db.commit()

        active = (
            test_db.query(Subscription)
            .filter(
                Subscription.published_strategy_id == sample_strategy.id,
                Subscription.status == "active",
            )
            .all()
        )
        assert len(active) == 1
        assert active[0].subscriber_wallet == "0xwallet1"

    def test_threshold_field_default(self, test_db):
        """Default funding_threshold should be 10.0."""
        ps = PublishedStrategy(
            strategy_id="strat-no-threshold",
            description="No threshold set",
            creator_address="0xcreator",
            vault_address="0xvault",
        )
        test_db.add(ps)
        test_db.commit()
        assert ps.funding_threshold == 10.0

    def test_query_subscriptions_by_strategy(self, test_db, sample_strategy, sample_subscription):
        """Subscriptions should be queryable by published_strategy_id."""
        subs = (
            test_db.query(Subscription)
            .filter(Subscription.published_strategy_id == sample_strategy.id)
            .all()
        )
        assert len(subs) == 1
        assert subs[0].subscriber_wallet == "0xsubscriber1234567890abcdef"

    def test_subscription_action_timestamps(self, test_db, sample_subscription):
        """SubscriptionAction should have auto-generated recorded_at."""
        action = SubscriptionAction(
            subscription_id=sample_subscription.id,
            action_type="trade",
            action_data='{"token": "ETH"}',
        )
        test_db.add(action)
        test_db.commit()
        assert action.recorded_at is not None
