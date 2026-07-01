import { useState, useEffect, useCallback } from 'react'
import { apiGet } from '../api'

// Insights — the internal metrics dashboard (#787).
//
// Renders the live conversion instruments as a human-readable dashboard instead
// of raw JSON:
//   - Traction: human vs agent REQUEST counts (honestly labelled — these are
//     cumulative request tallies, bot-inflated, NOT unique users).
//   - Conversion funnel: distinct visitors through landed → generation_started →
//     wallet_connected → vault_deployed, with step-conversion %.
//   - Visitor insights: distinct human visitors by country + device (live only
//     once #795 is merged + the CloudFront TF applied; degrades to an empty state).
//
// All three are public GET endpoints; this page only reads them.

const FUNNEL_LABELS = {
  landed: 'Landed',
  generation_started: 'Tried Generate',
  wallet_connected: 'Connected Wallet',
  vault_deployed: 'Deployed Vault',
}

const DEVICE_LABELS = { mobile: 'Mobile', tablet: 'Tablet', desktop: 'Desktop', tv: 'TV', unknown: 'Unknown' }

const COUNTRY_NAMES = {
  US: 'United States', GB: 'United Kingdom', DE: 'Germany', BR: 'Brazil', TR: 'Türkiye',
  CA: 'Canada', FR: 'France', IN: 'India', NL: 'Netherlands', SG: 'Singapore',
  ZZ: 'Unknown / not provided',
}

const card = {
  background: 'var(--surface, #14161c)',
  border: '1px solid var(--border, #262a34)',
  borderRadius: 12,
  padding: '20px 22px',
}

function Bar({ pct, color = '#5b9dff' }) {
  return (
    <div style={{ background: 'rgba(255,255,255,0.06)', borderRadius: 6, height: 10, overflow: 'hidden' }}>
      <div style={{ width: `${Math.max(0, Math.min(100, pct))}%`, background: color, height: '100%', transition: 'width .3s' }} />
    </div>
  )
}

export default function Insights() {
  const [metrics, setMetrics] = useState(null)
  const [funnel, setFunnel] = useState(null)
  const [visitors, setVisitors] = useState(null)
  const [visitorsLive, setVisitorsLive] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [m, f] = await Promise.all([apiGet('/api/metrics'), apiGet('/api/metrics/funnel')])
      setMetrics(m)
      setFunnel(f)
    } catch (e) {
      setError(String(e.message || e))
    }
    // Visitor insights may not be deployed yet (#795) — tolerate ONLY a 404 as
    // "not live yet"; surface any other failure (500 / network) instead of
    // masking it as a missing endpoint.
    try {
      setVisitors(await apiGet('/api/metrics/visitors'))
      setVisitorsLive(true)
    } catch (e) {
      setVisitors(null)
      if (e?.status === 404) {
        setVisitorsLive(false)
      } else {
        setVisitorsLive(true)
        setError(prev => prev || `Visitor insights failed: ${e?.message || e}`)
      }
    }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const landed = funnel?.stages?.find(s => s.stage === 'landed')?.distinct_visitors ?? 0
  const totalDevices = visitors ? Object.values(visitors.devices || {}).reduce((a, b) => a + b, 0) : 0
  const maxCountry = visitors?.countries?.[0]?.distinct_visitors ?? 0

  return (
    <div style={{ maxWidth: 880, margin: '0 auto', padding: '8px 4px 48px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
        <h1 style={{ margin: '0 0 4px' }}>Insights</h1>
        <button onClick={load} disabled={loading} style={{ fontSize: 13, padding: '6px 12px', borderRadius: 8, cursor: 'pointer' }}>
          {loading ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>
      <p style={{ color: 'var(--text-dim, #8b93a7)', marginTop: 0, fontSize: 14 }}>
        Live conversion instruments for our (un-promoted) traffic. Read-only.
      </p>

      {error && (
        <div style={{ ...card, borderColor: '#a3434a', color: '#ff9aa2', marginBottom: 16 }}>
          Couldn’t load metrics: {error}
        </div>
      )}

      {/* ── Traction ── */}
      <section style={{ ...card, marginBottom: 16 }}>
        <h2 style={{ marginTop: 0, fontSize: 16 }}>Traction — requests</h2>
        <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap' }}>
          <Stat label="Human-UA requests" value={metrics?.human_count} />
          <Stat label="Agent / bot requests" value={metrics?.agent_count} />
          <Stat label="Total requests" value={metrics?.total_requests} />
        </div>
        <p style={{ color: 'var(--text-dim, #8b93a7)', fontSize: 12.5, marginBottom: 0, marginTop: 14 }}>
          ⚠️ These are <strong>cumulative request counts</strong>, not unique users — and the
          “human” bucket is inflated by browser-UA bots. The funnel below (distinct visitors,
          JS-gated so crawlers drop out) is the clean signal.
        </p>
      </section>

      {/* ── Conversion funnel ── */}
      <section style={{ ...card, marginBottom: 16 }}>
        <h2 style={{ marginTop: 0, fontSize: 16 }}>Conversion funnel — distinct visitors</h2>
        {!funnel ? (
          <Empty>Loading…</Empty>
        ) : landed === 0 ? (
          <Empty>No visitors recorded yet. The funnel started collecting when it deployed today.</Empty>
        ) : (
          <div style={{ display: 'grid', gap: 14 }}>
            {funnel.stages.map((s, i) => (
              <div key={s.stage}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 5 }}>
                  <span>{FUNNEL_LABELS[s.stage] || s.stage}</span>
                  <span style={{ color: 'var(--text-dim, #8b93a7)' }}>
                    <strong style={{ color: 'var(--text, #e6e9f0)' }}>{s.distinct_visitors}</strong>
                    {i > 0 && <> · {(s.step_conversion * 100).toFixed(0)}% of prev</>}
                  </span>
                </div>
                <Bar pct={s.pct_of_landed * 100} color={i === 0 ? '#5b9dff' : s.distinct_visitors > 0 ? '#3fb56b' : '#3a3f4b'} />
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Visitor insights (geo + device) ── */}
      <section style={card}>
        <h2 style={{ marginTop: 0, fontSize: 16 }}>Who’s visiting — geography &amp; device</h2>
        {!visitorsLive ? (
          <Empty>
            Not live yet — merge <strong>#795</strong> and run the CloudFront <code>terraform apply</code> to
            enable viewer-country capture. (Device works on the UA fallback once #795 deploys.)
          </Empty>
        ) : loading && !visitors ? (
          <Empty>Loading visitor insights…</Empty>
        ) : !visitors || ((visitors.countries?.length ?? 0) === 0 && totalDevices === 0) ? (
          <Empty>No human visitors recorded yet.</Empty>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 24 }}>
            <div>
              <h3 style={{ fontSize: 13, color: 'var(--text-dim,#8b93a7)', margin: '0 0 10px' }}>Top countries</h3>
              <div style={{ display: 'grid', gap: 10 }}>
                {(visitors.countries || []).slice(0, 8).map(c => (
                  <div key={c.code}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                      <span>{COUNTRY_NAMES[c.code] || c.code}</span>
                      <strong>{c.distinct_visitors}</strong>
                    </div>
                    <Bar pct={maxCountry ? (c.distinct_visitors / maxCountry) * 100 : 0} color="#7c6cff" />
                  </div>
                ))}
              </div>
            </div>
            <div>
              <h3 style={{ fontSize: 13, color: 'var(--text-dim,#8b93a7)', margin: '0 0 10px' }}>Device</h3>
              <div style={{ display: 'grid', gap: 10 }}>
                {Object.entries(visitors.devices || {})
                  .filter(([, n]) => n > 0)
                  .sort((a, b) => b[1] - a[1])
                  .map(([dev, n]) => (
                    <div key={dev}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                        <span>{DEVICE_LABELS[dev] || dev}</span>
                        <strong>{n}</strong>
                      </div>
                      <Bar pct={totalDevices ? (n / totalDevices) * 100 : 0} color="#3fb56b" />
                    </div>
                  ))}
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div>
      <div style={{ fontSize: 26, fontWeight: 700 }}>{value == null ? '—' : value.toLocaleString()}</div>
      <div style={{ fontSize: 12.5, color: 'var(--text-dim, #8b93a7)' }}>{label}</div>
    </div>
  )
}

function Empty({ children }) {
  return <p style={{ color: 'var(--text-dim, #8b93a7)', fontSize: 13.5, margin: 0 }}>{children}</p>
}
