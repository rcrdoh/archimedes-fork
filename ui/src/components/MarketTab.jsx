import { useEffect, useState, useCallback } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function shortAddr(a) {
  return a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '—'
}

// ── Inner Panel: State A (not subscribed) ──────────────────────
function SubscribePanel({ publishedStrategyId, walletAddr, onSubscribed }) {
  const [amount, setAmount] = useState('10')
  const [subscribing, setSubscribing] = useState(false)
  const [error, setError] = useState('')

  const handleSubscribe = async (e) => {
    e.stopPropagation()
    setError('')
    setSubscribing(true)
    try {
      const r = await fetch(`${API_BASE}/api/market/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          published_strategy_id: publishedStrategyId,
          deposit_amount: parseFloat(amount) || 10,
        }),
      })
      if (!r.ok) {
        const err = await r.text()
        throw new Error(err || r.statusText)
      }
      const data = await r.json()
      onSubscribed(data)
    } catch (err) {
      setError(err.message || 'Subscribe failed')
    } finally {
      setSubscribing(false)
    }
  }

  return (
    <div
      style={{
        background: 'var(--bg-3, rgba(255,255,255,0.04))',
        border: '1px solid var(--border, rgba(255,255,255,0.08))',
        borderRadius: 8,
        padding: 16,
        marginTop: 12,
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="label mb-2">Subscribe to this strategy</div>
      <p className="caption mb-3" style={{ color: 'var(--text-4)' }}>
        Deposit USDC into your personal vault to copy-trade this strategy's live actions.
      </p>
      <div className="flex items-center gap-3 mb-3">
        <span className="caption">Deposit amount (USDC):</span>
        <input
          type="number"
          min="1"
          step="1"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className="bg-[var(--bg-2)] border border-[var(--border,rgba(255,255,255,0.08))] rounded px-3 py-1.5 text-sm w-28"
          style={{ color: 'var(--text-1)' }}
          onClick={(e) => e.stopPropagation()}
        />
      </div>
      <button
        className="btn btn-primary btn-sm"
        onClick={handleSubscribe}
        disabled={subscribing}
      >
        {subscribing ? 'Subscribing…' : `Subscribe — Deposit $${parseFloat(amount) || 10} USDC`}
      </button>
      {error && (
        <div className="caption mt-2" style={{ color: 'var(--negative, #ef4444)' }}>
          {error}
        </div>
      )}
    </div>
  )
}

// ── Inner Panel: State B (already subscribed) ──────────────────
function ManagementPanel({ subscription, onUnsubscribed }) {
  const [retireAmount, setRetireAmount] = useState('')
  const [retiring, setRetiring] = useState(false)
  const [retireFeedback, setRetireFeedback] = useState(null) // { type: 'success'|'warning'|'error', msg }
  const [unsubscribing, setUnsubscribing] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [unsubError, setUnsubError] = useState('')
  const [localSubscription, setLocalSubscription] = useState(subscription)

  const handleRetire = async (e) => {
    e.stopPropagation()
    const amt = parseFloat(retireAmount)
    if (!amt || amt <= 0) return
    setRetiring(true)
    setRetireFeedback(null)
    try {
      const r = await fetch(`${API_BASE}/api/market/retire`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          subscription_id: localSubscription.id,
          retire_amount: amt,
        }),
      })
      if (!r.ok) {
        const err = await r.text()
        throw new Error(err || r.statusText)
      }
      const data = await r.json()
      if (data.vault_under_threshold) {
        setRetireFeedback({ type: 'warning', msg: 'Vault is below the funding threshold — live operations are paused.' })
      } else {
        setRetireFeedback({ type: 'success', msg: 'Funds retired. Subscription remains active.' })
      }
      // Refresh subscription detail
      try {
        const rr = await fetch(`${API_BASE}/api/market/subscriptions/mine?published_strategy_id=${localSubscription.published_strategy_id}`)
        if (rr.ok) {
          const updated = await rr.json()
          if (updated) setLocalSubscription(updated)
        }
      } catch (_) { /* silent */ }
    } catch (err) {
      setRetireFeedback({ type: 'error', msg: err.message || 'Retire failed' })
    } finally {
      setRetiring(false)
    }
  }

  const handleUnsubscribe = async () => {
    setUnsubscribing(true)
    setUnsubError('')
    try {
      const r = await fetch(`${API_BASE}/api/market/unsubscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ subscription_id: localSubscription.id }),
      })
      if (!r.ok) {
        const err = await r.text()
        throw new Error(err || r.statusText)
      }
      onUnsubscribed()
    } catch (err) {
      setUnsubError(err.message || 'Unsubscribe failed')
      setUnsubscribing(false)
      setShowConfirm(false)
    }
  }

  const statusBadge = localSubscription.status === 'active' ? 'tag-positive'
    : localSubscription.status === 'funding' ? 'tag-accent' : 'tag-muted'

  return (
    <div
      style={{
        background: 'var(--bg-3, rgba(255,255,255,0.04))',
        border: '1px solid var(--border, rgba(255,255,255,0.08))',
        borderLeft: '3px solid var(--accent, #6366f1)',
        borderRadius: 8,
        padding: 16,
        marginTop: 12,
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="label">Your subscription</div>
        <span className={`tag ${statusBadge}`}>{localSubscription.status}</span>
      </div>

      {/* Info row */}
      <div className="caption mb-3" style={{ color: 'var(--text-3)', lineHeight: 1.6 }}>
        <div>Vault: <span className="mono">{shortAddr(localSubscription.vault_address)}</span></div>
        <div>Deposit: <strong>${localSubscription.deposit_amount}</strong> USDC</div>
        <div>Subscribed: {localSubscription.created_at ? new Date(localSubscription.created_at).toLocaleDateString() : '—'}</div>
        {localSubscription.container_running != null && (
          <div style={{ marginTop: 4 }}>
            Container: <span style={{ color: localSubscription.container_running ? 'var(--positive, #22c55e)' : 'var(--negative, #ef4444)' }}>
              {localSubscription.container_running ? 'Running' : 'Stopped'}
            </span>
          </div>
        )}
      </div>

      {/* Retire funds */}
      <div className="mb-3">
        <div className="caption mb-1">Amount to retire (USDC)</div>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min="0.01"
            step="0.01"
            max={localSubscription.deposit_amount}
            value={retireAmount}
            onChange={(e) => setRetireAmount(e.target.value)}
            placeholder="0.00"
            className="bg-[var(--bg-2)] border border-[var(--border,rgba(255,255,255,0.08))] rounded px-3 py-1.5 text-sm w-28"
            style={{ color: 'var(--text-1)' }}
            onClick={(e) => e.stopPropagation()}
          />
          <button
            className="btn btn-outline btn-sm"
            onClick={handleRetire}
            disabled={retiring || !parseFloat(retireAmount)}
          >
            {retiring ? 'Retiring…' : 'Retire funds'}
          </button>
        </div>
        {retireFeedback && (
          <div
            className="caption mt-1"
            style={{
              color: retireFeedback.type === 'error' ? 'var(--negative, #ef4444)'
                : retireFeedback.type === 'warning' ? '#f59e0b' : 'var(--positive, #22c55e)',
            }}
          >
            {retireFeedback.msg}
          </div>
        )}
      </div>

      {/* Unsubscribe */}
      {!showConfirm ? (
        <button
          className="btn btn-outline btn-sm"
          style={{ color: 'var(--negative, #ef4444)' }}
          onClick={(e) => { e.stopPropagation(); setShowConfirm(true) }}
        >
          Unsubscribe
        </button>
      ) : (
        <div
          style={{
            padding: '10px 12px',
            background: 'rgba(239, 68, 68, 0.06)',
            borderRadius: 6,
            border: '1px solid rgba(239, 68, 68, 0.15)',
          }}
        >
          <p className="caption mb-2" style={{ color: 'var(--text-2)' }}>
            This will stop copy-trading and shut down your subscription container. Are you sure?
          </p>
          <div className="flex items-center gap-2">
            <button
              className="btn btn-primary btn-sm"
              style={{ background: 'var(--negative, #ef4444)' }}
              onClick={handleUnsubscribe}
              disabled={unsubscribing}
            >
              {unsubscribing ? 'Unsubscribing…' : 'Confirm unsubscribe'}
            </button>
            <button
              className="btn btn-outline btn-sm"
              onClick={(e) => { e.stopPropagation(); setShowConfirm(false) }}
              disabled={unsubscribing}
            >
              Cancel
            </button>
          </div>
          {unsubError && (
            <div className="caption mt-1" style={{ color: 'var(--negative, #ef4444)' }}>
              {unsubError}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── StrategyCard sub-component ──────────────────────────────────
function StrategyCard({ s, walletAddr, loadStrategies }) {
  const [expanded, setExpanded] = useState(false)
  const [subscriptors, setSubscriptors] = useState([])
  const [mySubscription, setMySubscription] = useState(null) // null | subscription object
  const [loadingDetail, setLoadingDetail] = useState(false)

  const onSubscribed = useCallback((subData) => {
    // Transition to State B by constructing subscription from response
    setMySubscription({
      id: subData.id || 0,
      published_strategy_id: s.id,
      vault_address: subData.vault_address || '',
      deposit_amount: subData.deposit_amount || parseFloat(localStorage.getItem('lastDeposit') || '10'),
      status: subData.status || 'funding',
      created_at: new Date().toISOString(),
      container_running: true,
    })
    loadStrategies()
  }, [s.id, loadStrategies])

  const onUnsubscribed = useCallback(() => {
    setMySubscription(null)
    loadStrategies()
  }, [loadStrategies])

  const toggleExpand = async () => {
    if (expanded) {
      setExpanded(false)
      setSubscriptors([])
      setMySubscription(null)
      return
    }
    setExpanded(true)
    setLoadingDetail(true)
    try {
      const [detailRes, subRes] = await Promise.all([
        fetch(`${API_BASE}/api/market/strategies/${s.id}`),
        walletAddr
          ? fetch(`${API_BASE}/api/market/subscriptions/mine?published_strategy_id=${s.id}`, { credentials: 'include' })
          : Promise.resolve(null),
      ])
      if (detailRes?.ok) {
        const detail = await detailRes.json()
        setSubscriptors(detail.subscriptors || [])
      }
      if (subRes && subRes.ok) {
        const subData = await subRes.json()
        setMySubscription(subData)
      } else {
        setMySubscription(null)
      }
    } catch (e) {
      // silencio
    } finally {
      setLoadingDetail(false)
    }
  }

  return (
    <div key={s.id} className="card p-4">
      {/* Strategy header row */}
      <div
        className="flex items-center justify-between gap-3 cursor-pointer"
        onClick={toggleExpand}
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
              transform: expanded ? 'rotate(180deg)' : 'none',
              transition: 'transform 0.2s',
            }}
          />
        </div>
      </div>

      {/* Expanded area */}
      {expanded && (
        <div className="mt-4 pt-4 border-t border-[var(--border,rgba(255,255,255,0.08))]">
          {/* Creator info */}
          <div className="caption mb-3" style={{ color: 'var(--text-4)' }}>
            Created by {shortAddr(s.creator_address)} · Published {s.created_at ? new Date(s.created_at).toLocaleDateString() : ''}
          </div>

          {/* Subscriptors list — informational only, no action buttons (Defect 5) */}
          {subscriptors.length > 0 && (
            <div className="mb-4">
              <div className="caption mb-2 font-semibold" style={{ color: 'var(--text-3)' }}>
                Subscriptors ({subscriptors.length}):
              </div>
              <div className="flex flex-col gap-2">
                {subscriptors.map((sub, i) => (
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
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {subscriptors.length === 0 && (
            <div className="caption mb-3" style={{ color: 'var(--text-4)' }}>
              No subscriptors yet. Be the first to copy-trade this strategy.
            </div>
          )}

          {/* Loading state */}
          {loadingDetail && (
            <div className="caption mb-2" style={{ color: 'var(--text-4)' }}>Loading subscription details…</div>
          )}

          {/* Inner panel: State A (not subscribed) or State B (subscribed) */}
          {!loadingDetail && walletAddr && !mySubscription && (
            <SubscribePanel
              publishedStrategyId={s.id}
              walletAddr={walletAddr}
              onSubscribed={onSubscribed}
            />
          )}
          {!loadingDetail && walletAddr && mySubscription && (
            <ManagementPanel
              subscription={mySubscription}
              onUnsubscribed={onUnsubscribed}
            />
          )}
          {!loadingDetail && !walletAddr && (
            <div
              style={{
                background: 'var(--bg-3, rgba(255,255,255,0.04))',
                border: '1px solid var(--border, rgba(255,255,255,0.08))',
                borderRadius: 8,
                padding: 16,
                marginTop: 12,
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="label mb-2">Connect a wallet to subscribe</div>
              <p className="caption" style={{ color: 'var(--text-4)' }}>
                Connect a wallet to subscribe and copy-trade this strategy.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main MarketTab export ──────────────────────────────────────
export default function MarketTab({ walletAddr, onNavigate }) {
  const [strategies, setStrategies] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadStrategies = async () => {
    try {
      // Cache-bust: browser GET caching can serve stale listings after an unpublish
      const r = await fetch(`${API_BASE}/api/market/strategies?status=live&limit=50&_=${Date.now()}`, {
        headers: { 'Cache-Control': 'no-cache' },
      })
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
            <StrategyCard key={s.id} s={s} walletAddr={walletAddr} loadStrategies={loadStrategies} />
          ))}
        </div>
      )}
    </div>
  )
}
