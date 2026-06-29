# pip install titanoboa  (not in requirements.txt — deploy/test tool only)

"""Titanoboa-based tests for PaymentSplitter and SubscriptionManager contract fixes.

These tests run in titanoboa's in-process EVM — no Arc RPC, no .env, no
Circle credentials. They prove both contract fixes are correct before
any on-chain deployment.
"""

import pytest
import boa

# ── Mock ERC-20 (minimal USDC) ────────────────────────────────────────────

MOCK_USDC_SRC = """
# @version ^0.4.0
name: public(String[32])
symbol: public(String[8])
decimals: public(uint8)
totalSupply: public(uint256)
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])

@deploy
def __init__():
    self.name = "Mock USDC"
    self.symbol = "USDC"
    self.decimals = 6

@external
def mint(to: address, amount: uint256):
    self.balanceOf[to] += amount
    self.totalSupply += amount

@external
def transfer(to: address, amount: uint256) -> bool:
    self.balanceOf[msg.sender] -= amount
    self.balanceOf[to] += amount
    return True

@external
def transferFrom(sender: address, to: address, amount: uint256) -> bool:
    self.allowance[sender][msg.sender] -= amount
    self.balanceOf[sender] -= amount
    self.balanceOf[to] += amount
    return True

@external
def approve(spender: address, amount: uint256) -> bool:
    self.allowance[msg.sender][spender] = amount
    return True
"""

PAYMENT_SPLITTER_PATH = "contracts/vyper/PaymentSplitter.vy"
SUBSCRIPTION_MGR_PATH = "contracts/vyper/SubscriptionManager.vy"
FLAT_FEE = 100  # 100 raw USDC = $0.0001


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def usdc():
    return boa.loads(MOCK_USDC_SRC)


@pytest.fixture
def payment_splitter(usdc):
    return boa.load(PAYMENT_SPLITTER_PATH, usdc.address)


@pytest.fixture
def subscription_manager(payment_splitter, usdc):
    return boa.load(
        SUBSCRIPTION_MGR_PATH, payment_splitter.address, usdc.address, FLAT_FEE
    )


@pytest.fixture
def accounts():
    return [boa.env.generate_address() for _ in range(4)]
    # [0]=creator, [1]=platform, [2]=subscriber, [3]=other


@pytest.fixture
def pool_id():
    return b"\x01" * 32


# ── PaymentSplitter — split() fix ────────────────────────────────────────


class TestPaymentSplitterSplit:
    def test_split_transfers_90_to_creator(self, usdc, payment_splitter,
                                            subscription_manager, accounts, pool_id):
        """After chargeActions, creator receives 90% of the fee amount."""
        creator, platform, subscriber, _ = accounts

        # Setup: createPool, mint tokens, subscribe, approve
        payment_splitter.createPool(pool_id, creator, platform, sender=payment_splitter.owner())

        usdc.mint(subscriber, 10_000_000)
        usdc.approve(subscription_manager.address, 10_000_000, sender=subscriber)

        sub_id = subscription_manager.subscribe(
            pool_id, "http://example.com/events", 10_000_000, sender=subscriber
        )

        creator_balance_before = usdc.balanceOf(creator)
        subscription_manager.chargeActions(sub_id, 10, sender=creator)
        creator_balance_after = usdc.balanceOf(creator)

        expected_charge = 10 * FLAT_FEE  # 1000
        expected_creator_share = expected_charge * 90 // 100  # 900
        assert creator_balance_after - creator_balance_before == expected_creator_share, \
            f"Creator should receive {expected_creator_share}, got {creator_balance_after - creator_balance_before}"

    def test_split_transfers_10_to_platform(self, usdc, payment_splitter,
                                             subscription_manager, accounts, pool_id):
        """Platform receives 10% of the fee amount."""
        creator, platform, subscriber, _ = accounts

        payment_splitter.createPool(pool_id, creator, platform, sender=payment_splitter.owner())

        usdc.mint(subscriber, 10_000_000)
        usdc.approve(subscription_manager.address, 10_000_000, sender=subscriber)

        sub_id = subscription_manager.subscribe(
            pool_id, "http://example.com/events", 10_000_000, sender=subscriber
        )

        platform_balance_before = usdc.balanceOf(platform)
        subscription_manager.chargeActions(sub_id, 10, sender=creator)
        platform_balance_after = usdc.balanceOf(platform)

        expected_charge = 10 * FLAT_FEE
        expected_platform_share = expected_charge - (expected_charge * 90 // 100)  # 100
        assert platform_balance_after - platform_balance_before == expected_platform_share, \
            f"Platform should receive {expected_platform_share}, got {platform_balance_after - platform_balance_before}"

    def test_split_does_not_require_approval_from_subscription_manager(
            self, usdc, payment_splitter, subscription_manager, accounts, pool_id):
        """chargeActions succeeds WITHOUT any USDC.approve() from SM to PS.

        This directly proves the fix: transferFrom required an allowance;
        transfer does not.
        """
        creator, platform, subscriber, _ = accounts

        payment_splitter.createPool(pool_id, creator, platform, sender=payment_splitter.owner())

        usdc.mint(subscriber, 10_000_000)
        usdc.approve(subscription_manager.address, 10_000_000, sender=subscriber)

        sub_id = subscription_manager.subscribe(
            pool_id, "http://example.com/events", 10_000_000, sender=subscriber
        )

        # No approve call from subscription_manager to payment_splitter
        # chargeActions should still succeed (proving transfer works)
        subscription_manager.chargeActions(sub_id, 10, sender=creator)

        # Post-conditions
        expected_charge = 10 * FLAT_FEE
        expected_creator_share = expected_charge * 90 // 100
        assert usdc.balanceOf(creator) == expected_creator_share

    def test_split_reverts_on_inactive_pool(self, usdc, payment_splitter,
                                             subscription_manager, accounts, pool_id):
        """Calling split() on a deactivated pool reverts with 'pool not active'."""
        creator, platform, subscriber, _ = accounts

        payment_splitter.createPool(pool_id, creator, platform, sender=payment_splitter.owner())

        usdc.mint(subscriber, 10_000_000)
        usdc.approve(subscription_manager.address, 10_000_000, sender=subscriber)

        sub_id = subscription_manager.subscribe(
            pool_id, "http://example.com/events", 10_000_000, sender=subscriber
        )

        # Deactivate pool after subscription is created
        payment_splitter.deactivatePool(pool_id, sender=payment_splitter.owner())

        with pytest.raises(Exception) as excinfo:
            subscription_manager.chargeActions(sub_id, 10, sender=creator)
        assert "pool not active" in str(excinfo.value)


# ── SubscriptionManager — subscribe() pool validation fix ─────────────────


class TestSubscriptionManagerPoolValidation:
    def test_subscribe_reverts_on_nonexistent_pool(
            self, subscription_manager, accounts):
        """subscribe() with a pool_id that was never passed to createPool() reverts."""
        _, _, subscriber, _ = accounts

        phantom_pool = b"\xde" * 32
        with pytest.raises(Exception) as excinfo:
            subscription_manager.subscribe(
                phantom_pool, "http://example.com/events", 0, sender=subscriber
            )
        assert "pool not active" in str(excinfo.value)

    def test_subscribe_reverts_on_deactivated_pool(
            self, usdc, payment_splitter, subscription_manager, accounts, pool_id):
        """subscribe() with a pool that was created then deactivated reverts."""
        creator, platform, subscriber, _ = accounts

        payment_splitter.createPool(pool_id, creator, platform, sender=payment_splitter.owner())
        payment_splitter.deactivatePool(pool_id, sender=payment_splitter.owner())

        with pytest.raises(Exception) as excinfo:
            subscription_manager.subscribe(
                pool_id, "http://example.com/events", 0, sender=subscriber
            )
        assert "pool not active" in str(excinfo.value)

    def test_subscribe_succeeds_on_active_pool(
            self, usdc, payment_splitter, subscription_manager, accounts, pool_id):
        """subscribe() with a valid active pool_id returns a non-zero sub_id
        and the subscription is stored with active=True."""
        creator, platform, subscriber, _ = accounts

        payment_splitter.createPool(pool_id, creator, platform, sender=payment_splitter.owner())

        sub_id = subscription_manager.subscribe(
            pool_id, "http://example.com/events", 0, sender=subscriber
        )

        assert sub_id != b"\x00" * 32
        sub = subscription_manager.subscriptions(sub_id)
        assert sub.active is True

    def test_full_charge_flow_end_to_end(
            self, usdc, payment_splitter, subscription_manager, accounts, pool_id):
        """createPool → subscribe → chargeActions completes without revert,
        creator and platform receive correct USDC amounts, subscriber
        ephemeral wallet balance decreases by the charged amount."""
        creator, platform, subscriber, _ = accounts

        # Create pool
        payment_splitter.createPool(pool_id, creator, platform, sender=payment_splitter.owner())

        # Mint and subscribe
        deposit = 10_000_000
        usdc.mint(subscriber, deposit)
        usdc.approve(subscription_manager.address, deposit, sender=subscriber)

        sub_id = subscription_manager.subscribe(
            pool_id, "http://example.com/events", deposit, sender=subscriber
        )

        # Record balances BEFORE chargeActions
        creator_balance_before = usdc.balanceOf(creator)
        platform_balance_before = usdc.balanceOf(platform)
        # subscriber balance is 0 after subscribe transferred tokens into SM
        subscriber_balance_before = usdc.balanceOf(subscriber)

        action_count = 5
        subscription_manager.chargeActions(sub_id, action_count, sender=creator)

        total_charge = action_count * FLAT_FEE  # 500
        creator_share = total_charge * 90 // 100  # 450
        platform_share = total_charge - creator_share  # 50

        # Creator received 90%
        assert usdc.balanceOf(creator) - creator_balance_before == creator_share
        # Platform received 10%
        assert usdc.balanceOf(platform) - platform_balance_before == platform_share
        # Subscriber balance unchanged after subscribe (tokens moved to SM then to splitter)
        # subscriber_balance_before is 0 because subscribe() already transferred the deposit
        assert usdc.balanceOf(subscriber) == subscriber_balance_before

        # Ephemeral wallet balance decreased by the charged amount
        sub = subscription_manager.subscriptions(sub_id)
        assert sub.reserved_usdc == deposit - total_charge

        # Pool totals updated
        pool = payment_splitter.pools(pool_id)
        assert pool.total_collected == total_charge
        assert pool.total_disbursed == total_charge
