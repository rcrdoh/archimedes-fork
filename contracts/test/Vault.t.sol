// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/Vault.sol";
import "../src/VaultFactory.sol";
import "../src/AMMRouter.sol";
import "../src/AMMPool.sol";

/// @dev Mock ERC-20 USDC for testing
contract MockUSDC is ERC20 {
    constructor() ERC20("Mock USDC", "USDC") {
        _mint(msg.sender, 10_000_000 * 10**6);
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function decimals() public pure override returns (uint8) {
        return 6;
    }
}

contract MockToken is ERC20 {
    constructor(string memory name, string memory symbol) ERC20(name, symbol) {
        _mint(msg.sender, 1_000_000 * 1e18);
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

contract VaultTest is Test {
    MockUSDC public usdc;
    AMMRouter public router;
    VaultFactory public factory;
    Vault public vault;

    MockToken public sTSLA;

    address public owner = address(0x1);
    address public alice = address(0x2);
    address public bob = address(0x3);
    address public agent = address(0x4);
    address public platformRecipient = address(0x5);

    function setUp() public {
        usdc = new MockUSDC();

        vm.prank(owner);
        router = new AMMRouter(owner);

        vm.prank(owner);
        factory = new VaultFactory(
            agent,
            address(router),
            address(usdc),
            platformRecipient,
            owner
        );

        // Fund test users
        usdc.mint(alice, 1_000_000 * 10**6);
        usdc.mint(bob, 1_000_000 * 10**6);

        // Deploy sTSLA token for rebalance testing
        sTSLA = new MockToken("Synthetic TSLA", "sTSLA");

        // Create AMM pool for USDC/sTSLA
        router.createPool(address(usdc), address(sTSLA));

        // Create a vault as agent (Tier 1)
        vm.prank(agent);
        address vaultAddr = factory.createVault(
            "Momentum Alpha",
            "vMOM",
            150,   // 1.5% management fee
            2000,  // 20% performance fee
            true   // agent assisted
        );
        vault = Vault(payable(vaultAddr));

        // Seed AMM pool with liquidity
        uint256 poolUsdc = 100_000 * 10**6;
        uint256 poolTsla = 50_000 * 1e18;

        usdc.mint(address(this), poolUsdc);
        sTSLA.mint(address(this), poolTsla);

        usdc.approve(address(router), poolUsdc);
        sTSLA.approve(address(router), poolTsla);
        router.addLiquidity(address(usdc), address(sTSLA), poolUsdc, poolTsla, 0);
    }

    // ─── Deposit Tests ───────────────────────────────────────────────

    function test_deposit_first() public {
        uint256 amount = 10_000 * 10**6;

        vm.startPrank(alice);
        usdc.approve(address(vault), amount);
        uint256 shares = vault.deposit(amount, alice);
        vm.stopPrank();

        // First deposit: 1:1 rate minus MIN_LIQUIDITY dead shares (inflation guard, #507)
        assertEq(shares, amount - vault.MIN_LIQUIDITY());
        assertEq(vault.balanceOf(alice), shares);
        assertEq(vault.balanceOf(vault.DEAD_SHARES_SINK()), vault.MIN_LIQUIDITY());
        assertEq(vault.totalSupply(), amount); // 1:1 share:asset scale preserved
        assertEq(usdc.balanceOf(address(vault)), amount);
    }

    function test_deposit_second_user() public {
        uint256 amount = 10_000 * 10**6;

        // Alice deposits first
        vm.startPrank(alice);
        usdc.approve(address(vault), amount);
        vault.deposit(amount, alice);
        vm.stopPrank();

        // Bob deposits same amount
        vm.startPrank(bob);
        usdc.approve(address(vault), amount);
        uint256 bobShares = vault.deposit(amount, bob);
        vm.stopPrank();

        // Same deposit amount should get same shares (no gains yet)
        assertEq(bobShares, amount);
        assertEq(vault.balanceOf(bob), bobShares);
    }

    function test_revert_deposit_zero() public {
        vm.prank(alice);
        vm.expectRevert(Vault.ZeroAmount.selector);
        vault.deposit(0, alice);
    }

    // ─── Withdraw Tests ──────────────────────────────────────────────

    function test_withdraw() public {
        uint256 amount = 10_000 * 10**6;

        vm.startPrank(alice);
        usdc.approve(address(vault), amount);
        vault.deposit(amount, alice);

        // First depositor's max withdraw is amount - MIN_LIQUIDITY: the dead shares
        // (inflation guard, #507) keep their pro-rata sliver of assets locked.
        uint256 withdrawable = amount - vault.MIN_LIQUIDITY();
        uint256 aliceUsdcBefore = usdc.balanceOf(alice);
        vault.withdraw(withdrawable, alice, alice);
        vm.stopPrank();

        assertEq(usdc.balanceOf(alice) - aliceUsdcBefore, withdrawable);
        assertEq(vault.balanceOf(alice), 0);
    }

    function test_redeem() public {
        uint256 amount = 10_000 * 10**6;

        vm.startPrank(alice);
        usdc.approve(address(vault), amount);
        uint256 shares = vault.deposit(amount, alice);

        uint256 aliceUsdcBefore = usdc.balanceOf(alice);
        vault.redeem(shares, alice, alice);
        vm.stopPrank();

        // shares = amount - MIN_LIQUIDITY (dead shares, #507); redeeming them all
        // returns the matching pro-rata assets at the unchanged 1:1 rate.
        assertEq(usdc.balanceOf(alice) - aliceUsdcBefore, amount - vault.MIN_LIQUIDITY());
        assertEq(vault.balanceOf(alice), 0);
    }

    function test_revert_withdraw_zero() public {
        vm.prank(alice);
        vm.expectRevert(Vault.ZeroAmount.selector);
        vault.withdraw(0, alice, alice);
    }

    // ─── Preview Functions ───────────────────────────────────────────

    function test_previewDeposit() public {
        uint256 amount = 10_000 * 10**6;
        uint256 preview = vault.previewDeposit(amount);

        vm.startPrank(alice);
        usdc.approve(address(vault), amount);
        uint256 actual = vault.deposit(amount, alice);
        vm.stopPrank();

        assertEq(preview, actual);
    }

    function test_previewRedeem() public {
        uint256 amount = 10_000 * 10**6;

        vm.startPrank(alice);
        usdc.approve(address(vault), amount);
        uint256 shares = vault.deposit(amount, alice);

        uint256 preview = vault.previewRedeem(shares);
        uint256 actual = vault.redeem(shares, alice, alice);
        vm.stopPrank();

        assertEq(preview, actual);
    }

    // ─── Inflation-Attack Tests (audit 2026-06-10 #4 / issue #507) ───

    /// @dev Classic first-depositor inflation attack: deposit 1 wei, donate USDC
    ///      directly to the vault to inflate NAV, and let the victim's deposit
    ///      round to zero shares. With MIN_LIQUIDITY dead shares the 1-wei seed
    ///      deposit is impossible and the donation is absorbed by the dead shares,
    ///      so the victim keeps ~full value and the attacker takes a massive loss.
    function test_inflation_attack_fails() public {
        uint256 minLiq = vault.MIN_LIQUIDITY();

        // Step 1: the canonical 1-wei first deposit now reverts —
        // previewDeposit(1) == 0 because MIN_LIQUIDITY is subtracted.
        vm.startPrank(bob); // bob = attacker
        usdc.approve(address(vault), type(uint256).max);
        vm.expectRevert(Vault.ZeroShares.selector);
        vault.deposit(1, bob);

        // Step 2: attacker falls back to the smallest viable first deposit
        // (MIN_LIQUIDITY + 1 wei → exactly 1 share; dead sink holds MIN_LIQUIDITY).
        uint256 attackerCost = minLiq + 1;
        uint256 attackerShares = vault.deposit(attackerCost, bob);
        assertEq(attackerShares, 1);

        // Step 3: attacker donates USDC directly to the vault to inflate NAV
        uint256 donation = 10_000 * 10**6;
        usdc.transfer(address(vault), donation);
        attackerCost += donation;
        vm.stopPrank();

        // Step 4: victim deposits
        uint256 victimDeposit = 10_000 * 10**6;
        vm.startPrank(alice); // alice = victim
        usdc.approve(address(vault), victimDeposit);
        uint256 victimShares = vault.deposit(victimDeposit, alice);
        vm.stopPrank();

        // Victim's shares MUST NOT round to zero
        assertGt(victimShares, 0);

        // Victim's redeemable value ≈ deposit (within 0.1% rounding tolerance)
        uint256 victimValue = vault.previewRedeem(victimShares);
        assertApproxEqRel(victimValue, victimDeposit, 0.001e18);

        // Attack is strictly unprofitable: the dead shares absorb
        // MIN_LIQUIDITY/(MIN_LIQUIDITY+1) of the donation, so the attacker
        // recovers only a dust fraction of what they spent.
        uint256 attackerValue = vault.previewRedeem(attackerShares);
        assertLt(attackerValue, attackerCost / 100); // lost > 99% of outlay
    }

    /// @dev Donation alone (no zero-share rounding) must not let any depositor
    ///      capture more than their pro-rata claim from a later depositor.
    function test_donation_does_not_dilute_later_depositor() public {
        uint256 amount = 10_000 * 10**6;

        // Honest first depositor
        vm.startPrank(alice);
        usdc.approve(address(vault), amount);
        vault.deposit(amount, alice);
        vm.stopPrank();

        // Third party donates to the vault
        usdc.mint(address(this), amount);
        usdc.transfer(address(vault), amount);

        // Bob deposits after the donation: his shares price in the doubled NAV,
        // and his redeemable value still ≈ his deposit.
        vm.startPrank(bob);
        usdc.approve(address(vault), amount);
        uint256 bobShares = vault.deposit(amount, bob);
        vm.stopPrank();

        assertGt(bobShares, 0);
        assertApproxEqRel(vault.previewRedeem(bobShares), amount, 0.001e18);
    }

    // ─── Rebalance Tests ─────────────────────────────────────────────

    function test_rebalance_buy_synth() public {
        uint256 depositAmount = 50_000 * 10**6;

        // Deposit USDC
        vm.prank(alice);
        usdc.approve(address(vault), depositAmount);
        vm.prank(alice);
        vault.deposit(depositAmount, alice);

        // Agent rebalances: buy sTSLA with 10,000 USDC
        uint256 swapAmount = 10_000 * 10**6;
        address[] memory tokensIn = new address[](1);
        tokensIn[0] = address(sTSLA);
        uint256[] memory amountsIn = new uint256[](1);
        amountsIn[0] = swapAmount;
        address[] memory tokensOut = new address[](0);
        uint256[] memory amountsOut = new uint256[](0);

        vm.prank(agent);
        vault.rebalance(tokensIn, amountsIn, tokensOut, amountsOut);

        // Vault should now hold sTSLA
        assertGt(sTSLA.balanceOf(address(vault)), 0);
        // Vault USDC should be reduced
        assertLt(usdc.balanceOf(address(vault)), depositAmount);
    }

    function test_revert_rebalance_unauthorized() public {
        uint256 depositAmount = 50_000 * 10**6;

        vm.prank(alice);
        usdc.approve(address(vault), depositAmount);
        vm.prank(alice);
        vault.deposit(depositAmount, alice);

        address[] memory tokensIn = new address[](0);
        uint256[] memory amountsIn = new uint256[](0);
        address[] memory tokensOut = new address[](0);
        uint256[] memory amountsOut = new uint256[](0);

        // Bob can't rebalance — he's not the creator or agent
        vm.prank(bob);
        vm.expectRevert(Vault.Unauthorized.selector);
        vault.rebalance(tokensIn, amountsIn, tokensOut, amountsOut);
    }

    function test_rebalance_creator_can_also_rebalance() public {
        uint256 depositAmount = 50_000 * 10**6;

        vm.prank(alice);
        usdc.approve(address(vault), depositAmount);
        vm.prank(alice);
        vault.deposit(depositAmount, alice);

        address[] memory tokensIn = new address[](0);
        uint256[] memory amountsIn = new uint256[](0);
        address[] memory tokensOut = new address[](0);
        uint256[] memory amountsOut = new uint256[](0);

        // Creator (agent in this case) can rebalance
        vm.prank(agent);
        vault.rebalance(tokensIn, amountsIn, tokensOut, amountsOut);
        // No tokens swapped, but no revert — success
    }

    // ─── Target Allocations ──────────────────────────────────────────

    function test_setTargetAllocations() public {
        address[] memory tokens = new address[](2);
        tokens[0] = address(usdc);
        tokens[1] = address(sTSLA);
        uint256[] memory weights = new uint256[](2);
        weights[0] = 6000; // 60%
        weights[1] = 4000; // 40%

        vm.prank(agent);
        vault.setTargetAllocations(tokens, weights);

        (address[] memory retTokens, uint256[] memory retWeights) = vault.getTargetAllocations();
        assertEq(retTokens.length, 2);
        assertEq(retWeights[0], 6000);
        assertEq(retWeights[1], 4000);
    }

    function test_revert_setTargetAllocations_invalid_sum() public {
        address[] memory tokens = new address[](1);
        tokens[0] = address(usdc);
        uint256[] memory weights = new uint256[](1);
        weights[0] = 5000; // 50% — doesn't sum to 100%

        vm.prank(agent);
        vm.expectRevert(Vault.InvalidAllocations.selector);
        vault.setTargetAllocations(tokens, weights);
    }

    function test_revert_setTargetAllocations_unauthorized() public {
        address[] memory tokens = new address[](1);
        tokens[0] = address(usdc);
        uint256[] memory weights = new uint256[](1);
        weights[0] = 10000;

        vm.prank(bob);
        vm.expectRevert(Vault.Unauthorized.selector);
        vault.setTargetAllocations(tokens, weights);
    }

    // ─── Vault Properties ────────────────────────────────────────────

    function test_vault_tier1() public view {
        assertEq(vault.tier(), 1);
        assertTrue(vault.isAgentAssisted());
        assertEq(vault.managementFeeBps(), 150);
        assertEq(vault.performanceFeeBps(), 2000);
    }

    function test_vault_creator() public view {
        assertEq(vault.creator(), agent);
    }

    function test_vault_asset() public view {
        assertEq(vault.asset(), address(usdc));
    }

    function test_totalAssets() public {
        uint256 amount = 10_000 * 10**6;

        vm.prank(alice);
        usdc.approve(address(vault), amount);
        vm.prank(alice);
        vault.deposit(amount, alice);

        assertEq(vault.totalAssets(), amount);
    }

    // ─── Fee Tests ───────────────────────────────────────────────────

    function test_management_fee_accrues() public {
        uint256 amount = 100_000 * 10**6;

        vm.prank(alice);
        usdc.approve(address(vault), amount);
        vm.prank(alice);
        vault.deposit(amount, alice);

        uint256 supplyBefore = vault.totalSupply();

        // Advance time by 365 days (1 year)
        vm.warp(block.timestamp + 365 days);

        // Trigger fee accrual via another deposit
        uint256 smallDeposit = 1000 * 10**6;
        vm.prank(bob);
        usdc.approve(address(vault), smallDeposit);
        vm.prank(bob);
        vault.deposit(smallDeposit, bob);

        // Total supply should have increased due to management fee shares
        uint256 supplyAfter = vault.totalSupply();
        assertGt(supplyAfter, supplyBefore + smallDeposit);
    }

    function test_highWaterMark_initial() public view {
        assertEq(vault.highWaterMark(), 1e18);
    }

    // ─── VaultFactory Tests ──────────────────────────────────────────

    function test_factory_create_tier1() public {
        vm.prank(agent);
        address v = factory.createVault("Tier1 Vault", "vT1", 100, 1000, true);

        assertEq(Vault(payable(v)).tier(), 1);
        assertEq(Vault(payable(v)).creator(), agent);
    }

    function test_factory_create_tier2() public {
        vm.prank(alice);
        address v = factory.createVault("Community Vault", "vCOM", 200, 1500, false);

        assertEq(Vault(payable(v)).tier(), 2);
        assertEq(Vault(payable(v)).creator(), alice);
    }

    function test_factory_getVaults() public {
        vm.prank(agent);
        factory.createVault("V1", "v1", 100, 1000, true);

        vm.prank(alice);
        factory.createVault("V2", "v2", 200, 1500, false);

        address[] memory vaults = factory.getVaults();
        assertEq(vaults.length, 3); // 1 from setUp + 2 new
    }

    function test_factory_getVaultsByCreator() public {
        vm.prank(alice);
        factory.createVault("Alice Vault", "vAL", 200, 1500, false);

        address[] memory aliceVaults = factory.getVaultsByCreator(alice);
        assertEq(aliceVaults.length, 1);

        address[] memory agentVaults = factory.getVaultsByCreator(agent);
        assertEq(agentVaults.length, 1); // from setUp
    }

    function test_factory_vaultCount() public {
        assertEq(factory.vaultCount(), 1); // from setUp

        vm.prank(alice);
        factory.createVault("V2", "v2", 200, 1500, false);
        assertEq(factory.vaultCount(), 2);
    }

    function test_factory_agentAddress() public view {
        assertEq(factory.agentAddress(), agent);
    }

    function test_factory_ammRouter() public view {
        assertEq(factory.ammRouter(), address(router));
    }

    function test_factory_usdc() public view {
        assertEq(factory.usdc(), address(usdc));
    }

    // ─── Edge Cases ──────────────────────────────────────────────────

    function test_deposit_withdraw_round_trip() public {
        uint256 amount = 10_000 * 10**6;
        uint256 aliceUsdcBefore = usdc.balanceOf(alice);

        vm.startPrank(alice);
        usdc.approve(address(vault), amount);
        vault.deposit(amount, alice);
        vault.withdraw(amount - vault.MIN_LIQUIDITY(), alice, alice);
        vm.stopPrank();

        // Alice gets her USDC back minus the one-time MIN_LIQUIDITY dead-share cost
        // (1e3 share-wei = 0.001 USDC, inflation guard #507; no fees — no time passed)
        assertEq(usdc.balanceOf(alice), aliceUsdcBefore - vault.MIN_LIQUIDITY());
    }

    function test_multiple_deposits_withdraws() public {
        uint256 amount1 = 10_000 * 10**6;
        uint256 amount2 = 20_000 * 10**6;

        // Alice deposits
        vm.startPrank(alice);
        usdc.approve(address(vault), amount1);
        vault.deposit(amount1, alice);

        // Bob deposits
        vm.startPrank(bob);
        usdc.approve(address(vault), amount2);
        vault.deposit(amount2, bob);

        // Alice withdraws her full entitlement: amount1 minus the MIN_LIQUIDITY
        // dead shares locked by her first deposit (inflation guard, #507)
        vm.startPrank(alice);
        vault.withdraw(amount1 - vault.MIN_LIQUIDITY(), alice, alice);

        // Vault retains amount2 plus the dead shares' pro-rata assets
        assertEq(vault.totalAssets(), amount2 + vault.MIN_LIQUIDITY());
        assertEq(vault.balanceOf(alice), 0);
        assertEq(vault.balanceOf(bob), amount2);
    }
}
