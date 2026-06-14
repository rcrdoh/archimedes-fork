// SPDX-License-Identifier: Unlicense
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import "./interfaces/IAMMRouter.sol";
import "./interfaces/IAMMPool.sol";
import "./AMMPool.sol";

/// @title AMMRouter
/// @notice Creates pools, routes swaps, and manages liquidity operations.
///         All pools are created through this contract for tracking.
contract AMMRouter is IAMMRouter, Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ─── State ───────────────────────────────────────────────────────

    /// @notice Swap fee in basis points for new pools (30 = 0.30%)
    uint16 public defaultSwapFeeBps = 30;

    /// @notice Mapping from sorted token pair hash to pool address
    mapping(bytes32 => address) private _pools;

    /// @notice All pool addresses
    address[] private _allPools;

    // ─── Errors ──────────────────────────────────────────────────────

    error PoolNotFound();
    error PoolAlreadyExists();
    error ZeroAmount();
    error SlippageExceeded();
    error InvalidPair();

    // ─── Constructor ─────────────────────────────────────────────────

    constructor(address _owner) Ownable(_owner) {}

    // ─── Pool Management ─────────────────────────────────────────────

    function createPool(address tokenA, address tokenB)
        external
        override
        returns (address pool)
    {
        if (tokenA == tokenB) revert InvalidPair();

        bytes32 pairHash = _pairHash(tokenA, tokenB);
        if (_pools[pairHash] != address(0)) revert PoolAlreadyExists();

        // Sort tokens for deterministic ordering
        (address t0, address t1) = _sortTokens(tokenA, tokenB);

        AMMPool newPool = new AMMPool(t0, t1, defaultSwapFeeBps, address(this));
        pool = address(newPool);

        _pools[pairHash] = pool;
        _allPools.push(pool);

        emit PoolCreated(tokenA, tokenB, pool);
    }

    function getPool(address tokenA, address tokenB)
        external
        view
        override
        returns (address pool)
    {
        return _pools[_pairHash(tokenA, tokenB)];
    }

    function getAllPools() external view override returns (address[] memory) {
        return _allPools;
    }

    // ─── Liquidity ───────────────────────────────────────────────────

    function addLiquidity(
        address tokenA,
        address tokenB,
        uint256 amountA,
        uint256 amountB,
        uint256 minLPTokens
    ) external override nonReentrant returns (uint256 lpTokens) {
        address pool = _pools[_pairHash(tokenA, tokenB)];
        if (pool == address(0)) revert PoolNotFound();

        // Transfer tokens from sender to this contract
        IERC20(tokenA).safeTransferFrom(msg.sender, address(this), amountA);
        IERC20(tokenB).safeTransferFrom(msg.sender, address(this), amountB);

        // Sort amounts to match pool's token order
        (address t0, address t1) = _sortTokens(tokenA, tokenB);
        (uint256 amt0, uint256 amt1) = tokenA == t0
            ? (amountA, amountB)
            : (amountB, amountA);

        // Approve pool to pull tokens
        IERC20(t0).safeIncreaseAllowance(pool, amt0);
        IERC20(t1).safeIncreaseAllowance(pool, amt1);

        // Add liquidity to pool
        lpTokens = AMMPool(pool).addLiquidity(amt0, amt1, msg.sender);

        if (lpTokens < minLPTokens) revert SlippageExceeded();

        // Transfer any LP tokens to sender (already minted to msg.sender by pool)
    }

    function removeLiquidity(
        address tokenA,
        address tokenB,
        uint256 lpTokens,
        uint256 minAmountA,
        uint256 minAmountB
    ) external override nonReentrant returns (uint256 amountA, uint256 amountB) {
        address pool = _pools[_pairHash(tokenA, tokenB)];
        if (pool == address(0)) revert PoolNotFound();

        // Transfer LP tokens from sender to this contract
        IERC20(pool).safeTransferFrom(msg.sender, address(this), lpTokens);

        // Remove liquidity — tokens come to this contract
        (amountA, amountB) = _removeLiquidityFromPool(pool, lpTokens);

        // Map amounts back to the user's requested token order
        (address t0,) = _sortTokens(tokenA, tokenB);
        if (tokenA != t0) {
            (amountA, amountB) = (amountB, amountA);
        }

        if (amountA < minAmountA || amountB < minAmountB) {
            revert SlippageExceeded();
        }

        // Transfer tokens to sender
        IERC20(tokenA).safeTransfer(msg.sender, amountA);
        IERC20(tokenB).safeTransfer(msg.sender, amountB);
    }

    // ─── Swap ────────────────────────────────────────────────────────

    function swap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut
    ) external override nonReentrant returns (uint256 amountOut) {
        address pool = _pools[_pairHash(tokenIn, tokenOut)];
        if (pool == address(0)) revert PoolNotFound();

        // Transfer tokenIn from sender to this contract
        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);

        // Approve pool to pull tokenIn
        IERC20(tokenIn).safeIncreaseAllowance(pool, amountIn);

        // Execute swap — tokenOut comes to this contract.
        // Pass 0 as minAmountOut: the router already enforces slippage above via
        // the SlippageExceeded check on the returned amountOut.
        amountOut = AMMPool(pool).swap(tokenIn, amountIn, address(this), 0);

        if (amountOut < minAmountOut) revert SlippageExceeded();

        // Transfer tokenOut to sender
        IERC20(tokenOut).safeTransfer(msg.sender, amountOut);
    }

    // ─── Views ───────────────────────────────────────────────────────

    function getAmountOut(
        address tokenIn,
        address tokenOut,
        uint256 amountIn
    ) external view override returns (uint256 amountOut) {
        address pool = _pools[_pairHash(tokenIn, tokenOut)];
        if (pool == address(0)) return 0;
        return IAMMPool(pool).getAmountOut(tokenIn, amountIn);
    }

    // ─── Admin ───────────────────────────────────────────────────────

    function setDefaultSwapFeeBps(uint16 newFeeBps) external onlyOwner {
        require(newFeeBps <= 1000, "fee too high"); // max 10%
        defaultSwapFeeBps = newFeeBps;
    }

    // ─── Internal ────────────────────────────────────────────────────

    function _pairHash(address tokenA, address tokenB) internal pure returns (bytes32) {
        (address t0, address t1) = _sortTokens(tokenA, tokenB);
        return keccak256(abi.encodePacked(t0, t1));
    }

    function _sortTokens(address tokenA, address tokenB)
        internal
        pure
        returns (address t0, address t1)
    {
        if (tokenA < tokenB) {
            return (tokenA, tokenB);
        }
        return (tokenB, tokenA);
    }

    function _removeLiquidityFromPool(address pool, uint256 lpTokens)
        internal
        returns (uint256 amount0, uint256 amount1)
    {
        return AMMPool(pool).removeLiquidity(lpTokens, address(this));
    }
}
