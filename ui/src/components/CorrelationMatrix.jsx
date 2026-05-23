import { useState, useEffect } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/**
 * CorrelationMatrix — compact pairwise correlation table for the strategy library.
 *
 * Fetches /api/strategies/correlation and renders a color-coded heatmap table:
 *   - Near 0  → green  (low correlation, good diversification)
 *   - Near 1  → red    (high correlation, less diversification benefit)
 *
 * Honest disclosure: all strategies track broad equity markets so
 * inter-strategy correlations are expected to be high.
 *
 * NOTE: Returns are simulated from summary statistics since raw daily series
 * are not stored in backtest_fixtures.json.
 */
export default function CorrelationMatrix({ selectedStrategyId = null }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    apiGet('/api/strategies/correlation')
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message || 'Failed to load correlation data'); setLoading(false) })
  }, [])

  if (loading) {
    return (
      <div className="card-flat" style={{ padding: 20 }}>
        <div className="label mb-2">Library Correlation</div>
        <div className="caption" style={{ color: 'var(--text-4)' }}>Computing correlation matrix…</div>
      </div>
    )
  }

  if (error || !data || !data.matrix || data.matrix.length === 0) {
    return (
      <div className="card-flat" style={{ padding: 20 }}>
        <div className="label mb-2">Library Correlation</div>
        <div className="caption" style={{ color: 'var(--text-4)' }}>
          {error || 'Need at least 2 strategies with real backtest data.'}
        </div>
      </div>
    )
  }

  const { matrix, labels, avg_pairwise_correlation, note } = data

  /**
   * Colour interpolation: green (0) → neutral grey (0.5) → red (1).
   * Uses RGBA so it works on any background.
   * green = rgba(16,185,129), neutral = rgba(120,120,120), red = rgba(239,68,68)
   */
  function cellColor(value) {
    const v = Math.max(0, Math.min(1, value))
    if (v <= 0.5) {
      // green → neutral grey
      const t = v * 2
      const r = Math.round(16  + t * (120 - 16))
      const g = Math.round(185 + t * (120 - 185))
      const b = Math.round(129 + t * (120 - 129))
      return `rgba(${r},${g},${b},${0.15 + t * 0.20})`
    } else {
      // neutral grey → red
      const t = (v - 0.5) * 2
      const r = Math.round(120 + t * (239 - 120))
      const g = Math.round(120 + t * (68  - 120))
      const b = Math.round(120 + t * (68  - 120))
      return `rgba(${r},${g},${b},${0.35 + t * 0.15})`
    }
  }

  function textColor(value) {
    return value > 0.7 ? 'var(--negative)' : value < 0.3 ? 'var(--positive)' : 'var(--text-2)'
  }

  // Show full strategy names in both headers and row labels. Names ellipsize
  // (with a hover title) only when they exceed COL_MAXW — short names render in
  // full; columns size to content (table-layout: auto).
  const COL_MAXW = 220

  return (
    <div className="card-flat" style={{ padding: 20 }}>
      <div className="flex items-center justify-between mb-3">
        <div className="label">Library Correlation</div>
        {avg_pairwise_correlation != null && (
          <div className="caption" style={{ color: 'var(--text-3)', fontSize: '0.72rem' }}>
            avg pairwise: <strong style={{ color: avg_pairwise_correlation > 0.7 ? 'var(--negative)' : 'var(--text-1)' }}>
              {avg_pairwise_correlation.toFixed(3)}
            </strong>
          </div>
        )}
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '0.75rem' }}>
          <thead>
            <tr>
              <th style={{ padding: '4px 8px', textAlign: 'left', color: 'var(--text-4)', fontWeight: 400, borderBottom: '1px solid var(--glass-border)' }}>
                Strategy
              </th>
              {labels.map((l, j) => (
                <th key={j} title={l.title} style={{
                  padding: '4px 10px', textAlign: 'center', color: 'var(--text-3)',
                  fontWeight: 400, borderBottom: '1px solid var(--glass-border)',
                  fontSize: '0.68rem', whiteSpace: 'nowrap',
                  maxWidth: COL_MAXW, overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {l.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, i) => {
              const isSelectedRow = selectedStrategyId != null && labels[i]?.id === selectedStrategyId
              return (
              <tr key={i} style={isSelectedRow ? { background: 'rgba(99,102,241,0.08)' } : undefined}>
                <td title={labels[i].title} style={{
                  padding: '4px 8px', color: isSelectedRow ? 'var(--accent)' : 'var(--text-2)',
                  fontWeight: isSelectedRow ? 700 : 500,
                  borderBottom: '1px solid var(--glass-border)',
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  maxWidth: COL_MAXW, fontSize: '0.68rem',
                }}>
                  {labels[i].title}
                  {labels[i].passes_rigor_gate && (
                    <span style={{
                      marginLeft: 6, padding: '0 4px', borderRadius: 3,
                      background: 'rgba(16,185,129,0.12)', color: 'var(--positive)',
                      fontSize: '0.6rem', fontWeight: 700, verticalAlign: 'middle',
                    }}>T1</span>
                  )}
                </td>
                {row.map((val, j) => {
                  const isSelectedCol = selectedStrategyId != null && labels[j]?.id === selectedStrategyId
                  return (
                  <td key={j} style={{
                    padding: '4px 12px', textAlign: 'center',
                    background: i === j ? 'rgba(255,255,255,0.06)' : cellColor(val),
                    borderBottom: '1px solid var(--glass-border)',
                    borderRight: isSelectedCol ? '2px solid var(--accent)' : undefined,
                    color: i === j ? 'var(--text-4)' : textColor(val),
                    fontWeight: i === j ? 400 : (isSelectedRow || isSelectedCol) ? 700 : 600,
                  }}>
                    {i === j ? '—' : val.toFixed(2)}
                  </td>
                  )
                })}
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {note && (
        <div className="caption" style={{ marginTop: 10, color: 'var(--text-4)', fontSize: '0.67rem', fontStyle: 'italic' }}>
          {note}
        </div>
      )}
      <div className="caption" style={{ marginTop: 4, color: 'var(--text-4)', fontSize: '0.67rem' }}>
        Returns simulated from backtest summary statistics. Raw daily series not stored in fixture file.
      </div>
    </div>
  )
}
