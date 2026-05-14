// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

/// @title IAMMPool
/// @notice A single Uniswap V2-style constant-product pool (x·y = k).
///         Each pool pairs a token against USDC.
/// @dev Owner: Chuan (implements). Consumers: Marten (LP seeding),
///      Daniel (frontend reads reserves for price display).
interface IAMMPool {
    // ── Events ───────────────────────────────────────────────
    event Swap(
        address indexed sender,
        address indexed tokenIn,
        uint256 amountIn,
        address indexed tokenOut,
        uint256 amountOut
    );
    event LiquidityAdded(
        address indexed provider,
        uint256 amount0,
        uint256 amount1,
        uint256 lpTokens
    );
    event LiquidityRemoved(
        address indexed provider,
        uint256 amount0,
        uint256 amount1,
        uint256 lpTokens
    );

    // ── Views ────────────────────────────────────────────────
    /// @notice First token in the pair (sorted by address).
    function token0() external view returns (address);

    /// @notice Second token in the pair.
    function token1() external view returns (address);

    /// @notice Current reserve of token0.
    function reserve0() external view returns (uint256);

    /// @notice Current reserve of token1.
    function reserve1() external view returns (uint256);

    /// @notice Total supply of LP tokens.
    function totalSupply() external view returns (uint256);

    /// @notice Swap fee in basis points (e.g. 30 = 0.30%).
    function swapFeeBps() external view returns (uint16);

    /// @notice Calculate output amount for a given input.
    /// @param tokenIn Address of input token
    /// @param amountIn Amount of input token
    /// @return amountOut Amount of output token (after fees)
    function getAmountOut(
        address tokenIn,
        uint256 amountIn
    ) external view returns (uint256 amountOut);

    /// @notice Get the spot price of tokenIn in terms of tokenOut.
    /// @return price Price with 18 decimals
    function getSpotPrice(
        address tokenIn,
        address tokenOut
    ) external view returns (uint256 price);
}
