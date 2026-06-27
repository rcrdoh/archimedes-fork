// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/PriceOracle.sol";
import "../src/SyntheticToken.sol";
import "../src/SyntheticVault.sol";
import "../src/SyntheticFactory.sol";
import "../src/AMMRouter.sol";
import "../src/Vault.sol";
import "../src/VaultFactory.sol";
import "../src/ReasoningTraceRegistry.sol";
import "../src/AssetRegistry.sol";
import "../src/generated/SyntheticUniverse.sol";

/// @notice Deploy the full Archimedes ecosystem to Arc testnet.
///         Usage:
///           forge script script/Deploy.s.sol --rpc-url arc-testnet --broadcast
///
///         Required env vars:
///           DEPLOYER_KEY     — private key of the deployer
///           OWNER_ADDRESS    — address that will own the contracts
///           AGENT_ADDRESS    — platform agent address (creates Tier 1 vaults)
///
///         Optional env vars:
///           SEED_LIQUIDITY   — "true" to seed AMM pools (default: false)
///
///         Arc Testnet USDC: 0x3600000000000000000000000000000000000000
contract DeployScript is Script {
    address constant USDC_ARC_TESTNET = 0x3600000000000000000000000000000000000000;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address owner = vm.envAddress("OWNER_ADDRESS");
        address agentAddr = vm.envAddress("AGENT_ADDRESS");

        vm.startBroadcast(deployerKey);

        // ═══════════════════════════════════════════════════════════════
        // Phase 1: Core Infrastructure
        // ═══════════════════════════════════════════════════════════════

        console.log("=== Phase 1: Core Infrastructure ===");

        AMMRouter ammRouter = new AMMRouter(owner);
        console.log("AMMRouter:", address(ammRouter));

        SyntheticFactory synthFactory = new SyntheticFactory(USDC_ARC_TESTNET, owner);
        console.log("SyntheticFactory:", address(synthFactory));

        ReasoningTraceRegistry traceRegistry = new ReasoningTraceRegistry(owner);
        console.log("ReasoningTraceRegistry:", address(traceRegistry));

        AssetRegistry assetRegistry = new AssetRegistry(owner);
        console.log("AssetRegistry:", address(assetRegistry));

        VaultFactory vaultFactory = new VaultFactory(
            agentAddr,
            address(ammRouter),
            USDC_ARC_TESTNET,
            address(traceRegistry),
            owner,
            owner
        );
        console.log("VaultFactory:", address(vaultFactory));

        // ═══════════════════════════════════════════════════════════════
        // Phase 2: Synthetic Assets (via factory)
        // ═══════════════════════════════════════════════════════════════

        console.log("");
        console.log("=== Phase 2: Synthetic Assets ===");

        // The synthetic set is GENERATED from the SSOT
        // (backend/archimedes/data/synthetic_universe.json) so this forge deploy can never
        // drift from it (#756) — regenerate via
        // `python -m archimedes.scripts.gen_solidity_universe`.
        (
            string[] memory syntheticNames,
            string[] memory syntheticSymbols,
            uint256[] memory initialPrices
        ) = SyntheticUniverse.synthetics();

        address[] memory synthTokens = new address[](syntheticNames.length);
        address[] memory synthOracles = new address[](syntheticNames.length);

        for (uint256 i = 0; i < syntheticNames.length; i++) {
            // Deploy oracle first (factory needs the address)
            PriceOracle oracle = new PriceOracle(syntheticSymbols[i], initialPrices[i], owner);
            synthOracles[i] = address(oracle);

            // Create synthetic via factory
            address token = synthFactory.createSynthetic(
                syntheticNames[i],
                syntheticSymbols[i],
                address(oracle)
            );
            synthTokens[i] = token;

            // Register in AssetRegistry
            assetRegistry.registerSynthetic(
                token,
                keccak256(bytes(syntheticSymbols[i])),
                abi.encode(syntheticNames[i], syntheticSymbols[i])
            );

            console.log(string.concat(syntheticSymbols[i], " token:"), token);
        }

        // ═══════════════════════════════════════════════════════════════
        // Phase 3: AMM Pools (each synthetic paired with USDC)
        // ═══════════════════════════════════════════════════════════════

        console.log("");
        console.log("=== Phase 3: AMM Pools ===");

        for (uint256 i = 0; i < syntheticNames.length; i++) {
            address pool = ammRouter.createPool(USDC_ARC_TESTNET, synthTokens[i]);
            console.log(string.concat(syntheticSymbols[i], "/USDC pool:"), pool);
        }

        // ═══════════════════════════════════════════════════════════════
        // Phase 4: Tier 1 Vault (agent-created)
        // ═══════════════════════════════════════════════════════════════

        console.log("");
        console.log("=== Phase 4: Tier 1 Vault ===");

        if (vm.addr(deployerKey) == agentAddr) {
            address tier1Vault = vaultFactory.createVault(
                "Archimedes Momentum Alpha",
                "vMOM",
                150,   // 1.5% management fee
                2000,  // 20% performance fee
                true
            );
            console.log("Tier 1 vault:", tier1Vault);

            assetRegistry.registerVault(
                tier1Vault,
                1,
                abi.encode("Archimedes Momentum Alpha", "vMOM", uint16(150), uint16(2000))
            );

            // Set target allocations for the vault. Symbol-keyed (NOT positional): the SSOT
            // is sorted by symbol, so a positional index would silently point at the wrong
            // token. sSPY + sBTC are both deploy-eligible (sTSLA is compliance-held now).
            address[] memory allocTokens = new address[](3);
            allocTokens[0] = USDC_ARC_TESTNET;
            allocTokens[1] = _tokenFor(syntheticSymbols, synthTokens, "sSPY");
            allocTokens[2] = _tokenFor(syntheticSymbols, synthTokens, "sBTC");

            uint256[] memory allocWeights = new uint256[](3);
            allocWeights[0] = 4000; // 40% USDC
            allocWeights[1] = 3500; // 35% sSPY
            allocWeights[2] = 2500; // 25% sBTC

            Vault(payable(tier1Vault)).setTargetAllocations(allocTokens, allocWeights);
            console.log("Target allocations set");
        } else {
            console.log("!!! Deployer != agent. Create Tier 1 vault manually !!!");
        }

        vm.stopBroadcast();

        // ═══════════════════════════════════════════════════════════════
        // Phase 5: Seed AMM Liquidity (requires separate broadcast
        //          since deployer needs USDC + synth tokens)
        // ═══════════════════════════════════════════════════════════════

        bool seedLiq = vm.envOr("SEED_LIQUIDITY", false);
        if (seedLiq) {
            vm.startBroadcast(deployerKey);

            console.log("");
            console.log("=== Phase 5: Seed AMM Liquidity ===");

            // Note: deployer must have USDC and have minted synth tokens
            // For testnet, mint synth tokens through the vaults first
            uint256 seedUsdcPerPool = 10_000 * 10**6; // 10,000 USDC per pool

            for (uint256 i = 0; i < synthTokens.length; i++) {
                // Approve router for USDC
                // In production, would need to mint synth tokens first via vault
                // For now, just log the steps
                console.log(string.concat("  Seed ", syntheticSymbols[i], "/USDC with:"), seedUsdcPerPool);
            }

            vm.stopBroadcast();
        }

        // ═══════════════════════════════════════════════════════════════
        // Summary
        // ═══════════════════════════════════════════════════════════════

        console.log("");
        console.log("=== Deployment Summary ===");
        console.log("USDC (existing):       ", USDC_ARC_TESTNET);
        console.log("AMMRouter:             ", address(ammRouter));
        console.log("SyntheticFactory:      ", address(synthFactory));
        console.log("ReasoningTraceRegistry:", address(traceRegistry));
        console.log("AssetRegistry:         ", address(assetRegistry));
        console.log("VaultFactory:          ", address(vaultFactory));
        console.log("Owner:                 ", owner);
        console.log("Agent:                 ", agentAddr);
        console.log("Synthetic count:       ", synthTokens.length);
    }

    /// @dev Resolve a deployed synth token by symbol. Symbol-keyed (not positional) so
    ///      allocations don't depend on the SSOT's sorted ordering. Reverts if the symbol
    ///      isn't in the deployed set.
    function _tokenFor(string[] memory symbols, address[] memory tokens, string memory target)
        private
        pure
        returns (address)
    {
        bytes32 t = keccak256(bytes(target));
        for (uint256 i = 0; i < symbols.length; i++) {
            if (keccak256(bytes(symbols[i])) == t) return tokens[i];
        }
        revert(string.concat("synth not in deployed set: ", target));
    }
}
