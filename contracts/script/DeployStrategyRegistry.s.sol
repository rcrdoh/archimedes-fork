// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/StrategyRegistry.sol";

/// @notice Deploy StrategyRegistry.sol to Arc testnet.
///         Usage:
///           forge script script/DeployStrategyRegistry.s.sol --rpc-url arc-testnet --broadcast
///
///         Required env vars:
///           DEPLOYER_KEY   — private key of the deployer
///           OWNER_ADDRESS  — address that will own the registry (platform agent)
contract DeployStrategyRegistryScript is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address owner = vm.envAddress("OWNER_ADDRESS");

        vm.startBroadcast(deployerKey);

        StrategyRegistry registry = new StrategyRegistry(owner);
        console.log("StrategyRegistry deployed at:", address(registry));

        vm.stopBroadcast();

        console.log("");
        console.log("=== Deployment Summary ===");
        console.log("StrategyRegistry:", address(registry));
        console.log("Owner:           ", owner);
        console.log("");
        console.log("Add to .env:");
        console.log("  STRATEGY_REGISTRY_ADDRESS=", address(registry));
    }
}
