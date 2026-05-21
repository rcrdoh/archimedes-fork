import { useState, useEffect } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/**
 * EfficientFrontier — SVG scatter plot of the MVO efficient frontier.
 *
 * Fetches /api/strategies/frontier and renders a compact (~300px tall) card
 * showing volatility on the x-axis and expected return on the y-axis.
 * The min-variance and max-Sharpe points are highlighted.
 *
 * NOTE: The frontier is computed from synthetic return streams simulated from
 * backtest summary statistics (SR, CAGR) — raw daily series are not stored
 * in the fixture file. This is disclosed in the chart footer.
 */
export default function EfficientFrontier() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    apiGet('/api/strategies/frontier')
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message || 'Failed to load frontier'); setLoading(false) })
  }, [])

  if (loading) {
    return (
      <div className="card-flat" style={{ padding: 20 }}>
        <div className="label mb-2">Efficient Frontier</div>
        <div className="caption" style={{ color: 'var(--text-4)' }}>Computing frontier…</div>
      </div>
    )
  }

  if (error || !data || !Array.isArray(data?.frontier) || data.frontier.length === 0) {
    return (
      <div className="card-flat" style={{ padding: 20 }}>
        <div className="label mb-2">Efficient Frontier</div>
        <div className="caption" style={{ color: 'var(--text-4)' }}>
          {error || (data?.message ?? 'Need at least 2 Tier-1 strategies to plot frontier.')}
        </div>
      </div>
    )
  }

  const frontier = data.frontier
  const strategies = data.strategies || []

  // Map frontier points to SVG pixel coordinates
  const SVG_W = 480
  const SVG_H = 300
  const PAD_L = 52
  const PAD_R = 20
  const PAD_T = 20
  const PAD_B = 44

  const vols = frontier.map(p => p.vol)
  const rets = frontier.map(p => p.return)
  const minVol = Math.min(...vols)
  const maxVol = Math.max(...vols)
  const minRet = Math.min(...rets)
  const maxRet = Math.max(...rets)
  const volRange = maxVol - minVol || 1
  const retRange = maxRet - minRet || 1

  // Add 5% padding on each side
  const vPad = volRange * 0.05
  const rPad = retRange * 0.05

  function toX(vol) {
    return PAD_L + ((vol - minVol + vPad) / (volRange + 2 * vPad)) * (SVG_W - PAD_L - PAD_R)
  }
  function toY(ret) {
    return SVG_H - PAD_B - ((ret - minRet + rPad) / (retRange + 2 * rPad)) * (SVG_H - PAD_T - PAD_B)
  }

  // Min-variance point = lowest vol
  const minVarIdx = vols.indexOf(minVol)
  // Max-Sharpe point = highest (return / vol) ratio
  const sharpes = frontier.map(p => p.vol > 0 ? p.return / p.vol : 0)
  const maxSharpeIdx = sharpes.indexOf(Math.max(...sharpes))

  // Build polyline path
  const polyPoints = frontier.map(p => `${toX(p.vol).toFixed(1)},${toY(p.return).toFixed(1)}`).join(' ')

  // Y-axis tick labels (4 ticks)
  const yTicks = [0, 1, 2, 3].map(i => {
    const ret = minRet + (retRange * i) / 3
    return { y: toY(ret), label: `${(ret * 100).toFixed(1)}%` }
  })

  // X-axis tick labels (4 ticks)
  const xTicks = [0, 1, 2, 3].map(i => {
    const vol = minVol + (volRange * i) / 3
    return { x: toX(vol), label: `${(vol * 100).toFixed(1)}%` }
  })

  return (
    <div className="card-flat" style={{ padding: 20 }}>
      <div className="flex items-center justify-between mb-3">
        <div className="label">Efficient Frontier</div>
        <div className="caption" style={{ color: 'var(--text-4)', fontSize: '0.68rem' }}>
          MVO · {strategies.length} Tier-1 strategies
        </div>
      </div>

      <svg
        viewBox={`0 0 ${SVG_W} ${SVG_H}`}
        width="100%"
        style={{ display: 'block', maxHeight: 300 }}
        aria-label="Efficient frontier chart"
      >
        {/* Grid lines */}
        {yTicks.map((t, i) => (
          <line key={i} x1={PAD_L} y1={t.y} x2={SVG_W - PAD_R} y2={t.y}
            stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
        ))}

        {/* Axes */}
        <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={SVG_H - PAD_B}
          stroke="rgba(255,255,255,0.2)" strokeWidth="1" />
        <line x1={PAD_L} y1={SVG_H - PAD_B} x2={SVG_W - PAD_R} y2={SVG_H - PAD_B}
          stroke="rgba(255,255,255,0.2)" strokeWidth="1" />

        {/* Y-axis labels */}
        {yTicks.map((t, i) => (
          <text key={i} x={PAD_L - 6} y={t.y + 4}
            textAnchor="end" fill="rgba(255,255,255,0.35)" fontSize="9">
            {t.label}
          </text>
        ))}

        {/* X-axis labels */}
        {xTicks.map((t, i) => (
          <text key={i} x={t.x} y={SVG_H - PAD_B + 14}
            textAnchor="middle" fill="rgba(255,255,255,0.35)" fontSize="9">
            {t.label}
          </text>
        ))}

        {/* Axis titles */}
        <text x={PAD_L + (SVG_W - PAD_L - PAD_R) / 2} y={SVG_H - 4}
          textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="9">
          Annualised Volatility
        </text>
        <text x={10} y={PAD_T + (SVG_H - PAD_T - PAD_B) / 2}
          textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="9"
          transform={`rotate(-90, 10, ${PAD_T + (SVG_H - PAD_T - PAD_B) / 2})`}>
          Expected Return
        </text>

        {/* Frontier curve */}
        <polyline
          points={polyPoints}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2"
          strokeLinejoin="round"
        />

        {/* All frontier dots */}
        {frontier.map((p, i) => (
          <circle key={i} cx={toX(p.vol)} cy={toY(p.return)} r={3}
            fill="var(--accent)" opacity={0.5} />
        ))}

        {/* Min-variance highlight */}
        {minVarIdx >= 0 && (
          <>
            <circle cx={toX(frontier[minVarIdx].vol)} cy={toY(frontier[minVarIdx].return)}
              r={6} fill="var(--positive)" opacity={0.9} />
            <text x={toX(frontier[minVarIdx].vol) + 9} y={toY(frontier[minVarIdx].return) + 4}
              fill="var(--positive)" fontSize="9" fontWeight="600">
              Min Var
            </text>
          </>
        )}

        {/* Max-Sharpe highlight */}
        {maxSharpeIdx >= 0 && maxSharpeIdx !== minVarIdx && (
          <>
            <circle cx={toX(frontier[maxSharpeIdx].vol)} cy={toY(frontier[maxSharpeIdx].return)}
              r={6} fill="var(--accent)" opacity={1} stroke="#fff" strokeWidth="1.5" />
            <text x={toX(frontier[maxSharpeIdx].vol) + 9} y={toY(frontier[maxSharpeIdx].return) + 4}
              fill="var(--accent)" fontSize="9" fontWeight="600">
              Max Sharpe
            </text>
          </>
        )}
      </svg>

      {/* Strategy legend */}
      {strategies.length > 0 && (
        <div style={{ marginTop: 10, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {strategies.map(s => (
            <span key={s.id} className="caption" style={{
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid var(--glass-border)',
              borderRadius: 4,
              padding: '2px 6px',
              fontSize: '0.68rem',
            }}>
              {s.title.slice(0, 28)}{s.title.length > 28 ? '…' : ''}
            </span>
          ))}
        </div>
      )}

      <div className="caption" style={{ marginTop: 8, color: 'var(--text-4)', fontSize: '0.67rem' }}>
        Returns simulated from backtest summary statistics (SR + CAGR).
        Raw daily series not stored in fixture file.
      </div>
    </div>
  )
}
