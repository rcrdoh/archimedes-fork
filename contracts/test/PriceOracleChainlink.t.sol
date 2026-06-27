// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/PriceOracle.sol";

/// @dev Minimal mock implementing AggregatorV3Interface so we can drive the
///      Chainlink read path deterministically — feed answer, decimals, and the
///      round metadata (roundId / updatedAt / answeredInRound) are all settable.
contract MockAggregator is AggregatorV3Interface {
    uint8 internal _decimals;
    int256 internal _answer;
    uint80 internal _roundId;
    uint256 internal _updatedAt;
    uint80 internal _answeredInRound;

    constructor(uint8 d, int256 answer, uint256 updatedAt) {
        _decimals = d;
        _answer = answer;
        _updatedAt = updatedAt;
        _roundId = 1;
        _answeredInRound = 1;
    }

    function decimals() external view override returns (uint8) {
        return _decimals;
    }

    bool internal _shouldRevert;

    function latestRoundData()
        external
        view
        override
        returns (uint80, int256, uint256, uint256, uint80)
    {
        if (_shouldRevert) revert("feed down");
        return (_roundId, _answer, _updatedAt, _updatedAt, _answeredInRound);
    }

    // ── Test setters ─────────────────────────────────────────────
    function setShouldRevert(bool r) external {
        _shouldRevert = r;
    }

    function setAnswer(int256 a) external {
        _answer = a;
    }

    function setUpdatedAt(uint256 t) external {
        _updatedAt = t;
    }

    function setRound(uint80 roundId, uint80 answeredInRound) external {
        _roundId = roundId;
        _answeredInRound = answeredInRound;
    }
}

/// @dev T1.3 — Chainlink-first read-path tests for PriceOracle.
///      Covers: feed-backed read (with 8→6 decimal scaling), staleness rejection,
///      admin fallback when no feed is configured, and the funds-safety guards
///      (negative/zero answer, incomplete round, carried-over stale round,
///      decimals overflow bound). The no-arg getPrice() signature is preserved,
///      so these assertions exercise the exact path Vault/SyntheticVault read.
contract PriceOracleChainlinkTest is Test {
    PriceOracle public oracle;
    MockAggregator public feed;

    address public owner = address(0x1);
    address public alice = address(0x2);

    uint256 constant INITIAL_PRICE = 392_600_000; // $392.60 (6 dec, admin-fed)

    // Chainlink USD feeds report 8 decimals. $392.60 → 39_260_000_000.
    uint8 constant FEED_DECIMALS = 8;
    int256 constant FEED_ANSWER = 39_260_000_000; // $392.60 @ 8 dec
    uint256 constant EXPECTED_6DEC = 392_600_000; // $392.60 @ 6 dec (scaled down)

    function setUp() public {
        // Pin a baseline well above MAX_STALENESS so "now - updatedAt" arithmetic
        // is unambiguous and we can warp backward/forward freely.
        vm.warp(1_000_000);
        vm.prank(owner);
        oracle = new PriceOracle("TSLA", INITIAL_PRICE, owner);
        feed = new MockAggregator(FEED_DECIMALS, FEED_ANSWER, block.timestamp);
    }

    // ─── Admin fallback (no feed configured) ─────────────────────────

    function test_admin_fallback_when_no_feed() public view {
        // Default state: no feed set → getPrice() returns the admin-fed value.
        assertEq(address(oracle.priceFeed()), address(0));
        assertEq(oracle.getPrice(), INITIAL_PRICE);
        assertTrue(oracle.isFresh());
    }

    function test_admin_fallback_reverts_when_stale() public {
        // Warp past MAX_STALENESS with no feed → admin path reverts StalePrice.
        vm.warp(block.timestamp + oracle.MAX_STALENESS() + 1);
        vm.expectRevert(PriceOracle.StalePrice.selector);
        oracle.getPrice();
        assertFalse(oracle.isFresh());
    }

    // ─── Feed-backed read ────────────────────────────────────────────

    function test_feed_backed_read_scales_8dec_to_6dec() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        assertEq(address(oracle.priceFeed()), address(feed));
        // 8-decimal $392.60 feed answer → 6-decimal 392_600_000.
        assertEq(oracle.getPrice(), EXPECTED_6DEC);
        assertTrue(oracle.isFresh());
    }

    function test_feed_takes_precedence_over_admin_price() public {
        // Admin price is $392.60; point the feed at a *different* value ($500)
        // and confirm getPrice() returns the FEED value, proving precedence.
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        feed.setAnswer(50_000_000_000); // $500.00 @ 8 dec
        assertEq(oracle.getPrice(), 500_000_000); // $500.00 @ 6 dec
        // Admin-fed `price` storage is untouched.
        assertEq(oracle.price(), INITIAL_PRICE);
    }

    function test_feed_with_6_decimals_no_scaling() public {
        MockAggregator feed6 = new MockAggregator(6, 392_600_000, block.timestamp);
        vm.prank(owner);
        oracle.setPriceFeed(address(feed6));
        assertEq(oracle.getPrice(), 392_600_000);
    }

    function test_feed_with_sub6_decimals_scales_up() public {
        // 2-decimal feed: $392.60 → 39260 @ 2 dec → 392_600_000 @ 6 dec.
        MockAggregator feed2 = new MockAggregator(2, 39_260, block.timestamp);
        vm.prank(owner);
        oracle.setPriceFeed(address(feed2));
        assertEq(oracle.getPrice(), 392_600_000);
    }

    function test_clearing_feed_reverts_to_admin() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        assertEq(oracle.getPrice(), EXPECTED_6DEC);
        // Clear the feed → back to the admin-fed value.
        vm.prank(owner);
        oracle.setPriceFeed(address(0));
        assertEq(address(oracle.priceFeed()), address(0));
        assertEq(oracle.getPrice(), INITIAL_PRICE);
    }

    // ─── Staleness rejection (the core T1.3 funds-safety check) ──────

    function test_feed_stale_beyond_heartbeat_degrades_to_admin() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        uint256 feedTs = block.timestamp; // 1_000_000 (pinned in setUp)
        feed.setUpdatedAt(feedTs);
        // Past the per-feed heartbeat but the admin reference is still fresh: the feed
        // is ignored and getPrice() DEGRADES to the admin value (not a hard revert).
        vm.warp(feedTs + oracle.feedStaleness() + 1);
        assertEq(oracle.getPrice(), oracle.price());
        assertTrue(oracle.isFresh()); // admin fallback is fresh
    }

    function test_feed_stale_and_admin_stale_reverts() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        uint256 feedTs = block.timestamp;
        feed.setUpdatedAt(feedTs);
        // Both the feed (past heartbeat) and the admin (past MAX_STALENESS) are stale →
        // only now does getPrice() revert.
        vm.warp(feedTs + oracle.MAX_STALENESS() + 1);
        vm.expectRevert(PriceOracle.StalePrice.selector);
        oracle.getPrice();
        assertFalse(oracle.isFresh());
    }

    function test_feed_fresh_at_exact_heartbeat_boundary() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        // updatedAt exactly feedStaleness ago is still fresh (strict > check).
        uint256 ts = block.timestamp;
        feed.setUpdatedAt(ts);
        vm.warp(ts + oracle.feedStaleness());
        assertEq(oracle.getPrice(), EXPECTED_6DEC);
    }

    // ─── Other funds-safety guards (now DEGRADE to admin, #724 review) ──

    function test_feed_negative_answer_degrades_to_admin() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        feed.setAnswer(-1);
        // A bad feed answer no longer bricks the read — it degrades to the admin price.
        assertEq(oracle.getPrice(), oracle.price());
    }

    function test_feed_zero_answer_degrades_to_admin() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        feed.setAnswer(0);
        assertEq(oracle.getPrice(), oracle.price());
    }

    function test_feed_incomplete_round_degrades_to_admin() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        feed.setUpdatedAt(0); // round not yet answered
        assertEq(oracle.getPrice(), oracle.price());
    }

    function test_feed_carried_over_round_degrades_to_admin() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        feed.setRound(5, 4); // answeredInRound < roundId → carried-over answer
        assertEq(oracle.getPrice(), oracle.price());
    }

    // ─── setPriceFeed access + validation ────────────────────────────

    function test_setPriceFeed_emits_event() public {
        vm.expectEmit(false, false, false, true);
        emit PriceOracle.PriceFeedChanged(address(0), address(feed));
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
    }

    function test_revert_setPriceFeed_non_owner() public {
        vm.prank(alice);
        vm.expectRevert(); // Ownable: OwnableUnauthorizedAccount
        oracle.setPriceFeed(address(feed));
    }

    function test_revert_setPriceFeed_decimals_too_large() public {
        MockAggregator badFeed = new MockAggregator(37, 1, block.timestamp);
        vm.expectRevert(abi.encodeWithSelector(PriceOracle.InvalidFeedDecimals.selector, uint8(37)));
        vm.prank(owner);
        oracle.setPriceFeed(address(badFeed));
    }

    function test_setPriceFeed_decimals_at_bound_allowed() public {
        // 36 decimals is the inclusive upper bound — accepted at config time.
        MockAggregator boundFeed = new MockAggregator(36, 1, block.timestamp);
        vm.prank(owner);
        oracle.setPriceFeed(address(boundFeed));
        assertEq(address(oracle.priceFeed()), address(boundFeed));
    }

    function test_setPriceFeed_caches_decimals() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        assertEq(oracle.feedDecimals(), FEED_DECIMALS);
        // Cleared back to 0 when the feed is removed.
        vm.prank(owner);
        oracle.setPriceFeed(address(0));
        assertEq(oracle.feedDecimals(), 0);
    }

    // ─── #724-review hardening: degrade + sanity band + heartbeat ─────

    function test_feed_reverts_degrades_to_admin() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        feed.setShouldRevert(true);
        // A feed whose latestRoundData() reverts (paused / self-destructed) is caught and
        // degrades to the admin fallback — NOT a hard revert that bricks every consumer.
        assertEq(oracle.getPrice(), oracle.price());
        assertTrue(oracle.isFresh());
    }

    function test_feed_future_updatedAt_degrades_to_admin() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        // A feed reporting a timestamp in the FUTURE is malformed round metadata — it must
        // degrade to admin (fail-soft), not be treated as fresh (#724 review).
        feed.setUpdatedAt(block.timestamp + 1 hours);
        assertEq(oracle.getPrice(), oracle.price());
        assertTrue(oracle.isFresh()); // admin fallback is fresh
    }

    function test_feed_huge_answer_out_of_band_degrades_no_overflow() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed)); // 8-decimal feed
        // A malicious answer near int256 max scales to an enormous price. The sanity-band
        // comparison must NOT overflow-and-revert (which would brick getPrice) — it falls
        // out of band and degrades to admin (#724 review: overflow-safe band).
        feed.setAnswer(type(int256).max);
        assertEq(oracle.getPrice(), oracle.price());
    }

    function test_feed_upscale_overflow_degrades_no_revert() public {
        // Sub-6-decimal feed: a huge answer would overflow `raw * 10**(6-d)` INSIDE the try
        // block (uncaught → getPrice revert). The bounds check degrades instead (#724 review).
        MockAggregator feed2 = new MockAggregator(2, type(int256).max, block.timestamp);
        vm.prank(owner);
        oracle.setPriceFeed(address(feed2));
        assertEq(oracle.getPrice(), oracle.price());
    }

    function test_ratcheted_huge_admin_price_band_no_overflow() public {
        // The OTHER band factor: a ratcheted-large admin `price` must not overflow
        // `price * maxFeedDeviationBps` and brick getPrice even when the FEED reads clean
        // (#724 review round-3). Construct an oracle with an absurd admin price, point it at
        // a valid fresh feed, and confirm the band guard degrades (returns admin) — no revert.
        PriceOracle huge = new PriceOracle("HUGE", type(uint256).max, owner);
        vm.prank(owner);
        huge.setPriceFeed(address(feed)); // valid 8-dec feed, fresh (updatedAt == now)
        // price * maxFeedDeviationBps would overflow uint256 → band uncomputable → degrade.
        assertEq(huge.getPrice(), type(uint256).max);
    }

    function test_feed_out_of_band_degrades_to_admin() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        // Admin reference is $392.60; point the feed at $5000 (a ~12x wrong-denomination-
        // style error) — well outside the 50% band → getPrice() ignores the feed.
        feed.setAnswer(500_000_000_000); // $5000 @ 8 dec
        assertEq(oracle.getPrice(), oracle.price());
    }

    function test_feed_in_band_uses_feed() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        // $450 vs admin $392.60 ≈ +14.6% — inside the 50% band → the live feed wins.
        feed.setAnswer(45_000_000_000); // $450 @ 8 dec
        assertEq(oracle.getPrice(), 450_000_000);
    }

    function test_band_disabled_trusts_feed_out_of_band() public {
        vm.startPrank(owner);
        oracle.setMaxFeedDeviationBps(0); // disable the band
        oracle.setPriceFeed(address(feed));
        vm.stopPrank();
        feed.setAnswer(500_000_000_000); // $5000 — would be out of band
        assertEq(oracle.getPrice(), 5_000_000_000); // band off → feed trusted
    }

    function test_band_skipped_when_admin_stale_trusts_feed() public {
        vm.prank(owner);
        oracle.setPriceFeed(address(feed));
        // Admin reference goes stale (> MAX_STALENESS) but the feed stays fresh; the band
        // can't sanity-check against a stale reference, so the in-heartbeat feed is trusted.
        uint256 ts = block.timestamp;
        vm.warp(ts + oracle.MAX_STALENESS() + 1);
        feed.setUpdatedAt(block.timestamp); // feed itself is fresh
        feed.setAnswer(500_000_000_000); // out-of-band vs the (now stale) admin price
        assertEq(oracle.getPrice(), 5_000_000_000); // admin stale → band skipped → feed
    }

    function test_post_scale_zero_degrades_to_admin() public {
        // An 18-decimal feed reporting 1 wei floors to 0 at 6 decimals → degrade.
        MockAggregator feed18 = new MockAggregator(18, 1, block.timestamp);
        vm.prank(owner);
        oracle.setPriceFeed(address(feed18));
        assertEq(oracle.getPrice(), oracle.price());
    }

    function test_setFeedStaleness_bounds_and_access() public {
        uint256 tooLong = oracle.MAX_STALENESS() + 1; // read view BEFORE arming expectRevert
        vm.prank(owner);
        oracle.setFeedStaleness(2 hours);
        assertEq(oracle.feedStaleness(), 2 hours);
        vm.prank(owner);
        vm.expectRevert(PriceOracle.InvalidFeedStaleness.selector);
        oracle.setFeedStaleness(0);
        vm.prank(owner);
        vm.expectRevert(PriceOracle.InvalidFeedStaleness.selector);
        oracle.setFeedStaleness(tooLong);
        vm.prank(alice);
        vm.expectRevert(); // onlyOwner
        oracle.setFeedStaleness(2 hours);
    }

    function test_setMaxFeedDeviationBps_and_access() public {
        vm.prank(owner);
        oracle.setMaxFeedDeviationBps(2000);
        assertEq(oracle.maxFeedDeviationBps(), 2000);
        vm.prank(alice);
        vm.expectRevert(); // onlyOwner
        oracle.setMaxFeedDeviationBps(1000);
    }
}
