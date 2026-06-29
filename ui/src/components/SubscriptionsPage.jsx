import { useEffect, useState } from 'react'
import { apiGet, apiDelete } from '../api'
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

export default function SubscriptionsPage({ walletAddr, onNavigate }) {
  const [subscriptions, setSubscriptions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [stopping, setStopping] = useState(null)

  const load = () => {
    if (!walletAddr) { setLoading(false); return }
    setLoading(true)
    apiGet('/api/marketplace/my-subscriptions')
      .then(data => { setSubscriptions(data.subscriptions || []); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }

  useEffect(() => { load() }, [walletAddr])

  const handleUnsubscribe = async (strategyId) => {
    setStopping(strategyId)
    try {
      const walletClient = await getWalletClient()
      if (walletClient) {
        await authenticateWithSIWE(walletClient, getAddress())
      }
      await apiDelete(`/api/marketplace/subscribe/${encodeURIComponent(strategyId)}`)
      load()
    } catch (e) {
      setError(e.message || 'Failed to unsubscribe')
    } finally {
      setStopping(null)
    }
  }

  if (!walletAddr) {
    return (
      <div>
        <button className="btn-ghost mb-4" onClick={() => onNavigate?.('marketplace')}>
          ← Back to Marketplace
        </button>
        <div className="card" style={{ padding: 18 }}>
          <p className="body">Connect a wallet to see your subscriptions.</p>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <button className="btn-ghost" onClick={() => onNavigate?.('marketplace')}>
          ← Back to Marketplace
        </button>
        <button className="btn-secondary btn-sm" onClick={load}>
          Refresh
        </button>
      </div>

      <div style={{ maxWidth: 640 }}>
        <h2 className="serif text-[2rem] mb-2">My Subscriptions</h2>
        <p className="body mb-5">
          All strategies you are currently subscribed to, across all publishers.
        </p>

        {error && (
          <div className="info-box warning" style={{ padding: 12, marginBottom: 16 }}>
            {error}
          </div>
        )}

        {loading && (
          <div className="card" style={{ padding: 18 }}>
            <p className="caption">Loading subscriptions…</p>
          </div>
        )}

        {!loading && !error && subscriptions.length === 0 && (
          <div className="card" style={{ padding: 18 }}>
            <p className="body" style={{ marginBottom: 6 }}>No active subscriptions.</p>
            <p className="caption">
              Browse the{' '}
              <a
                onClick={() => onNavigate?.('marketplace')}
                style={{ color: 'var(--accent)', cursor: 'pointer', textDecoration: 'underline' }}
              >
                marketplace
              </a>
              {' '}to find strategies to subscribe to.
            </p>
          </div>
        )}

        {!loading && !error && subscriptions.length > 0 && (
          <div className="flex flex-col gap-2">
            {subscriptions.map(sub => {
              const strategyId = sub.container_name?.replace(/^archimedes-subscriber-/, '').split('-').slice(0, -1).join('-')
              return (
                <div key={sub.sub_id} className="card" style={{ padding: 14 }}>
                  <div className="flex justify-between items-center">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-sm">{strategyId || sub.sub_id}</span>
                        <span className={`tag ${sub.status === 'running' ? 'tag-accent' : 'tag-muted'}`}>
                          {sub.status}
                        </span>
                      </div>
                      <div className="caption flex gap-3 text-[var(--text-4)]">
                        <span>sub: <code>{shortAddr(sub.sub_id)}</code></span>
                        <span>wallet: <code>{shortAddr(sub.subscriber_wallet)}</code></span>
                        <span>{timeAgo(sub.subscribed_at)}</span>
                      </div>
                      {sub.publisher_endpoint && (
                        <div className="caption text-[var(--text-4)] mt-0.5">
                          publisher: <code>{sub.publisher_endpoint}</code>
                        </div>
                      )}
                    </div>
                    <div className="flex gap-2 ml-3">
                      <button
                        className="btn-ghost btn-sm"
                        onClick={() => onNavigate?.('strategy-detail', { strategyId: strategyId || sub.sub_id })}
                      >
                        View
                      </button>
                      {sub.status === 'running' && (
                        <button
                          className="btn-secondary btn-sm"
                          onClick={() => handleUnsubscribe(strategyId || sub.sub_id)}
                          disabled={stopping === strategyId}
                          style={{ color: 'var(--negative)' }}
                        >
                          {stopping === strategyId ? '…' : 'Stop'}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
