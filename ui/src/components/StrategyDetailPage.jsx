import { useEffect, useState } from 'react'
import { apiGet, apiPost, apiDelete } from '../api'
import { getWalletClient, getAddress } from '../config'
import { authenticateWithSIWE } from '../siwe'

function shortAddr(a) {
  return a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '—'
}

function timeAgo(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  const secs = Math.floor((Date.now() - d.getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

export default function StrategyDetailPage({ strategyId, walletAddr, onNavigate }) {
  const [strategy, setStrategy] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [subscribing, setSubscribing] = useState(false)
  const [subscribeError, setSubscribeError] = useState('')
  const [subscribed, setSubscribed] = useState(false)

  const load = () => {
    if (!strategyId) return
    setLoading(true)
    apiGet(`/api/marketplace/published/${encodeURIComponent(strategyId)}`)
      .then(data => { setStrategy(data); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }

  useEffect(() => { load() }, [strategyId])

  const handleSubscribe = async () => {
    if (!walletAddr) {
      setSubscribeError('Connect a wallet first')
      return
    }
    setSubscribing(true)
    setSubscribeError('')
    try {
      // SIWE auth — ensure session is fresh
      const walletClient = await getWalletClient()
      if (!walletClient) throw new Error('No wallet client available')
      const addr = getAddress()
      await authenticateWithSIWE(walletClient, addr)

      await apiPost('/api/marketplace/subscribe', {
        strategy_id: strategyId,
        pool_id: strategy.pool_id || '0x' + '0'.repeat(64),
        sub_id: '0x' + '0'.repeat(64),
        initial_deposit_usdc: 10_000_000,
      })
      setSubscribed(true)
      load() // refresh
    } catch (e) {
      setSubscribeError(e.message || 'Subscription failed')
    } finally {
      setSubscribing(false)
    }
  }

  const handleUnsubscribe = async () => {
    setSubscribing(true)
    try {
      const walletClient = await getWalletClient()
      if (walletClient) {
        await authenticateWithSIWE(walletClient, getAddress())
      }
      await apiDelete(`/api/marketplace/subscribe/${encodeURIComponent(strategyId)}`)
      setSubscribed(false)
      load()
    } catch (e) {
      setSubscribeError(e.message || 'Unsubscribe failed')
    } finally {
      setSubscribing(false)
    }
  }

  const mySub = strategy?.subscribers?.find(s =>
    s.subscriber_wallet?.toLowerCase() === walletAddr?.toLowerCase()
  )

  if (loading) {
    return <div className="card" style={{ padding: 18 }}><p className="caption">Loading…</p></div>
  }

  if (error) {
    return (
      <div>
        <div className="info-box warning" style={{ padding: 14, marginBottom: 16 }}>
          {error}
        </div>
        <button className="btn-secondary" onClick={() => onNavigate?.('marketplace')}>
          ← Back to Marketplace
        </button>
      </div>
    )
  }

  if (!strategy) {
    return (
      <div>
        <div className="card" style={{ padding: 18, marginBottom: 16 }}>
          <p className="body">Strategy not found.</p>
        </div>
        <button className="btn-secondary" onClick={() => onNavigate?.('marketplace')}>
          ← Back to Marketplace
        </button>
      </div>
    )
  }

  return (
    <div>
      <button className="btn-ghost mb-4" onClick={() => onNavigate?.('marketplace')}>
        ← Back to Marketplace
      </button>

      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <div className="flex justify-between items-start mb-3">
          <div>
            <h2 className="serif text-[1.6rem]">{strategy.strategy_id}</h2>
            <p className="caption text-[var(--text-4)] mt-1">
              by {shortAddr(strategy.creator_wallet)}
              {' · '}
              <span className={strategy.status === 'running' ? 'text-[var(--positive)]' : 'text-[var(--text-3)]'}>
                {strategy.status}
              </span>
            </p>
          </div>
          <span className="tag tag-accent">{strategy.active_subscriber_count} active</span>
        </div>

        <div className="grid gap-3" style={{ gridTemplateColumns: '1fr 1fr', fontSize: '0.8rem' }}>
          <div><span className="caption text-[var(--text-4)]">Pool ID</span><br /><code>{shortAddr(strategy.pool_id)}</code></div>
          <div><span className="caption text-[var(--text-4)]">Vault</span><br /><code>{shortAddr(strategy.vault_address) || '—'}</code></div>
          <div><span className="caption text-[var(--text-4)]">Published</span><br />{timeAgo(strategy.published_at)}</div>
          <div><span className="caption text-[var(--text-4)]">Endpoint</span><br /><code>{strategy.publisher_endpoint || '—'}</code></div>
        </div>

        {strategy.status === 'running' && walletAddr && (
          <div className="mt-4 pt-3" style={{ borderTop: '1px solid var(--glass-border)' }}>
            {mySub ? (
              <div className="flex items-center gap-3">
                <span className="caption" style={{ color: 'var(--positive)' }}>
                  ✓ You are subscribed
                </span>
                <button className="btn-secondary btn-sm" onClick={handleUnsubscribe} disabled={subscribing}>
                  {subscribing ? '…' : 'Unsubscribe'}
                </button>
              </div>
            ) : (
              <div>
                {subscribed ? (
                  <div className="flex items-center gap-3">
                    <span className="caption" style={{ color: 'var(--positive)' }}>Subscribed!</span>
                    <button className="btn-secondary btn-sm" onClick={() => onNavigate?.('subscriptions')}>
                      View My Subscriptions
                    </button>
                  </div>
                ) : (
                  <div>
                    <button className="btn-primary" onClick={handleSubscribe} disabled={subscribing}>
                      {subscribing ? 'Subscribing…' : 'Subscribe to this Strategy'}
                    </button>
                    {subscribeError && (
                      <p className="caption mt-2" style={{ color: 'var(--negative)' }}>{subscribeError}</p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Subscribers list */}
      {strategy.subscribers && strategy.subscribers.length > 0 && (
        <div>
          <h3 className="font-semibold mb-3">Subscribers ({strategy.subscribers.length})</h3>
          <div className="flex flex-col gap-2">
            {strategy.subscribers.map(sub => (
              <div key={sub.sub_id} className="card" style={{ padding: 14 }}>
                <div className="flex justify-between items-center">
                  <div>
                    <code className="text-sm">{shortAddr(sub.subscriber_wallet)}</code>
                    <span className={`tag ml-2 ${sub.status === 'running' ? 'tag-accent' : 'tag-muted'}`}>
                      {sub.status}
                    </span>
                  </div>
                  <span className="caption text-[var(--text-4)]">{timeAgo(sub.subscribed_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
