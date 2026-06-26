import { useEffect, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function shortAddr(a) {
  return a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '—'
}

export default function MarketTab({ walletAddr, onNavigate }) {
  const [strategies, setStrategies] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState(null)
  const [expandedSubscriptors, setExpandedSubscriptors] = useState([])
  const [subscribing, setSubscribing] = useState(null) // strategy id being subscribed to
  const [depositAmount, setDepositAmount] = useState('10')
  const [message, setMessage] = useState('')

  const loadStrategies = async () => {
    try {
      const r = await fetch(`${API_BASE}/api/market/strategies?status=live&limit=50`)
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setStrategies(data.strategies || [])
    } catch (e) {
      setError(e.message || 'Failed to load market')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStrategies()
    const t = setInterval(loadStrategies, 30_000)
    return () => clearInterval(t)
  }, [])

  const toggleExpand = async (id) => {
    if (expandedId === id) {
      setExpandedId(null)
      setExpandedSubscriptors([])
      return
    }
    setExpandedId(id)
    try {
      const r = await fetch(`${API_BASE}/api/market/strategies/${id}`)
      if (!r.ok) throw new Error(await r.text())
      const data = await r.json()
      setExpandedSubscriptors(data.subscriptors || [])
    } catch (e) {
      setExpandedSubscriptors([])
    }
  }

  const handleSubscribe = async (strategyId) => {
    if (!walletAddr) {
      setMessage('Connect a wallet to subscribe.')
      return
    }
    setSubscribing(strategyId)
    setMessage('')
    try {
      const r = await fetch(`${API_BASE}/api/market/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          published_strategy_id: strategyId,
          deposit_amount: parseFloat(depositAmount) || 10,
        }),
      })
      if (!r.ok) {
        const err = await r.text()
        throw new Error(err || r.statusText)
      }
      const data = await r.json()
      setMessage(`Subscribed! Vault: ${shortAddr(data.vault_address)}. Status: ${data.status}`)
      // Refresh to show updated subscriptors
      loadStrategies()
      if (expandedId === strategyId) toggleExpand(strategyId)
    } catch (e) {
      setMessage(`Subscribe failed: ${e.message}`)
    } finally {
      setSubscribing(null)
    }
  }

  const handleRetire = async (subscriptionId) => {
    if (!walletAddr) {
      setMessage('Connect a wallet to retire funds.')
      return
    }
    setMessage('')
    try {
      const r = await fetch(`${API_BASE}/api/market/retire`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ subscription_id: subscriptionId }),
      })
      if (!r.ok) {
        const err = await r.text()
        throw new Error(err || r.statusText)
      }
      const data = await r.json()
      setMessage(`Funds retired. Operations paused: ${data.vault_under_threshold}`)
    } catch (e) {
      setMessage(`Retire failed: ${e.message}`)
    }
  }

  return (
    <div>
      <div className="max-w-[760px] mb-6">
        <h2 className="serif text-[2rem] mb-2.5">Copy Trading Market</h2>
        <p className="body mb-2">
          Browse published strategies and subscribe to copy-trade them.
          Each strategy runs in an isolated, non-custodial vault you control.
        </p>
        <p className="caption" style={{ color: 'var(--text-4)' }}>
          Subscribe to a strategy to automatically replicate its trades in your own vault.
          Creator earnings are split via Arc nanopayments.
        </p>
      </div>

      {/* Subscribe deposit amount input */}
      <div className="flex items-center gap-3 mb-5">
        <span className="caption">Deposit amount (USDC):</span>
        <input
          type="number"
          min="1"
          step="1"
          value={depositAmount}
          onChange={(e) => setDepositAmount(e.target.value)}
          className="bg-[var(--bg-2)] border border-[var(--border,rgba(255,255,255,0.08))] rounded px-3 py-1.5 text-sm w-28"
          style={{ color: 'var(--text-1)' }}
        />
      </div>

      {message && (
        <div className="info-box mb-4" style={{ padding: '10px 14px', fontSize: '0.85rem' }}>
          {message}
        </div>
      )}

      {loading && (
        <div className="card p-4">
          <p className="caption">Loading published strategies…</p>
        </div>
      )}

      {!loading && error && (
        <div className="info-box warning p-4">
          Failed to load market: {error}
        </div>
      )}

      {!loading && !error && strategies.length === 0 && (
        <div className="card p-4">
          <p className="body mb-2">No strategies published yet.</p>
          <p className="caption">
            Be the first — generate a strategy and publish it from its passport page.
          </p>
        </div>
      )}

      {!loading && !error && strategies.length > 0 && (
        <div className="flex flex-col gap-3">
          {strategies.map((s) => (
            <div key={s.id} className="card p-4">
              {/* Strategy header row */}
              <div
                className="flex items-center justify-between gap-3 cursor-pointer"
                onClick={() => toggleExpand(s.id)}
              >
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-sm" style={{ color: 'var(--text-1)' }}>
                    {s.description || `Strategy ${shortAddr(s.strategy_id)}`}
                  </div>
                  <div className="caption mt-1 flex gap-3" style={{ color: 'var(--text-3)' }}>
                    <span>Vault: {shortAddr(s.vault_address)}</span>
                    <span>Threshold: ${s.funding_threshold}</span>
                    <span>{s.subscriptor_count} subscriber{s.subscriptor_count !== 1 ? 's' : ''}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`tag ${s.status === 'live' ? 'tag-positive' : 'tag-muted'}`}>
                    {s.status}
                  </span>
                  <span className="i-lucide-chevron-down w-4 h-4"
                    style={{
                      color: 'var(--text-3)',
                      transform: expandedId === s.id ? 'rotate(180deg)' : 'none',
                      transition: 'transform 0.2s',
                    }}
                  />
                </div>
              </div>

              {/* Expanded: subscriptors + subscribe CTA */}
              {expandedId === s.id && (
                <div className="mt-4 pt-4 border-t border-[var(--border,rgba(255,255,255,0.08))]">
                  {/* Creator info */}
                  <div className="caption mb-3" style={{ color: 'var(--text-4)' }}>
                    Created by {shortAddr(s.creator_address)} · Published {s.created_at ? new Date(s.created_at).toLocaleDateString() : ''}
                  </div>

                  {/* Subscriptors list */}
                  {expandedSubscriptors.length > 0 && (
                    <div className="mb-4">
                      <div className="caption mb-2 font-semibold" style={{ color: 'var(--text-3)' }}>
                        Subscriptors ({expandedSubscriptors.length}):
                      </div>
                      <div className="flex flex-col gap-2">
                        {expandedSubscriptors.map((sub, i) => (
                          <div key={i} className="flex items-center justify-between gap-3 text-xs"
                            style={{
                              padding: '6px 10px',
                              background: 'var(--bg-2)',
                              borderRadius: 6,
                            }}
                          >
                            <div className="flex items-center gap-3">
                              <span className="mono">{shortAddr(sub.wallet)}</span>
                              <span className="caption" style={{ color: 'var(--text-4)' }}>
                                vault: {shortAddr(sub.vault_address)}
                              </span>
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="caption">${sub.deposit_amount}</span>
                              <span className={`tag ${sub.status === 'active' ? 'tag-positive' : 'tag-muted'}`}>
                                {sub.status}
                              </span>
                              {sub.status !== 'retired' && walletAddr && (
                                <button
                                  className="btn btn-outline btn-xs"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    // Find subscription id - we'd need it from the detail endpoint
                                    handleRetire(sub.id || 0)
                                  }}
                                  style={{ padding: '2px 8px', fontSize: '0.7rem' }}
                                >
                                  Retire
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {expandedSubscriptors.length === 0 && (
                    <div className="caption mb-3" style={{ color: 'var(--text-4)' }}>
                      No subscriptors yet. Be the first to copy-trade this strategy.
                    </div>
                  )}

                  {/* Subscribe CTA */}
                  {walletAddr ? (
                    <button
                      className="btn btn-primary btn-sm mt-2"
                      onClick={() => handleSubscribe(s.id)}
                      disabled={subscribing === s.id}
                    >
                      {subscribing === s.id ? 'Subscribing…' : `Subscribe — Deposit $${depositAmount} USDC`}
                    </button>
                  ) : (
                    <div className="caption mt-2" style={{ color: 'var(--text-4)' }}>
                      Connect a wallet to subscribe and copy-trade this strategy.
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
