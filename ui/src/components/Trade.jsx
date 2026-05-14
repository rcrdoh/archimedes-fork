import { useState, useEffect, useCallback } from 'react'
import {
  publicClient, getWalletClient, getAddress,
  USDC, TOKEN_ABI, AMM_ROUTER_ABI,
  ASSETS, NEW_CONTRACTS,
} from '../config'

const PRICE_DECIMALS = 6
const TOKEN_DECIMALS = 18
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export default function Trade() {
  const fallbackTokens = [
    { id: 'USDC', name: 'USD Coin', sym: 'USDC', emoji: '💵', token: USDC, decimals: PRICE_DECIMALS, color: '#3B82F6' },
    ...ASSETS.map(asset => ({
      ...asset,
      decimals: TOKEN_DECIMALS,
      color: asset.id === 'BTC' ? '#F59E0B' : asset.id === 'TSLA' ? '#EF4444' : '#6366F1',
    })),
  ]

  const [backendAssets, setBackendAssets] = useState([])
  const [backendPools, setBackendPools] = useState([])
  const [contracts, setContracts] = useState(null)
  const [backendError, setBackendError] = useState('')

  const backendTokens = backendAssets.map(asset => ({
    id: asset.symbol === 'USDC' ? 'USDC' : asset.symbol.replace(/^s/, ''),
    name: asset.name,
    sym: asset.symbol,
    emoji: asset.symbol === 'USDC' ? '💵' : asset.symbol === 'sBTC' ? '₿' : asset.symbol === 'sTSLA' ? '🚗' : asset.symbol === 'sSPY' ? '📈' : '◆',
    token: asset.address,
    decimals: asset.decimals,
    price_usd: asset.price_usd,
    color: asset.symbol === 'USDC' ? '#3B82F6' : asset.symbol === 'sBTC' ? '#F59E0B' : asset.symbol === 'sTSLA' ? '#EF4444' : '#D4A853',
  }))
  const ALL_SWAP_TOKENS = backendTokens.length > 0 ? backendTokens : fallbackTokens

  const fallbackPools = [
    { pair: 'USDC / sTSLA', fee: '0.3%', tvl: '$842K', volume: '$124K', apr: '16.2%', tokenId: 'TSLA' },
    { pair: 'USDC / sBTC', fee: '0.3%', tvl: '$1.2M', volume: '$342K', apr: '24.8%', tokenId: 'BTC' },
    { pair: 'USDC / sSPY', fee: '0.3%', tvl: '$621K', volume: '$89K', apr: '12.4%', tokenId: 'SPY' },
    { pair: 'USDC / USYC', fee: '0.05%', tvl: '$2.1M', volume: '$421K', apr: '5.4%', tokenId: null },
    { pair: 'USDC / vMOMENTUM', fee: 'Vault Token · 0.3%', tvl: '$182K', volume: '$28K', apr: '+0.4% prem.', tokenId: null, accent: true },
  ]

  const [mode, setMode] = useState('swap')
  const [tokenInId, setTokenInId] = useState('USDC')
  const [tokenOutId, setTokenOutId] = useState('TSLA')
  const [amountIn, setAmountIn] = useState('1000')
  const [quote, setQuote] = useState(null)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [quoting, setQuoting] = useState(false)
  const [balances, setBalances] = useState({})

  const tokenIn = ALL_SWAP_TOKENS.find(token => token.id === tokenInId) ?? ALL_SWAP_TOKENS[0]
  const tokenOut = ALL_SWAP_TOKENS.find(token => token.id === tokenOutId) ?? ALL_SWAP_TOKENS[1] ?? ALL_SWAP_TOKENS[0]
  const routerAddr = contracts?.amm_router || NEW_CONTRACTS.ammRouter

  const decimalsIn = tokenIn.decimals ?? (tokenIn.id === 'USDC' ? PRICE_DECIMALS : TOKEN_DECIMALS)
  const amountNumber = parseFloat(amountIn || '0')
  const displayOut = quote?.amountOut ?? null
  const minReceived = quote ? quote.amountOut * 0.995 : null
  const feeAmount = amountNumber > 0 ? amountNumber * 0.003 : 0
  const priceImpactColor = quote?.slippage > 1 ? 'var(--negative)' : quote?.slippage > 0.3 ? 'var(--accent)' : 'var(--positive)'

  const featuredPools = backendPools.length > 0
    ? backendPools.map(pool => ({
        pair: `${pool.symbol0} / ${pool.symbol1}`,
        fee: `${pool.fee_pct.toFixed(2)}%`,
        tvl: pool.tvl_usdc ? `$${pool.tvl_usdc.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—',
        volume: pool.volume_24h_usdc ? `$${pool.volume_24h_usdc.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—',
        apr: pool.apr_pct != null ? `${pool.apr_pct.toFixed(1)}%` : 'Live',
        tokenId: pool.symbol0 === 'USDC' ? pool.symbol1.replace(/^s/, '') : pool.symbol0.replace(/^s/, ''),
      }))
    : fallbackPools

  useEffect(() => {
    let cancelled = false
    async function loadBackendData() {
      try {
        const [assetData, poolData, contractData] = await Promise.all([
          apiGet('/api/assets/'),
          apiGet('/api/swap/pools'),
          apiGet('/api/config/contracts'),
        ])
        if (cancelled) return
        setBackendAssets(assetData.assets ?? [])
        setBackendPools(poolData.pools ?? [])
        setContracts(contractData)
        setBackendError('')
      } catch (err) {
        if (!cancelled) setBackendError(`Backend unavailable: ${err.message}`)
      }
    }
    loadBackendData()
    return () => { cancelled = true }
  }, [])

  const loadBalances = useCallback(async () => {
    const addr = getAddress()
    if (!addr) { setBalances({}); return }
    const uniqueTokens = [...new Map([tokenIn, tokenOut].map(token => [token.id, token])).values()]
    try {
      const entries = await Promise.all(uniqueTokens.map(async token => {
        const raw = await publicClient.readContract({
          address: token.token,
          abi: TOKEN_ABI,
          functionName: 'balanceOf',
          args: [addr],
        })
        const decimals = token.id === 'USDC' ? PRICE_DECIMALS : TOKEN_DECIMALS
        return [token.id, Number(raw) / 10 ** decimals]
      }))
      setBalances(Object.fromEntries(entries))
    } catch {
      setBalances({})
    }
  }, [tokenIn, tokenOut])

  const getQuote = useCallback(async (amtStr, tIn, tOut) => {
    if (!routerAddr || !amtStr) { setQuote(null); return }
    const amt = parseFloat(amtStr)
    if (isNaN(amt) || amt <= 0) { setQuote(null); return }
    if (tIn.id === tOut.id) { setQuote(null); return }
    setQuoting(true)
    setStatus('')
    try {
      const params = new URLSearchParams({
        token_in: tIn.token,
        token_out: tOut.token,
        amount_in: String(amt),
      })
      const data = await apiGet(`/api/swap/quote?${params.toString()}`)
      if (data.amount_out === 0) {
        setQuote(null)
        setStatus('No liquidity in this pool yet. Add liquidity first.')
      } else {
        setQuote({
          amountOut: data.amount_out,
          execPrice: data.amount_out / amt,
          spotPrice: data.amount_out / amt,
          slippage: data.price_impact_pct,
          minAmountOut: data.min_amount_out,
          feePct: data.fee_pct,
        })
        setStatus('')
      }
    } catch (err) {
      setQuote(null)
      if (err.message?.includes('Insufficient') || err.message?.includes('insufficient')) {
        setStatus('Insufficient liquidity for this trade size.')
      } else {
        setStatus(err.shortMessage || err.message)
      }
    }
    setQuoting(false)
  }, [routerAddr])

  useEffect(() => {
    const timer = setTimeout(() => { getQuote(amountIn, tokenIn, tokenOut) }, 400)
    return () => clearTimeout(timer)
  }, [amountIn, tokenIn, tokenOut, getQuote])

  useEffect(() => {
    const timer = setTimeout(loadBalances, 0)
    return () => clearTimeout(timer)
  }, [loadBalances])

  const executeSwap = async () => {
    setBusy(true)
    setStatus('')
    try {
      const wallet = await getWalletClient()
      const amountInt = BigInt(Math.round(parseFloat(amountIn) * 10 ** decimalsIn))
      setStatus('Approving token…')
      await wallet.writeContract({
        address: tokenIn.token,
        abi: TOKEN_ABI,
        functionName: 'approve',
        args: [routerAddr, amountInt],
      })
      setStatus('Swapping…')
      const hash = await wallet.writeContract({
        address: routerAddr,
        abi: AMM_ROUTER_ABI,
        functionName: 'swap',
        args: [tokenIn.token, tokenOut.token, amountInt, BigInt(0)],
      })
      setStatus(`Swapped! TX: ${hash}`)
      loadBalances()
    } catch (err) {
      setStatus(err.shortMessage || err.message)
    }
    setBusy(false)
  }

  const flipTokens = () => {
    setTokenInId(tokenOut.id)
    setTokenOutId(tokenIn.id)
    setAmountIn(displayOut ? displayOut.toFixed(6) : '')
    setQuote(null)
  }

  const updateToken = (side, tokenId) => {
    const next = ALL_SWAP_TOKENS.find(a => a.id === tokenId)
    if (!next) return
    if (side === 'in') {
      if (next.id === tokenOut.id) setTokenOutId(tokenIn.id)
      setTokenInId(next.id)
    } else {
      if (next.id === tokenIn.id) setTokenInId(tokenOut.id)
      setTokenOutId(next.id)
    }
    setQuote(null)
  }

  const renderTokenSelector = (token, side) => (
    <div className="token-pill">
      <div className="token-dot" style={{ background: token.color, color: 'white' }}>
        {token.id === 'USDC' ? 'U' : token.sym.replace('s', '').slice(0, 1)}
      </div>
      <select value={token.id} onChange={e => updateToken(side, e.target.value)}>
        {ALL_SWAP_TOKENS.map(a => <option key={a.id} value={a.id}>{a.sym}</option>)}
      </select>
      <span style={{ color: 'var(--text-3)', fontSize: '0.7rem' }}>▾</span>
    </div>
  )

  return (
    <div className="trade-page">
      <div className="tabs">
        <div className={`tab${mode === 'swap' ? ' active' : ''}`} onClick={() => setMode('swap')}>Swap</div>
        <div className={`tab${mode === 'pools' ? ' active' : ''}`} onClick={() => setMode('pools')}>Pools</div>
        <div className={`tab${mode === 'positions' ? ' active' : ''}`} onClick={() => setMode('positions')}>My Positions</div>
      </div>

      {backendError && <div className="backend-warning">{backendError}. Showing deployed frontend config until the backend is running.</div>}

      {!routerAddr ? (
        <div className="card-flat" style={{ padding: 20 }}>AMM Router not deployed yet. Run <code>node deploy-new.mjs</code> first.</div>
      ) : (
        <div className="trade-grid">
          {/* Swap interface */}
          {mode === 'swap' && (
            <div className="swap-box fade-up fade-up-1">
              <div className="swap-token-input">
                <div className="flex justify-between mb-3">
                  <span className="caption">From</span>
                  <span className="caption">Balance: <strong style={{ color: 'var(--text-2)' }}>{balances[tokenIn.id] != null ? balances[tokenIn.id].toFixed(tokenIn.id === 'USDC' ? 2 : 6) : '—'}</strong></span>
                </div>
                <div className="flex items-center justify-between">
                  <input
                    type="text"
                    className="swap-amount"
                    value={amountIn}
                    onChange={e => setAmountIn(e.target.value)}
                    placeholder="0.00"
                  />
                  {renderTokenSelector(tokenIn, 'in')}
                </div>
                <div className="caption" style={{ marginTop: 16 }}>≈ ${tokenIn.id === 'USDC' ? (amountNumber || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</div>
              </div>

              <div className="swap-arrow"><button onClick={flipTokens} title="Swap direction">↕</button></div>

              <div className="swap-token-input" style={{ marginTop: -6 }}>
                <div className="flex justify-between mb-3">
                  <span className="caption">To</span>
                  <span className="caption">Balance: <strong style={{ color: 'var(--text-2)' }}>{balances[tokenOut.id] != null ? balances[tokenOut.id].toFixed(tokenOut.id === 'USDC' ? 2 : 6) : '—'}</strong></span>
                </div>
                <div className="flex items-center justify-between">
                  <input
                    type="text"
                    className="swap-amount"
                    value={quoting ? 'Quoting…' : displayOut != null ? displayOut.toFixed(6) : ''}
                    placeholder="0.00"
                    readOnly
                    style={{ color: displayOut != null ? 'var(--positive)' : undefined }}
                  />
                  {renderTokenSelector(tokenOut, 'out')}
                </div>
                <div className="caption" style={{ marginTop: 16 }}>≈ {tokenOut.id === 'USDC' && displayOut != null ? `$${displayOut.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}</div>
              </div>

              <div className="card-flat quote-details">
                <div className="flex justify-between caption mb-2"><span>Rate</span><span style={{ color: 'var(--text-2)' }}>{quote ? `1 ${tokenIn.sym} = ${quote.execPrice.toFixed(6)} ${tokenOut.sym}` : '—'}</span></div>
                <div className="flex justify-between caption mb-2"><span>Price impact</span><span style={{ color: priceImpactColor }}>{quote ? `${quote.slippage.toFixed(3)}%` : '—'}</span></div>
                <div className="flex justify-between caption mb-2"><span>Fee (0.3%)</span><span style={{ color: 'var(--text-2)' }}>{amountNumber > 0 ? `${feeAmount.toFixed(tokenIn.id === 'USDC' ? 2 : 6)} ${tokenIn.sym}` : '—'}</span></div>
                <div className="flex justify-between caption mb-2"><span>Min received</span><span style={{ color: 'var(--text-2)' }}>{minReceived ? `${minReceived.toFixed(6)} ${tokenOut.sym}` : '—'}</span></div>
                <div className="flex justify-between caption"><span>Gas</span><span className="positive">~$0.01 Paymaster</span></div>
              </div>

              <button className="btn btn-primary w-full btn-lg" onClick={executeSwap} disabled={busy || !amountIn || !quote}>
                {busy ? 'Waiting for wallet…' : 'Swap'}
              </button>
              <div className="caption text-center" style={{ marginTop: 16 }}>AMM · Constant Product · {tokenIn.sym}/{tokenOut.sym}</div>
              {status && <div className="status-msg">{status}</div>}
            </div>
          )}

          {/* Pools */}
          {mode !== 'positions' && (
            <div>
              <div className="label mb-5 fade-up fade-up-2">Liquidity Pools</div>
              <div className="flex-col gap-3">
                {featuredPools.map((pool, i) => (
                  <div key={pool.pair} className={`card fade-up fade-up-${Math.min(i + 2, 5)}${pool.accent ? ' card-accent' : ''}`}>
                    <div className="flex items-center justify-between mb-3">
                      <div>
                        <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{pool.pair}</div>
                        <div className={`caption${pool.accent ? ' accent' : ''}`}>Fee: {pool.fee}</div>
                      </div>
                      <button className="btn btn-outline btn-sm" onClick={() => pool.tokenId && updateToken('out', pool.tokenId)}>+ Add</button>
                    </div>
                    <div className="flex gap-5">
                      <div><div className="caption">TVL</div><div style={{ fontWeight: 700 }}>{pool.tvl}</div></div>
                      <div><div className="caption">24h Vol</div><div style={{ fontWeight: 700 }}>{pool.volume}</div></div>
                      <div><div className="caption">{pool.accent ? 'Prem.' : 'APR'}</div><div className="positive" style={{ fontWeight: 700 }}>{pool.apr}</div></div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* My Positions */}
          {mode === 'positions' && (
            <div className="positions-empty fade-up fade-up-1">
              <div style={{ fontSize: '2rem', marginBottom: 10 }}>💧</div>
              <strong>No LP positions detected</strong>
              <p className="caption" style={{ marginTop: 8, maxWidth: 440 }}>Add liquidity from the Liquidity tab to see pool shares, fees earned, and vault-token premium/discount here.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
