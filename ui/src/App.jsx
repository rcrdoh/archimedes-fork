import { useState, useEffect, useCallback } from 'react'
import {
  publicClient, getWalletClient, getAddress, connectWallet, disconnectWallet,
  getAvailableProviders, getConnectedProvider,
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

const TABS = ['📊 Dashboard', '🔄 Mint/Burn', '🔀 Swap', '🏛️ Vaults', '📝 Traces']

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
    } catch (err) {
      setStatus(`❌ ${err.shortMessage || err.message}`)
    }
    setBusy(false)
  }

  return (
    <div className="panel">
      <h2>Mint / Burn Synthetics</h2>
      <p className="hint">Deposit USDC to mint synthetic tokens, or burn them back to USDC.</p>

      <div className="form-group">
        <label>Asset</label>
        <select value={selectedAsset.id} onChange={e => setSelectedAsset(ASSETS.find(a => a.id === e.target.value))}>
          {ASSETS.map(a => <option key={a.id} value={a.id}>{a.emoji} {a.sym} — {a.name}</option>)}
        </select>
      </div>

      <div className="form-group">
        <label>Action</label>
        <div className="btn-group">
          <button className={action === 'mint' ? 'active' : ''} onClick={() => setAction('mint')}>Mint</button>
          <button className={action === 'burn' ? 'active' : ''} onClick={() => setAction('burn')}>Burn</button>
        </div>
      </div>

      <div className="form-group">
        <label>{action === 'mint' ? 'USDC Amount (6 dec)' : 'Synth Amount (18 dec)'}</label>
        <input type="number" value={amount} onChange={e => setAmount(e.target.value)} placeholder="1000" />
      </div>

      <button className="primary" onClick={execute} disabled={busy || !amount}>
        {busy ? '⏳ Waiting...' : action === 'mint' ? '🪙 Mint' : '🔥 Burn'}
      </button>

      {status && <div className="status">{status}</div>}

      <div className="info-box">
        <strong>Selected:</strong> {selectedAsset.emoji} {selectedAsset.sym}<br />
        <strong>Token:</strong> <code>{selectedAsset.token}</code><br />
        <strong>Vault:</strong> <code>{selectedAsset.vault}</code><br />
        <strong>Oracle:</strong> <code>{selectedAsset.oracle}</code>
      </div>
    </div>
  )
}

// ─── Swap Panel ──────────────────────────────────────────────

function Swap() {
  const [tokenIn, setTokenIn] = useState(ASSETS[0])
  const [tokenOut, setTokenOut] = useState(ASSETS[1])
  const [amountIn, setAmountIn] = useState('')
  const [preview, setPreview] = useState(null)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  const routerAddr = NEW_CONTRACTS.ammRouter

  const getQuote = async () => {
    if (!routerAddr || !amountIn) return
    try {
      const amountInt = BigInt(Math.round(parseFloat(amountIn) * 10 ** TOKEN_DECIMALS))
      const out = await publicClient.readContract({
        address: routerAddr,
        abi: AMM_ROUTER_ABI,
        functionName: 'getAmountOut',
        args: [tokenIn.token, tokenOut.token, amountInt],
      })
      setPreview(Number(out) / 10 ** TOKEN_DECIMALS)
    } catch {
      setPreview(null)
    }
  }

  const executeSwap = async () => {
    setBusy(true)
    setStatus('')
    try {
      const wallet = await getWalletClient()
      const amountInt = BigInt(Math.round(parseFloat(amountIn) * 10 ** TOKEN_DECIMALS))

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

  return (
    <div className="panel">
      <h2>🔀 Swap via AMM</h2>
      {!routerAddr ? (
        <div className="info-box warning">⚠️ AMM Router not deployed yet. Run <code>node deploy-new.mjs</code> first.</div>
      ) : (
        <>
          <div className="form-group">
            <label>Token In</label>
            <select value={tokenIn.id} onChange={e => { setTokenIn(ASSETS.find(a => a.id === e.target.value)); setPreview(null) }}>
              {ASSETS.map(a => <option key={a.id} value={a.id}>{a.emoji} {a.sym}</option>)}
            </select>
          </div>

          <div className="form-group">
            <label>Amount In</label>
            <input type="number" value={amountIn} onChange={e => { setAmountIn(e.target.value); setPreview(null) }} placeholder="100" />
          </div>

          <div style={{ textAlign: 'center', fontSize: '2rem' }}>⬇️</div>

          <div className="form-group">
            <label>Token Out</label>
            <select value={tokenOut.id} onChange={e => { setTokenOut(ASSETS.find(a => a.id === e.target.value)); setPreview(null) }}>
              {ASSETS.map(a => <option key={a.id} value={a.id}>{a.emoji} {a.sym}</option>)}
            </select>
          </div>

          <button onClick={getQuote} disabled={!amountIn}>Get Quote</button>
          {preview !== null && <div className="preview">≈ {preview.toFixed(6)} {tokenOut.sym}</div>}

          <button className="primary" onClick={executeSwap} disabled={busy || !amountIn}>
            {busy ? '⏳' : '🔀 Swap'}
          </button>

          {status && <div className="status">{status}</div>}
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
  const [walletAddr, setWalletAddr] = useState(getAddress())
  const [data, setData] = useState({})
  const [prevData, setPrevData] = useState({})
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(true)
  const [lastFetch, setLastFetch] = useState(null)
  const [countdown, setCountdown] = useState(30)

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
        {tab === 3 && <Vaults />}
        {tab === 4 && <Traces />}
      </main>

      <footer>
        <span>Arc Testnet · USDC: {USDC} · {ASSETS.length} synthetic assets</span>
      </footer>
    </div>
  )
}
