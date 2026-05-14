// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/PriceOracle.sol";
import "../src/SyntheticToken.sol";
import "../src/SyntheticVault.sol";
import "../src/AMMRouter.sol";
import "../src/AMMPool.sol";
import "../src/Vault.sol";
import "../src/VaultFactory.sol";
import "../src/ReasoningTraceRegistry.sol";
import "../src/AssetRegistry.sol";

/// @notice Deploy the full Archimedes ecosystem to Arc testnet.
///         Usage:
///           forge script script/Deploy.s.sol --rpc-url arc-testnet --broadcast
///
///         Required env vars:
///           DEPLOYER_KEY     — private key of the deployer
///           OWNER_ADDRESS    — address that will own the contracts
///           AGENT_ADDRESS    — platform agent address (creates Tier 1 vaults)
///
///         Arc Testnet USDC: 0x3600000000000000000000000000000000000000
contract DeployScript is Script {
    // Arc Testnet USDC (ERC-20 interface)
    address constant USDC_ARC_TESTNET = 0x3600000000000000000000000000000000000000;

    // ─── Synthetic asset definitions ─────────────────────────────────

    string[] syntheticNames  = ["Synthetic TSLA", "Synthetic NVDA", "Synthetic SPY", "Synthetic BTC", "Synthetic GOLD"];
    string[] syntheticSymbols = ["sTSLA", "sNVDA", "sSPY", "sBTC", "sGOLD"];
    uint256[] initialPrices  = [
        392_600_000,    // TSLA @ $392.60
        135_000_000,    // NVDA @ $135.00
        528_500_000,    // SPY @ $528.50
        103_000_000_000, // BTC @ $103,000
        3_215_000_000   // GOLD @ $3,215.00
    ];

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address owner = vm.envAddress("OWNER_ADDRESS");
        address agentAddr = vm.envAddress("AGENT_ADDRESS");
        address platformRecipient = owner; // Platform fees go to owner initially

        vm.startBroadcast(deployerKey);

        // ═══════════════════════════════════════════════════════════════
        // Phase 1: Core Infrastructure
        // ═══════════════════════════════════════════════════════════════

        console.log("=== Phase 1: Core Infrastructure ===");

        // 1. Deploy AMM Router
        AMMRouter ammRouter = new AMMRouter(owner);
        console.log("AMMRouter deployed:", address(ammRouter));

        // 2. Deploy ReasoningTraceRegistry
        ReasoningTraceRegistry traceRegistry = new ReasoningTraceRegistry(owner);
        console.log("ReasoningTraceRegistry deployed:", address(traceRegistry));

        // 3. Deploy AssetRegistry
        AssetRegistry assetRegistry = new AssetRegistry(owner);
        console.log("AssetRegistry deployed:", address(assetRegistry));

        // 4. Deploy VaultFactory
        VaultFactory vaultFactory = new VaultFactory(
            agentAddr,
            address(ammRouter),
            USDC_ARC_TESTNET,
            platformRecipient,
            owner
        );
        console.log("VaultFactory deployed:", address(vaultFactory));

        // ═══════════════════════════════════════════════════════════════
        // Phase 2: Synthetic Assets
        // ═══════════════════════════════════════════════════════════════

        console.log("");
        console.log("=== Phase 2: Synthetic Assets ===");

        address[] memory oracleAddrs = new address[](syntheticNames.length);
        address[] memory synthTokenAddrs = new address[](syntheticNames.length);
        address[] memory synthVaultAddrs = new address[](syntheticNames.length);

        for (uint256 i = 0; i < syntheticNames.length; i++) {
            // Deploy oracle
            PriceOracle oracle = new PriceOracle(
                syntheticSymbols[i],
                initialPrices[i],
                owner
            );
            oracleAddrs[i] = address(oracle);

            // Deploy synthetic token
            SyntheticToken synthToken = new SyntheticToken(
                syntheticNames[i],
                syntheticSymbols[i],
                owner
            );
            synthTokenAddrs[i] = address(synthToken);

            // Deploy per-asset vault
            SyntheticVault synthVault = new SyntheticVault(
                USDC_ARC_TESTNET,
                address(synthToken),
                address(oracle),
                owner
            );
            synthVaultAddrs[i] = address(synthVault);

            // Set vault as minter/burner
            synthToken.setVault(address(synthVault));

            // Register in AssetRegistry
            assetRegistry.registerSynthetic(
                address(synthToken),
                keccak256(bytes(syntheticSymbols[i])),
                abi.encode(syntheticNames[i], syntheticSymbols[i])
            );

            console.log(string.concat(syntheticSymbols[i], " oracle:"), address(oracle));
            console.log(string.concat(syntheticSymbols[i], " token:"), address(synthToken));
            console.log(string.concat(syntheticSymbols[i], " vault:"), address(synthVault));
        }

        // ═══════════════════════════════════════════════════════════════
        // Phase 3: AMM Pools (each synthetic paired with USDC)
        // ═══════════════════════════════════════════════════════════════

        console.log("");
        console.log("=== Phase 3: AMM Pools ===");

        for (uint256 i = 0; i < syntheticNames.length; i++) {
            address pool = ammRouter.createPool(USDC_ARC_TESTNET, synthTokenAddrs[i]);
            console.log(string.concat(syntheticSymbols[i], "/USDC pool:"), pool);
        }

        // ═══════════════════════════════════════════════════════════════
        // Phase 4: Tier 1 Vault (agent-created)
        // ═══════════════════════════════════════════════════════════════

        console.log("");
        console.log("=== Phase 4: Tier 1 Vault ===");

        // Note: This must be called by agentAddr. If deployer != agent, skip and log.
        if (vm.addr(deployerKey) == agentAddr) {
            address tier1Vault = vaultFactory.createVault(
                "Archimedes Momentum Alpha",
                "vMOM",
                150,   // 1.5% management fee
                2000,  // 20% performance fee
                true   // agent assisted
            );
            console.log("Tier 1 vault:", tier1Vault);

            // Register in AssetRegistry
            assetRegistry.registerVault(
                tier1Vault,
                1,
                abi.encode("Archimedes Momentum Alpha", "vMOM", uint16(150), uint16(2000))
            );
        } else {
            console.log("!!! Deployer != agent. Create Tier 1 vault manually !!!");
            console.log("  vaultFactory.createVault('Archimedes Momentum Alpha', 'vMOM', 150, 2000, true)");
        }

        vm.stopBroadcast();

        // ═══════════════════════════════════════════════════════════════
        // Summary
        // ═══════════════════════════════════════════════════════════════

        console.log("");
        console.log("=== Deployment Summary ===");
        console.log("USDC (existing):       ", USDC_ARC_TESTNET);
        console.log("AMMRouter:             ", address(ammRouter));
        console.log("ReasoningTraceRegistry:", address(traceRegistry));
        console.log("AssetRegistry:         ", address(assetRegistry));
        console.log("VaultFactory:          ", address(vaultFactory));
        console.log("Owner:                 ", owner);
        console.log("Agent:                 ", agentAddr);
        console.log("");
        console.log("Synthetic assets:");
        for (uint256 i = 0; i < syntheticNames.length; i++) {
            console.log(string.concat("  ", syntheticSymbols[i], ":"), synthTokenAddrs[i]);
        }
    }
}
