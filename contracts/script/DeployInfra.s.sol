// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/AMMRouter.sol";
import "../src/SyntheticFactory.sol";
import "../src/VaultFactory.sol";
import "../src/ReasoningTraceRegistry.sol";
import "../src/AssetRegistry.sol";

/// @notice Deploy Phase 1 infrastructure only (no owner-only factory calls).
///         Phase 2+ (synthetics, pools, vaults) done via Circle wallet in Python.
contract DeployInfra is Script {
    address constant USDC_ARC_TESTNET = 0x3600000000000000000000000000000000000000;

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address owner = vm.envAddress("OWNER_ADDRESS");
        address agentAddr = vm.envAddress("AGENT_ADDRESS");

        vm.startBroadcast(deployerKey);

        console.log("=== Deploying Core Infrastructure ===");
        console.log("Owner:", owner);
        console.log("Agent:", agentAddr);

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

        vm.stopBroadcast();

        console.log("");
        console.log("=== Done ===");
    }
}
