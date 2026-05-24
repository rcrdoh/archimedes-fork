import { useEffect, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// Renders the stress_engine.py output for a portfolio. Six canonical historical
// shocks per backend (equity crash 2008, COVID 2020, rate shock 2022, EM crisis
// 2018, etc.). Per [`docs/chuan-architecture-survey.md`](../../docs/chuan-architecture-survey.md)
// gap #13 — the engine exists but had no UI surface.
//
// Phase 4 scaffold: surfaces scenarios + portfolio-PnL view against a
// caller-supplied allocations array. Drop into Portfolio.jsx (next to or under
// the Allocation Advisor) for the demo path.

function fmtPct(v) {
  if (v == null || !Number.isFinite(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${(Number(v) * 100).toFixed(2)}%`
}

function fmtUsd(v) {
  if (v == null || !Number.isFinite(v)) return '—'
  return `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

// Default demo allocation — diversified placeholder so the panel renders
// something useful when no user portfolio is plugged in. The caller can pass
// `allocations` + `usdcWeight` to override.
const DEFAULT_ALLOCATIONS = [
  { symbol: 'sSPY', token_address: '', weight_bps: 4000 },
  { symbol: 'sQQQ', token_address: '', weight_bps: 2000 },
  { symbol: 'sBTC', token_address: '', weight_bps: 1500 },
  { symbol: 'sGOLD', token_address: '', weight_bps: 500 },
]
const DEFAULT_USDC_WEIGHT = 0.20

export default function StressScenarioPanel({ allocations, usdcWeight, portfolioValue = 10000 }) {
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const allocs = (allocations && allocations.length > 0) ? allocations : DEFAULT_ALLOCATIONS
  const usdc = usdcWeight != null ? usdcWeight : DEFAULT_USDC_WEIGHT
  const isPlaceholder = !allocations || allocations.length === 0

  useEffect(() => {
    let cancelled = false
    async function run() {
      setLoading(true)
      setError('')
      try {
        const res = await fetch(`${API_BASE}/api/strategies/stress/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            allocations: allocs,
            scenario: 'all',
            usdc_weight: usdc,
          }),
        })
        if (!res.ok) throw new Error(await res.text())
        const data = await res.json()
        if (!cancelled) setResults(data.results || [])
      } catch (e) {
        if (!cancelled) setError(e.message || 'Failed to run stress test')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => { cancelled = true }
  }, [JSON.stringify(allocs), usdc])

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <div>
          <div className="label">Stress scenarios</div>
          <p className="caption mt-1 leading-relaxed">
            Six historical shocks applied to your allocation per
            <code style={{ marginLeft: 4 }}>stress_engine.py</code>. Each scenario
            shocks asset classes by historically-calibrated amounts;
            portfolio P&amp;L is the weighted sum.
          </p>
        </div>
      </div>

      {isPlaceholder && (
        <div className="info-box mb-3" style={{ fontSize: '0.8rem' }}>
          Showing default demo allocation (40% SPY / 20% QQQ / 15% BTC / 5% GOLD / 20% USDC).
          Pass real <code>allocations</code> from a vault to see your own portfolio's shock surface.
        </div>
      )}

      {loading && <div className="caption">Computing scenarios…</div>}
      {error && <div className="info-box warning">{error}</div>}

      {results && results.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--glass-border)]">
          <table className="lib-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
            <thead>
              <tr style={{ background: 'rgba(255,255,255,0.03)', textAlign: 'left', borderBottom: '1px solid var(--glass-border)' }}>
                <th style={{ padding: '10px 14px' }}>Scenario</th>
                <th style={{ padding: '10px 14px', textAlign: 'right' }}>P&amp;L %</th>
                <th style={{ padding: '10px 14px', textAlign: 'right' }}>Value after</th>
                <th style={{ padding: '10px 14px' }}>Description</th>
              </tr>
            </thead>
            <tbody>
              {results.map(r => {
                const pnl = r.portfolio_pnl
                const negativeClass = pnl < 0 ? 'negative' : pnl > 0 ? 'positive' : ''
                return (
                  <tr key={r.scenario} style={{ borderBottom: '1px solid var(--glass-border)' }}>
                    <td style={{ padding: '8px 14px', fontWeight: 600 }}>{r.label}</td>
                    <td className={`mono ${negativeClass}`} style={{ padding: '8px 14px', textAlign: 'right' }}>
                      {fmtPct(pnl)}
                    </td>
                    <td className="mono" style={{ padding: '8px 14px', textAlign: 'right' }}>
                      {fmtUsd(portfolioValue * (1 + (pnl || 0)))}
                    </td>
                    <td className="caption" style={{ padding: '8px 14px', maxWidth: 320 }}>
                      {r.description}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="caption mt-3 text-[var(--text-4)] leading-relaxed">
        Beta-1 per-asset-class shock model — coarse on purpose so the assumptions
        are inspectable. Factor models + Monte Carlo tail-risk are a v2 problem.
      </p>
    </div>
  )
}
