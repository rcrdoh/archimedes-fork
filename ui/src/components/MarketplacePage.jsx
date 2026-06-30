import { useEffect, useState } from 'react'
import { apiGet } from '../api'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function shortAddr(a) {
  return a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '—'
}

export default function MarketplacePage({ onNavigate }) {
  const [strategies, setStrategies] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const data = await apiGet('/api/marketplace/published?status=all&limit=100')
        if (!cancelled) {
          setStrategies(data.strategies || [])
          setLoading(false)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e.message || 'Failed to load marketplace')
          setLoading(false)
        }
      }
    }
    load()
    const t = setInterval(load, 30_000)
    return () => { cancelled = true; clearInterval(t) }
  }, [])

  const runningCount = strategies.filter(s => s.status === 'running').length

  return (
    <div>
      <div style={{ maxWidth: 760, marginBottom: 28 }}>
        <h2 className="serif" style={{ fontSize: '2rem', marginBottom: 10 }}>Strategy Marketplace</h2>
        <p className="body" style={{ marginBottom: 6 }}>
          Browse live published strategies and their active subscribers.
          Publish a strategy of your own, or subscribe to one you like.
        </p>
        <p className="caption" style={{ color: 'var(--text-4)' }}>
          {runningCount} running · {strategies.length - runningCount} stopped/errored
        </p>
      </div>

      <div className="flex gap-3 mb-5">
        <button className="btn-primary" onClick={() => onNavigate?.('publish')}>
          <span className="i-lucide-upload mr-1.5" /> Publish a Strategy
        </button>
        <button className="btn-secondary" onClick={() => onNavigate?.('subscriptions')}>
          <span className="i-lucide-eye mr-1.5" /> My Subscriptions
        </button>
      </div>

      {loading && (
        <div className="card" style={{ padding: 18 }}>
          <p className="caption">Loading marketplace…</p>
        </div>
      )}

      {!loading && error && (
        <div className="info-box warning" style={{ padding: 14 }}>
          Failed to load marketplace: {error}
        </div>
      )}

      {!loading && !error && strategies.length === 0 && (
        <div className="card" style={{ padding: 18 }}>
          <p className="body" style={{ marginBottom: 6 }}>No strategies have been published yet.</p>
          <p className="caption">
            Be the first —{' '}
            <a
              onClick={() => onNavigate?.('publish')}
              style={{ color: 'var(--accent)', cursor: 'pointer', textDecoration: 'underline' }}
            >
              publish a strategy
            </a>
          </p>
        </div>
      )}

      {!loading && !error && strategies.length > 0 && (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
          {strategies.map(s => (
            <div
              key={s.strategy_id}
              className="card vault-card-clickable"
              onClick={() => onNavigate?.('strategy-detail', { strategyId: s.strategy_id })}
            >
              <div className="flex justify-between items-center mb-2">
                <span className="font-semibold text-sm" style={{ color: 'var(--text-1)' }}>
                  {s.strategy_id}
                </span>
                <span className={`tag ${s.status === 'running' ? 'tag-accent' : 'tag-muted'}`}>
                  {s.status}
                </span>
              </div>

              <div className="flex items-baseline gap-2 mt-3 mb-1">
                <span className="text-[1.4rem] font-bold">{s.active_subscriber_count}</span>
                <span className="caption">active subscriber{s.active_subscriber_count !== 1 ? 's' : ''}</span>
              </div>

              <div className="caption flex gap-3 text-[var(--text-3)] mt-1">
                <code>by {shortAddr(s.creator_wallet)}</code>
                {s.active_subscriber_count > 0 && (
                  <span style={{ color: 'var(--accent)' }}>
                    {s.subscribers.length} total
                  </span>
                )}
              </div>

              {s.status === 'running' && s.subscribers.length > 0 && (
                <div className="caption text-[var(--text-4)] mt-2" style={{ fontSize: '0.7rem' }}>
                  {s.subscribers.slice(0, 3).map(sub => (
                    <span key={sub.sub_id} className="mr-2">
                      {shortAddr(sub.subscriber_wallet)}
                    </span>
                  ))}
                  {s.subscribers.length > 3 && <span>+{s.subscribers.length - 3} more</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
