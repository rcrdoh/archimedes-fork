// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

/// @title IAMMRouter
/// @notice Entry point for all AMM operations: create pools, swap, add/remove liquidity.
/// @dev Owner: Chuan (implements). Consumers: Marten (vault rebalance executes swaps,
///      LP seeding), Daniel (frontend swap UI calls this directly via user wallet).
interface IAMMRouter {
    // ── Events ───────────────────────────────────────────────
    event PoolCreated(address indexed tokenA, address indexed tokenB, address pool);

    // ── Pool Management ──────────────────────────────────────
    /// @notice Create a new liquidity pool for a token pair.
    /// @param tokenA First token (typically USDC)
    /// @param tokenB Second token (synthetic or vault token)
    /// @return pool Address of the created AMMPool
    function createPool(
        address tokenA,
        address tokenB
    ) external returns (address pool);

    /// @notice Get the pool address for a token pair (zero if doesn't exist).
    function getPool(
        address tokenA,
        address tokenB
    ) external view returns (address pool);

    /// @notice List all pool addresses.
    function getAllPools() external view returns (address[] memory);

    // ── Liquidity ────────────────────────────────────────────
    /// @notice Add liquidity to a pool. Caller must approve both tokens first.
    /// @param tokenA First token address
    /// @param tokenB Second token address
    /// @param amountA Desired amount of tokenA to deposit
    /// @param amountB Desired amount of tokenB to deposit
    /// @param minLPTokens Minimum LP tokens to receive (slippage protection)
    /// @return lpTokens Actual LP tokens minted
    function addLiquidity(
        address tokenA,
        address tokenB,
        uint256 amountA,
        uint256 amountB,
        uint256 minLPTokens
    ) external returns (uint256 lpTokens);

    /// @notice Remove liquidity from a pool.
    /// @param tokenA First token address
    /// @param tokenB Second token address
    /// @param lpTokens LP tokens to burn
    /// @param minAmountA Minimum tokenA to receive
    /// @param minAmountB Minimum tokenB to receive
    /// @return amountA Actual tokenA received
    /// @return amountB Actual tokenB received
    function removeLiquidity(
        address tokenA,
        address tokenB,
        uint256 lpTokens,
        uint256 minAmountA,
        uint256 minAmountB
    ) external returns (uint256 amountA, uint256 amountB);

    // ── Swap ─────────────────────────────────────────────────
    /// @notice Swap tokenIn for tokenOut via the appropriate pool.
    /// @param tokenIn Input token address
    /// @param tokenOut Output token address
    /// @param amountIn Amount of input token to swap
    /// @param minAmountOut Minimum output (slippage protection)
    /// @return amountOut Actual output token received
    function swap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut
    ) external returns (uint256 amountOut);

    // ── Views ────────────────────────────────────────────────
    /// @notice Preview swap output without executing.
    function getAmountOut(
        address tokenIn,
        address tokenOut,
        uint256 amountIn
    ) external view returns (uint256 amountOut);
}
