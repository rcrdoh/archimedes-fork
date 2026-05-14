import { useState, useEffect, useCallback } from 'react'
import {
  publicClient, getWalletClient, getAddress, connectWallet, disconnectWallet,
  reconnectWallet, getAvailableProviders, getConnectedProvider,
  USDC,
  ORACLE_ABI, TOKEN_ABI, SYNTH_VAULT_ABI,
  AMM_ROUTER_ABI, TRACE_REGISTRY_ABI, VAULT_ABI, VAULT_FACTORY_ABI,
  ASSETS, NEW_CONTRACTS,
} from './config'
import './App.css'

const PRICE_DECIMALS = 6
const TOKEN_DECIMALS = 18

// ─── Shared helpers ──────────────────────────────────────────

function timeAgo(ts) {
  const secs = Math.floor(Date.now() / 1000) - ts
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}

function formatPrice(id, price) {
  if (id === 'BTC') return price.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
  return price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function fetchAssetData(asset) {
  const [price, lastUpdated, isFresh, supply] = await Promise.all([
    publicClient.readContract({ address: asset.oracle, abi: ORACLE_ABI, functionName: 'price' }),
    publicClient.readContract({ address: asset.oracle, abi: ORACLE_ABI, functionName: 'lastUpdated' }),
    publicClient.readContract({ address: asset.oracle, abi: ORACLE_ABI, functionName: 'isFresh' }),
    publicClient.readContract({ address: asset.token, abi: TOKEN_ABI, functionName: 'totalSupply' }),
  ])
  return {
    price: Number(price) / 10 ** PRICE_DECIMALS,
    lastUpdated: Number(lastUpdated),
    isFresh,
    supply: Number(supply) / 10 ** TOKEN_DECIMALS,
  }
}

// ─── Tabs ────────────────────────────────────────────────────

const TABS = ['📊 Dashboard', '🔄 Mint/Burn', '🔀 Swap', '💧 Liquidity', '🏛️ Vaults', '📝 Traces']

// ─── Wallet Connect Button ────────────────────────────────────

function WalletConnect({ address, onConnect, onDisconnect }) {
  const [showModal, setShowModal] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const available = getAvailableProviders()

  const handleConnect = async (providerId) => {
    setBusy(true)
    setError('')
    try {
      const result = await connectWallet(providerId)
      setShowModal(false)
      onConnect(result.address)
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  if (address) {
    return (
      <div className="wallet-info">
        <span className="wallet-addr">{address.slice(0, 6)}...{address.slice(-4)}</span>
        <button className="btn-sm" onClick={onDisconnect}>Disconnect</button>
      </div>
    )
  }

  return (
    <>
      <button className="connect-btn" onClick={() => setShowModal(true)}>
        🔗 Connect Wallet
      </button>

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Connect Wallet</h3>
            <p className="hint">Select a wallet to interact with Arc Testnet contracts.</p>

            {available.length === 0 ? (
              <div className="info-box warning">
                No wallets detected. Install <a href="https://metamask.io" target="_blank" rel="noreferrer">MetaMask</a> or{' '}
                <a href="https://www.coinbase.com/wallet" target="_blank" rel="noreferrer">Coinbase Wallet</a>.
              </div>
            ) : (
              <div className="wallet-options">
                {available.map(p => (
                  <button key={p.id} className="wallet-option" onClick={() => handleConnect(p.id)} disabled={busy}>
                    <span className="wallet-icon">{p.icon}</span>
                    <span>{p.name}</span>
                  </button>
                ))}
              </div>
            )}

            {error && <div className="status" style={{ marginTop: 12 }}>{error}</div>}

            <button className="btn-sm" style={{ marginTop: 12, width: '100%' }} onClick={() => setShowModal(false)}>Cancel</button>
          </div>
        </div>
      )}
    </>
  )
}

// ─── Dashboard Panel ─────────────────────────────────────────

function Dashboard({ data, prevData, errors, loading, lastFetch, countdown, fetchAll }) {
  const liveCount = Object.values(data).filter(d => d?.isFresh).length

  return (
    <div>
      <div className="status-bar">
        {lastFetch && (
          <>
            <span className="dot" />
            <span>{liveCount}/{ASSETS.length} live · refreshes in {countdown}s</span>
            <button onClick={fetchAll}>↺</button>
          </>
        )}
      </div>
      <div className="grid">
        {ASSETS.map(asset => {
          if (loading && !data[asset.id]) return <LoadingCard key={asset.id} asset={asset} />
          if (errors[asset.id]) return <ErrorCard key={asset.id} asset={asset} error={errors[asset.id]} />
          const change = prevData[asset.id] != null ? ((data[asset.id].price - prevData[asset.id]) / prevData[asset.id]) * 100 : null
          return (
            <div key={asset.id} className={`card ${!data[asset.id].isFresh ? 'stale' : ''}`}>
              <div className="card-header">
                <span className="emoji">{asset.emoji}</span>
                <div>
                  <div className="asset-name">{asset.name}</div>
                  <div className="asset-sym">{asset.sym}</div>
                </div>
                <span className={`badge ${data[asset.id].isFresh ? 'fresh' : 'stale'}`}>
                  {data[asset.id].isFresh ? 'LIVE' : 'STALE'}
                </span>
              </div>
              <div className="price-row">
                <span className="price">${formatPrice(asset.id, data[asset.id].price)}</span>
                {change !== null && (
                  <span className={`change ${change > 0 ? 'up' : change < 0 ? 'down' : ''}`}>
                    {change > 0 ? '▲' : change < 0 ? '▼' : '─'}{Math.abs(change).toFixed(3)}%
                  </span>
                )}
              </div>
              <div className="meta">
                <span>Updated {timeAgo(data[asset.id].lastUpdated)}</span>
                <span>{data[asset.id].supply.toFixed(4)} {asset.sym}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function LoadingCard({ asset }) {
  return (
    <div className="card loading">
      <div className="card-header">
        <span className="emoji">{asset.emoji}</span>
        <div><div className="asset-name">{asset.name}</div><div className="asset-sym">{asset.sym}</div></div>
      </div>
      <div className="price-row"><span className="price skeleton">$———</span></div>
    </div>
  )
}

function ErrorCard({ asset, error }) {
  return (
    <div className="card error">
      <div className="card-header">
        <span className="emoji">{asset.emoji}</span>
        <div><div className="asset-name">{asset.name}</div><div className="asset-sym">{asset.sym}</div></div>
        <span className="badge stale">ERR</span>
      </div>
      <div className="meta"><span className="err-msg">{error}</span></div>
    </div>
  )
}

// ─── Mint/Burn Panel ────────────────────────────────────────

function MintBurn() {
  const [selectedAsset, setSelectedAsset] = useState(ASSETS[0])
  const [amount, setAmount] = useState('')
  const [action, setAction] = useState('mint')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [balances, setBalances] = useState({ usdc: null, synth: null, price: null })
  const [estimate, setEstimate] = useState(null)

  // Load balances when asset or wallet changes
  const loadBalances = useCallback(async () => {
    try {
      const wallet = await getWalletClient()
      const addr = getAddress()
      if (!addr) return

      const [usdcBal, synthBal, price] = await Promise.all([
        publicClient.readContract({ address: USDC, abi: TOKEN_ABI, functionName: 'balanceOf', args: [addr] }),
        publicClient.readContract({ address: selectedAsset.token, abi: TOKEN_ABI, functionName: 'balanceOf', args: [addr] }),
        publicClient.readContract({ address: selectedAsset.oracle, abi: ORACLE_ABI, functionName: 'price' }),
      ])
      setBalances({
        usdc: Number(usdcBal) / 10 ** PRICE_DECIMALS,
        synth: Number(synthBal) / 10 ** TOKEN_DECIMALS,
        price: Number(price) / 10 ** PRICE_DECIMALS,
      })
    } catch {
      // wallet not connected
    }
  }, [selectedAsset])

  useEffect(() => { loadBalances() }, [selectedAsset, loadBalances])

  // Auto-refresh balances every 15 seconds
  useEffect(() => {
    const interval = setInterval(loadBalances, 15_000)
    return () => clearInterval(interval)
  }, [loadBalances])

  // Estimate output when amount changes
  useEffect(() => {
    if (!amount || !balances.price) { setEstimate(null); return }
    const amt = parseFloat(amount)
    if (isNaN(amt) || amt <= 0) { setEstimate(null); return }

    if (action === 'mint') {
      // mint fee = 50bps. price is already human-readable ($/token).
      // synthOut = netUsdc / price
      const fee = amt * 0.005
      const netUsdc = amt - fee
      const synthOut = netUsdc / balances.price
      setEstimate({
        fee: fee.toFixed(2),
        output: synthOut,
        outputLabel: `${selectedAsset.emoji} ${synthOut.toFixed(6)} ${selectedAsset.sym}`,
      })
    } else {
      // burn fee = 50bps. price is already human-readable.
      // usdcOut = synthAmount * price * (1 - fee)
      const usdcGross = amt * balances.price
      const fee = usdcGross * 0.005
      const usdcOut = usdcGross - fee
      setEstimate({
        fee: fee.toFixed(2),
        output: usdcOut,
        outputLabel: `💵 ${usdcOut.toFixed(2)} USDC`,
      })
    }
  }, [amount, action, balances.price, selectedAsset])

  const execute = async () => {
    setBusy(true)
    setStatus('')
    try {
      const wallet = await getWalletClient()
      const addr = getAddress()
      const amountInt = BigInt(Math.round(parseFloat(amount) * 10 ** (action === 'mint' ? PRICE_DECIMALS : TOKEN_DECIMALS)))

      if (action === 'mint') {
        // Approve USDC → vault
        setStatus('Approving USDC...')
        await wallet.writeContract({
          address: USDC,
          abi: TOKEN_ABI,
          functionName: 'approve',
          args: [selectedAsset.vault, amountInt],
        })
        setStatus('Minting...')
        const hash = await wallet.writeContract({
          address: selectedAsset.vault,
          abi: SYNTH_VAULT_ABI,
          functionName: 'mint',
          args: [amountInt],
        })
        setStatus(`✅ Minted! TX: ${hash}`)
      } else {
        setStatus('Burning...')
        const hash = await wallet.writeContract({
          address: selectedAsset.vault,
          abi: SYNTH_VAULT_ABI,
          functionName: 'burn',
          args: [amountInt],
        })
        setStatus(`✅ Burned! TX: ${hash}`)
      }
      loadBalances() // refresh after tx
    } catch (err) {
      setStatus(`❌ ${err.shortMessage || err.message}`)
    }
    setBusy(false)
  }

  // Max amount helper
  const setMax = () => {
    if (action === 'mint') {
      setAmount(balances.usdc ? String(Math.floor(balances.usdc * 100) / 100) : '')
    } else {
      setAmount(balances.synth ? String(balances.synth) : '')
    }
  }

  return (
    <div className="panel">
      <h2>Mint / Burn Synthetics</h2>
      <p className="hint">Deposit USDC to mint synthetic tokens, or burn them back to USDC.</p>

      {/* Balance bar */}
      <div className="balance-bar">
        <div className="balance-item">
          <span className="balance-label">💵 USDC</span>
          <span className="balance-value">{balances.usdc !== null ? balances.usdc.toFixed(2) : '—'}</span>
        </div>
        <div className="balance-item">
          <span className="balance-label">{selectedAsset.emoji} {selectedAsset.sym}</span>
          <span className="balance-value">{balances.synth !== null ? balances.synth.toFixed(6) : '—'}</span>
        </div>
        <div className="balance-item">
          <span className="balance-label">💲 Price</span>
          <span className="balance-value">{balances.price !== null ? `$${balances.price.toFixed(2)}` : '—'}</span>
        </div>
      </div>

      <div className="form-group">
        <label>Asset</label>
        <select value={selectedAsset.id} onChange={e => { setSelectedAsset(ASSETS.find(a => a.id === e.target.value)); setAmount(''); setEstimate(null) }}>
          {ASSETS.map(a => <option key={a.id} value={a.id}>{a.emoji} {a.sym} — {a.name}</option>)}
        </select>
      </div>

      <div className="form-group">
        <label>Action</label>
        <div className="btn-group">
          <button className={action === 'mint' ? 'active' : ''} onClick={() => { setAction('mint'); setAmount(''); setEstimate(null) }}>Mint</button>
          <button className={action === 'burn' ? 'active' : ''} onClick={() => { setAction('burn'); setAmount(''); setEstimate(null) }}>Burn</button>
        </div>
      </div>

      <div className="form-group">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <label>{action === 'mint' ? 'USDC Amount' : `${selectedAsset.sym} Amount`}</label>
          <button className="link-btn" onClick={setMax}>Max</button>
        </div>
        <input type="number" value={amount} onChange={e => setAmount(e.target.value)} placeholder={action === 'mint' ? '1000' : '0.5'} />
      </div>

      {/* Estimate */}
      {estimate && (
        <div className="estimate-box">
          <div className="estimate-row">
            <span>Fee (0.5%)</span>
            <span>${estimate.fee}</span>
          </div>
          <div className="estimate-row estimate-output">
            <span>You receive ≈</span>
            <span>{estimate.outputLabel}</span>
          </div>
          <div className="estimate-note">Estimate based on current oracle price. Actual amount may differ slightly.</div>
        </div>
      )}

      <button className="primary" onClick={execute} disabled={busy || !amount}>
        {busy ? '⏳ Waiting...' : action === 'mint' ? '🪙 Mint' : '🔥 Burn'}
      </button>

      {status && <div className="status">{status}</div>}
    </div>
  )
}

// ─── Swap Panel ──────────────────────────────────────────────

function Swap() {
  const ALL_SWAP_TOKENS = [
    { id: 'USDC', name: 'USD Coin', sym: 'USDC', emoji: '💵', token: USDC },
    ...ASSETS,
  ]

  const [tokenIn, setTokenIn] = useState(ALL_SWAP_TOKENS[0])
  const [tokenOut, setTokenOut] = useState(ALL_SWAP_TOKENS[1])
  const [amountIn, setAmountIn] = useState('')
  const [quote, setQuote] = useState(null)   // { amountOut, execPrice, spotPrice, slippage }
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [quoting, setQuoting] = useState(false)

  const routerAddr = NEW_CONTRACTS.ammRouter

  // Decimals for display — USDC is 6, synthetics are 18
  const decimalsIn = tokenIn.id === 'USDC' ? PRICE_DECIMALS : TOKEN_DECIMALS
  const decimalsOut = tokenOut.id === 'USDC' ? PRICE_DECIMALS : TOKEN_DECIMALS

  // Auto-quote with debounce when amountIn / tokens change
  const getQuote = useCallback(async (amtStr, tIn, tOut) => {
    if (!routerAddr || !amtStr) { setQuote(null); return }
    const amt = parseFloat(amtStr)
    if (isNaN(amt) || amt <= 0) { setQuote(null); return }
    if (tIn.id === tOut.id) { setQuote(null); return }

    setQuoting(true)
    setStatus('')
    try {
      const dIn = tIn.id === 'USDC' ? PRICE_DECIMALS : TOKEN_DECIMALS
      const dOut = tOut.id === 'USDC' ? PRICE_DECIMALS : TOKEN_DECIMALS
      const amountInt = BigInt(Math.round(amt * 10 ** dIn))

      // Fetch actual quote and spot quote (1 unit) in parallel
      const oneUnit = BigInt(10 ** dIn)  // 1 token in smallest unit
      const [outRaw, spotOutRaw] = await Promise.all([
        publicClient.readContract({
          address: routerAddr, abi: AMM_ROUTER_ABI,
          functionName: 'getAmountOut',
          args: [tIn.token, tOut.token, amountInt],
        }),
        publicClient.readContract({
          address: routerAddr, abi: AMM_ROUTER_ABI,
          functionName: 'getAmountOut',
          args: [tIn.token, tOut.token, oneUnit],
        }),
      ])

      const amountOut = Number(outRaw) / 10 ** dOut
      const spotOneOut = Number(spotOutRaw) / 10 ** dOut  // output for exactly 1 unit in

      if (amountOut === 0) {
        setQuote(null)
        setStatus('⚠️ No liquidity in this pool yet. Add liquidity first.')
      } else {
        const execPrice = amountOut / amt          // actual tokens out per token in
        const spotPrice = spotOneOut               // ideal tokens out per token in
        const slippage = spotPrice > 0
          ? ((spotPrice - execPrice) / spotPrice) * 100
          : 0
        setQuote({ amountOut, execPrice, spotPrice, slippage })
        setStatus('')
      }
    } catch (err) {
      setQuote(null)
      if (err.message?.includes('Insufficient') || err.message?.includes('insufficient')) {
        setStatus('⚠️ Insufficient liquidity for this trade size.')
      } else {
        setStatus(`⚠️ ${err.shortMessage || err.message}`)
      }
    }
    setQuoting(false)
  }, [routerAddr])

  // Debounced auto-quote
  useEffect(() => {
    setQuote(null)
    const timer = setTimeout(() => {
      getQuote(amountIn, tokenIn, tokenOut)
    }, 400)
    return () => clearTimeout(timer)
  }, [amountIn, tokenIn, tokenOut, getQuote])

  const executeSwap = async () => {
    setBusy(true)
    setStatus('')
    try {
      const wallet = await getWalletClient()
      const amountInt = BigInt(Math.round(parseFloat(amountIn) * 10 ** decimalsIn))

      setStatus('Approving token...')
      await wallet.writeContract({
        address: tokenIn.token,
        abi: TOKEN_ABI,
        functionName: 'approve',
        args: [routerAddr, amountInt],
      })

      setStatus('Swapping...')
      const hash = await wallet.writeContract({
        address: routerAddr,
        abi: AMM_ROUTER_ABI,
        functionName: 'swap',
        args: [tokenIn.token, tokenOut.token, amountInt, BigInt(0)],
      })
      setStatus(`✅ Swapped! TX: ${hash}`)
    } catch (err) {
      setStatus(`❌ ${err.shortMessage || err.message}`)
    }
    setBusy(false)
  }

  const flipTokens = () => {
    const prev = tokenIn
    setTokenIn(tokenOut)
    setTokenOut(prev)
    setAmountIn('')
    setQuote(null)
  }

  return (
    <div className="panel">
      <h2>🔀 Swap via AMM</h2>
      {!routerAddr ? (
        <div className="info-box warning">⚠️ AMM Router not deployed yet. Run <code>node deploy-new.mjs</code> first.</div>
      ) : (
        <>
          <div className="form-group">
            <label>Token In</label>
            <select value={tokenIn.id} onChange={e => { setTokenIn(ALL_SWAP_TOKENS.find(a => a.id === e.target.value)); setQuote(null) }}>
              {ALL_SWAP_TOKENS.map(a => <option key={a.id} value={a.id}>{a.emoji} {a.sym}</option>)}
            </select>
          </div>

          <div className="form-group">
            <label>Amount In</label>
            <input type="number" value={amountIn} onChange={e => setAmountIn(e.target.value)} placeholder="100" />
          </div>

          <div style={{ textAlign: 'center' }}>
            <button className="btn-sm" onClick={flipTokens} title="Swap direction">⬆️⬇️</button>
          </div>

          <div className="form-group">
            <label>Token Out</label>
            <select value={tokenOut.id} onChange={e => { setTokenOut(ALL_SWAP_TOKENS.find(a => a.id === e.target.value)); setQuote(null) }}>
              {ALL_SWAP_TOKENS.map(a => <option key={a.id} value={a.id}>{a.emoji} {a.sym}</option>)}
            </select>
          </div>

          {/* Live quote details */}
          {quoting && <div className="status" style={{ opacity: 0.6 }}>⏳ Fetching quote...</div>}

          {quote && (
            <div className="estimate-box">
              <div className="estimate-row estimate-output">
                <span>You receive ≈</span>
                <span>{tokenOut.emoji} {quote.amountOut.toFixed(6)} {tokenOut.sym}</span>
              </div>
              <div className="estimate-row">
                <span>Exec Price</span>
                <span>{quote.execPrice.toFixed(6)} {tokenOut.sym}/{tokenIn.sym}</span>
              </div>
              <div className="estimate-row">
                <span>Spot Price</span>
                <span>{quote.spotPrice.toFixed(6)} {tokenOut.sym}/{tokenIn.sym}</span>
              </div>
              <div className="estimate-row">
                <span>Price Impact</span>
                <span style={{ color: quote.slippage > 1 ? '#ef4444' : quote.slippage > 0.3 ? '#f59e0b' : '#22c55e' }}>
                  {quote.slippage.toFixed(3)}%
                </span>
              </div>
              <div className="estimate-note">
                Quote auto-refreshes. Price impact is the difference between spot and execution price.
              </div>
            </div>
          )}

          <button className="primary" onClick={executeSwap} disabled={busy || !amountIn || !quote}>
            {busy ? '⏳' : '🔀 Swap'}
          </button>

          {status && <div className="status">{status}</div>}
        </>
      )}
    </div>
  )
}

// ─── Liquidity Panel ─────────────────────────────────────────

function Liquidity() {
  const [selectedAsset, setSelectedAsset] = useState(ASSETS[0])
  const [usdcAmount, setUsdcAmount] = useState('')
  const [synthAmount, setSynthAmount] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [poolAddr, setPoolAddr] = useState(null)
  const [reserves, setReserves] = useState(null)
  const [balances, setBalances] = useState(null)

  const routerAddr = NEW_CONTRACTS.ammRouter

  const USDC_DECIMALS = 6
  const SYNTH_DECIMALS = 18
  const walletAddr = getAddress()

  const loadPoolInfo = async () => {
    if (!routerAddr) return
    try {
      // Load pool info
      const pool = await publicClient.readContract({
        address: routerAddr,
        abi: AMM_ROUTER_ABI,
        functionName: 'getPool',
        args: [USDC, selectedAsset.token],
      })
      setPoolAddr(pool)
      if (pool && pool !== '0x0000000000000000000000000000000000000000') {
        const AMMPOOL_ABI = [
          { name: 'reserve0',     type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
          { name: 'reserve1',     type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
          { name: 'totalSupply',  type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
        ]
        const [r0, r1, ts] = await Promise.all([
          publicClient.readContract({ address: pool, abi: AMMPOOL_ABI, functionName: 'reserve0' }),
          publicClient.readContract({ address: pool, abi: AMMPOOL_ABI, functionName: 'reserve1' }),
          publicClient.readContract({ address: pool, abi: AMMPOOL_ABI, functionName: 'totalSupply' }),
        ])
        setReserves({ reserve0: Number(r0), reserve1: Number(r1), totalSupply: Number(ts) })
      } else {
        setReserves(null)
      }
    } catch {
      setPoolAddr(null)
      setReserves(null)
    }

    // Load wallet balances
    if (walletAddr) {
      try {
        const [usdcBal, synthBal] = await Promise.all([
          publicClient.readContract({
            address: USDC, abi: TOKEN_ABI, functionName: 'balanceOf', args: [walletAddr],
          }),
          publicClient.readContract({
            address: selectedAsset.token, abi: TOKEN_ABI, functionName: 'balanceOf', args: [walletAddr],
          }),
        ])
        setBalances({
          usdc: Number(usdcBal) / 10 ** USDC_DECIMALS,
          synth: Number(synthBal) / 10 ** SYNTH_DECIMALS,
        })
      } catch {
        setBalances(null)
      }
    } else {
      setBalances(null)
    }
  }

  useEffect(() => { loadPoolInfo() }, [selectedAsset])

  const addLiquidity = async () => {
    if (!routerAddr || !usdcAmount || !synthAmount) return
    setBusy(true)
    setStatus('')
    try {
      const wallet = await getWalletClient()
      const usdcInt = BigInt(Math.round(parseFloat(usdcAmount) * 10 ** USDC_DECIMALS))
      const synthInt = BigInt(Math.round(parseFloat(synthAmount) * 10 ** SYNTH_DECIMALS))

      // Approve synth token → router
      setStatus('Approving synth token...')
      await wallet.writeContract({
        address: selectedAsset.token,
        abi: TOKEN_ABI,
        functionName: 'approve',
        args: [routerAddr, synthInt],
      })

      // Approve USDC → router
      setStatus('Approving USDC...')
      await wallet.writeContract({
        address: USDC,
        abi: TOKEN_ABI,
        functionName: 'approve',
        args: [routerAddr, usdcInt],
      })

      // Add liquidity
      setStatus('Adding liquidity...')
      const hash = await wallet.writeContract({
        address: routerAddr,
        abi: AMM_ROUTER_ABI,
        functionName: 'addLiquidity',
        args: [USDC, selectedAsset.token, usdcInt, synthInt, BigInt(0)],
      })
      setStatus(`✅ Liquidity added! TX: ${hash}`)
      loadPoolInfo()
    } catch (err) {
      setStatus(`❌ ${err.shortMessage || err.message}`)
    }
    setBusy(false)
  }

  return (
    <div className="panel">
      <h2>💧 Add Liquidity</h2>
      {!routerAddr ? (
        <div className="info-box warning">⚠️ AMM Router not deployed yet.</div>
      ) : (
        <>
          <div className="form-group">
            <label>Pool</label>
            <select value={selectedAsset.id} onChange={e => setSelectedAsset(ASSETS.find(a => a.id === e.target.value))}>
              {ASSETS.map(a => <option key={a.id} value={a.id}>{a.emoji} {a.sym}/USDC</option>)}
            </select>
          </div>

          {poolAddr && poolAddr !== '0x0000000000000000000000000000000000000000' ? (
            <div className="info-box">
              <strong>Pool:</strong> <code>{poolAddr}</code><br />
              {reserves && (
                <>
                  <strong>Reserves:</strong> {(reserves.reserve0 / 1e6).toFixed(2)} USDC / {(reserves.reserve1 / 1e18).toFixed(6)} {selectedAsset.sym}<br />
                  <strong>LP Supply:</strong> {reserves.totalSupply}
                </>
              )}
            </div>
          ) : (
            <div className="info-box warning">⚠️ Pool not found for this pair.</div>
          )}

          {balances ? (
            <div className="balance-bar">
              <span>💵 USDC: <strong>{balances.usdc.toFixed(2)}</strong></span>
              <span>{selectedAsset.emoji} {selectedAsset.sym}: <strong>{balances.synth.toFixed(6)}</strong></span>
            </div>
          ) : walletAddr ? (
            <div className="balance-bar">Loading balances...</div>
          ) : (
            <div className="info-box warning">Connect wallet to see your balances.</div>
          )}

          <div className="form-group">
            <label>USDC Amount (6 dec)</label>
            <input type="number" value={usdcAmount} onChange={e => setUsdcAmount(e.target.value)} placeholder="10" />
          </div>

          <div className="form-group">
            <label>Synth Amount (18 dec)</label>
            <input type="number" value={synthAmount} onChange={e => setSynthAmount(e.target.value)} placeholder="50" />
          </div>

          <button className="primary" onClick={addLiquidity} disabled={busy || !usdcAmount || !synthAmount}>
            {busy ? '⏳' : '💧 Add Liquidity'}
          </button>

          {status && <div className="status">{status}</div>}

          <p className="hint" style={{ marginTop: 16 }}>
            First mint synthetics via the Mint/Burn tab, then add them here paired with USDC.
          </p>
        </>
      )}
    </div>
  )
}

// ─── Vaults Panel ────────────────────────────────────────────

function Vaults() {
  const [vaults, setVaults] = useState([])
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [selectedVault, setSelectedVault] = useState(null)
  const [vaultDetail, setVaultDetail] = useState(null)
  const [depositAmt, setDepositAmt] = useState('')

  const factoryAddr = NEW_CONTRACTS.vaultFactory

  const loadVaults = async () => {
    if (!factoryAddr) return
    try {
      const addrs = await publicClient.readContract({
        address: factoryAddr,
        abi: VAULT_FACTORY_ABI,
        functionName: 'getVaults',
      })
      setVaults(addrs)
    } catch (err) {
      setStatus(`❌ ${err.shortMessage || err.message}`)
    }
  }

  const loadVaultDetail = async (addr) => {
    try {
      const [totalAssets, totalSupply, creator, tier, paused, asset] = await Promise.all([
        publicClient.readContract({ address: addr, abi: VAULT_ABI, functionName: 'totalAssets' }),
        publicClient.readContract({ address: addr, abi: VAULT_ABI, functionName: 'totalSupply' }),
        publicClient.readContract({ address: addr, abi: VAULT_ABI, functionName: 'creator' }),
        publicClient.readContract({ address: addr, abi: VAULT_ABI, functionName: 'tier' }),
        publicClient.readContract({ address: addr, abi: VAULT_ABI, functionName: 'paused' }),
        publicClient.readContract({ address: addr, abi: VAULT_ABI, functionName: 'asset' }),
      ])
      setVaultDetail({
        address: addr,
        totalAssets: Number(totalAssets) / 1e6,
        totalSupply: Number(totalSupply),
        sharePrice: totalSupply > 0 ? Number(totalAssets) / Number(totalSupply) / 1e6 : 1,
        creator,
        tier: Number(tier),
        paused,
        asset,
      })
    } catch (err) {
      setVaultDetail({ error: err.shortMessage || err.message })
    }
  }

  const deposit = async () => {
    if (!selectedVault || !depositAmt) return
    setBusy(true)
    setStatus('')
    try {
      const wallet = await getWalletClient()
      const amount = BigInt(Math.round(parseFloat(depositAmt) * 1e6))

      setStatus('Approving USDC...')
      await wallet.writeContract({
        address: USDC,
        abi: TOKEN_ABI,
        functionName: 'approve',
        args: [selectedVault, amount],
      })

      setStatus('Depositing...')
      const hash = await wallet.writeContract({
        address: selectedVault,
        abi: VAULT_ABI,
        functionName: 'deposit',
        args: [amount, getAddress()],
      })
      setStatus(`✅ Deposited! TX: ${hash}`)
      loadVaultDetail(selectedVault)
    } catch (err) {
      setStatus(`❌ ${err.shortMessage || err.message}`)
    }
    setBusy(false)
  }

  useEffect(() => { loadVaults() }, [])

  return (
    <div className="panel">
      <h2>🏛️ Managed Vaults</h2>
      {!factoryAddr ? (
        <div className="info-box warning">⚠️ VaultFactory not deployed yet. Run <code>node deploy-new.mjs</code>.</div>
      ) : (
        <>
          <p>{vaults.length} vaults deployed</p>

          {vaults.length === 0 ? (
            <p className="hint">No vaults yet. Deploy contracts first, then create a vault.</p>
          ) : (
            <div className="vault-list">
              {vaults.map((v, i) => (
                <div key={i} className={`vault-card ${selectedVault === v ? 'selected' : ''}`} onClick={() => { setSelectedVault(v); loadVaultDetail(v) }}>
                  <code>{v}</code>
                </div>
              ))}
            </div>
          )}

          {vaultDetail && !vaultDetail.error && (
            <div className="info-box">
              <strong>AUM:</strong> {vaultDetail.totalAssets.toFixed(2)} USDC<br />
              <strong>Share Price:</strong> {vaultDetail.sharePrice.toFixed(6)} USDC<br />
              <strong>Tier:</strong> {vaultDetail.tier} | <strong>Creator:</strong> <code>{vaultDetail.creator?.slice(0,10)}...</code><br />
              <strong>Paused:</strong> {vaultDetail.paused ? '🛑 Yes' : '✅ No'}
            </div>
          )}

          {selectedVault && (
            <div className="form-row">
              <input type="number" value={depositAmt} onChange={e => setDepositAmt(e.target.value)} placeholder="USDC amount" />
              <button className="primary" onClick={deposit} disabled={busy}>
                {busy ? '⏳' : '💰 Deposit'}
              </button>
            </div>
          )}

          {status && <div className="status">{status}</div>}
        </>
      )}
    </div>
  )
}

// ─── Traces Panel ────────────────────────────────────────────

function Traces() {
  const [traces, setTraces] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [publishVault, setPublishVault] = useState(ASSETS[0].vault)
  const [publishMsg, setPublishMsg] = useState('Test trace from Archimedes UI')

  const regAddr = NEW_CONTRACTS.traceRegistry

  const loadTraces = async () => {
    if (!regAddr) return
    try {
      const count = await publicClient.readContract({
        address: regAddr,
        abi: TRACE_REGISTRY_ABI,
        functionName: 'traceCount',
      })
      setTotalCount(Number(count))

      // Load last 10 traces
      const loaded = []
      const start = Math.max(1, Number(count) - 9)
      for (let i = Number(count); i >= start; i--) {
        try {
          const [agent, vault, traceHash, timestamp] = await publicClient.readContract({
            address: regAddr,
            abi: TRACE_REGISTRY_ABI,
            functionName: 'getTraceById',
            args: [BigInt(i)],
          })
          loaded.push({ id: i, agent, vault, traceHash, timestamp: Number(timestamp) })
        } catch {}
      }
      setTraces(loaded)
    } catch (err) {
      setStatus(`❌ ${err.shortMessage || err.message}`)
    }
  }

  const publishTestTrace = async () => {
    if (!regAddr) return
    setBusy(true)
    setStatus('')
    try {
      const wallet = await getWalletClient()
      const hash = '0x' + Array.from(new TextEncoder().encode(publishMsg)).map(b => b.toString(16).padStart(2, '0')).join('').padEnd(64, '0').slice(0, 64)
      const metadata = '0x'

      setStatus('Publishing trace...')
      const txHash = await wallet.writeContract({
        address: regAddr,
        abi: TRACE_REGISTRY_ABI,
        functionName: 'publishTrace',
        args: [publishVault, hash, metadata],
      })
      setStatus(`✅ Published! TX: ${txHash}`)
      loadTraces()
    } catch (err) {
      setStatus(`❌ ${err.shortMessage || err.message}`)
    }
    setBusy(false)
  }

  useEffect(() => { loadTraces() }, [])

  return (
    <div className="panel">
      <h2>📝 Reasoning Traces</h2>
      {!regAddr ? (
        <div className="info-box warning">⚠️ TraceRegistry not deployed. Run <code>node deploy-new.mjs</code>.</div>
      ) : (
        <>
          <p className="hint">Total traces: {totalCount}</p>

          <h3>Publish Test Trace</h3>
          <div className="form-group">
            <label>Vault Address</label>
            <select value={publishVault} onChange={e => setPublishVault(e.target.value)}>
              {ASSETS.map(a => <option key={a.id} value={a.vault}>{a.emoji} {a.sym} vault</option>)}
            </select>
          </div>
          <div className="form-group">
            <label>Message (hashed on-chain)</label>
            <input value={publishMsg} onChange={e => setPublishMsg(e.target.value)} />
          </div>
          <button className="primary" onClick={publishTestTrace} disabled={busy}>
            {busy ? '⏳' : '📝 Publish Trace'}
          </button>

          {status && <div className="status">{status}</div>}

          <h3>Recent Traces</h3>
          {traces.length === 0 ? (
            <p className="hint">No traces yet. Publish one above!</p>
          ) : (
            <div className="trace-list">
              {traces.map(t => (
                <div key={t.id} className="trace-card">
                  <div className="trace-id">#{t.id}</div>
                  <div className="trace-detail">
                    <div><strong>Vault:</strong> <code>{t.vault.slice(0,10)}...{t.vault.slice(-6)}</code></div>
                    <div><strong>Agent:</strong> <code>{t.agent.slice(0,10)}...</code></div>
                    <div><strong>Hash:</strong> <code>{t.traceHash.slice(0,18)}...</code></div>
                    <div><strong>Time:</strong> {timeAgo(t.timestamp)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ─── Main App ────────────────────────────────────────────────

export default function App() {
  const [tab, setTab] = useState(0)
  const [walletAddr, setWalletAddr] = useState(null)
  const [data, setData] = useState({})
  const [prevData, setPrevData] = useState({})
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(true)
  const [lastFetch, setLastFetch] = useState(null)
  const [countdown, setCountdown] = useState(30)

  // Reconnect wallet from localStorage on mount
  useEffect(() => {
    reconnectWallet().then(result => {
      if (result) setWalletAddr(result.address)
    })
  }, [])

  // Listen for wallet account changes from extension events
  useEffect(() => {
    const handler = (e) => setWalletAddr(e.detail.address)
    window.addEventListener('wallet-changed', handler)
    return () => window.removeEventListener('wallet-changed', handler)
  }, [])

  const handleConnect = (addr) => setWalletAddr(addr)
  const handleDisconnect = () => { disconnectWallet(); setWalletAddr(null) }

  const fetchAll = useCallback(async () => {
    const results = await Promise.allSettled(ASSETS.map(a => fetchAssetData(a)))
    const newData = {}
    const newErrors = {}
    results.forEach((r, i) => {
      const id = ASSETS[i].id
      if (r.status === 'fulfilled') newData[id] = r.value
      else newErrors[id] = r.reason?.shortMessage || r.reason?.message || 'RPC error'
    })
    setPrevData(old => {
      const prev = {}
      for (const id of Object.keys(newData)) prev[id] = old[id]?.price ?? null
      return prev
    })
    setData(newData)
    setErrors(newErrors)
    setLoading(false)
    setLastFetch(new Date())
    setCountdown(30)
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  useEffect(() => {
    const interval = setInterval(() => {
      setCountdown(c => { if (c <= 1) { fetchAll(); return 30 } return c - 1 })
    }, 1000)
    return () => clearInterval(interval)
  }, [fetchAll])

  return (
    <div className="app">
      <header>
        <div className="logo">⚖️ Archimedes</div>
        <div className="subtitle">Arc Testnet · Contract Testing UI</div>
        <WalletConnect address={walletAddr} onConnect={handleConnect} onDisconnect={handleDisconnect} />
        <nav className="tabs">
          {TABS.map((t, i) => (
            <button key={i} className={tab === i ? 'active' : ''} onClick={() => setTab(i)}>{t}</button>
          ))}
        </nav>
      </header>

      <main>
        {tab === 0 && <Dashboard data={data} prevData={prevData} errors={errors} loading={loading} lastFetch={lastFetch} countdown={countdown} fetchAll={fetchAll} />}
        {tab === 1 && <MintBurn />}
        {tab === 2 && <Swap />}
        {tab === 3 && <Liquidity />}
        {tab === 4 && <Vaults />}
        {tab === 5 && <Traces />}
      </main>

      <footer>
        <span>Arc Testnet · USDC: {USDC} · {ASSETS.length} synthetic assets</span>
      </footer>
    </div>
  )
}
