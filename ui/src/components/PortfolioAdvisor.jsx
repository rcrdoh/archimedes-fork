import { useState, useEffect } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

const RISK_PROFILES = [
  { id: 'fixed_income', label: 'Fixed Income' },
  { id: 'conservative', label: 'Conservative' },
  { id: 'moderate', label: 'Moderate' },
  { id: 'aggressive', label: 'Aggressive' },
  { id: 'hyper_risky', label: 'Hyper-Risky' },
]

function fmtPct(v) {
  return v != null ? `${(v * 100).toFixed(1)}%` : '—'
}

function fmt(v, d = 2) {
  return v != null ? v.toFixed(d) : '—'
}

function regimeColor(regime) {
  if (regime === 'risk_on') return 'var(--positive)'
  if (regime === 'crisis' || regime === 'risk_off') return 'var(--negative)'
  return '#f59e0b'
}

function AllocationBar({ label, weight, isUsdc, kelly, rigorPassed, isCandidate }) {
  const pct = (weight * 100).toFixed(1)
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 5 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 600, fontSize: '0.88rem' }}>{label}</span>
          {isUsdc && (
            <span className="caption" style={{ color: 'var(--text-4)', fontSize: '0.72rem' }}>safety floor</span>
          )}
          {!isUsdc && kelly != null && (
            <span className="caption" style={{ color: 'var(--text-3)', fontSize: '0.72rem' }}>
              Kelly f*={fmtPct(kelly)}
            </span>
          )}
          {!isUsdc && rigorPassed && (
            <span style={{
              fontSize: '0.68rem', fontWeight: 600, padding: '1px 6px', borderRadius: 3,
              background: 'rgba(16,185,129,0.12)', color: 'var(--positive)',
              border: '1px solid rgba(16,185,129,0.3)',
            }}>
              Rigor Gate ✓
            </span>
          )}
          {!isUsdc && !rigorPassed && isCandidate !== undefined && (
            <span style={{
              fontSize: '0.68rem', fontWeight: 600, padding: '1px 6px', borderRadius: 3,
              background: 'rgba(255,255,255,0.04)', color: 'var(--text-4)',
              border: '1px solid var(--glass-border)',
            }}>
              Candidate
            </span>
          )}
        </div>
        <span className="mono" style={{ fontWeight: 700, fontSize: '0.9rem' }}>{pct}%</span>
      </div>
      <div style={{ background: 'rgba(255,255,255,0.06)', borderRadius: 4, height: 10, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`,
          height: '100%',
          background: isUsdc ? 'var(--text-4)' : 'var(--accent)',
          transition: 'width 0.4s ease',
        }} />
      </div>
    </div>
  )
}

export default function PortfolioAdvisor() {
  const [selectedProfile, setSelectedProfile] = useState('moderate')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    setData(null)
    apiGet(`/api/strategies/advisor?risk_profile=${selectedProfile}`)
      .then(setData)
      .catch(e => setError(e.message || 'Failed to load advisor'))
      .finally(() => setLoading(false))
  }, [selectedProfile])

  const regime = data?.regime ?? 'unknown'
  const regimeLabel = regime.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  const rColor = regimeColor(regime)

  return (
    <div>
      {/* Header */}
      <div className="fade-up fade-up-1" style={{ maxWidth: 640, marginBottom: 28 }}>
        <h2 className="serif" style={{ fontSize: '2rem', marginBottom: 10 }}>Portfolio Advisor</h2>
        <p className="body">
          Kelly Criterion + risk-parity allocation recommendations based on the active strategy
          library and current market regime. Use this before deploying a vault.
        </p>
      </div>

      {/* Risk Profile selector */}
      <div className="card-elevated mb-6 fade-up fade-up-2" style={{ padding: 24 }}>
        <div className="label mb-3">Risk Profile</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {RISK_PROFILES.map(rp => (
            <button
              key={rp.id}
              onClick={() => setSelectedProfile(rp.id)}
              style={{
                padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer',
                fontWeight: selectedProfile === rp.id ? 700 : 400,
                fontSize: '0.82rem',
                background: selectedProfile === rp.id ? 'var(--accent)' : 'rgba(255,255,255,0.07)',
                color: selectedProfile === rp.id ? '#000' : 'var(--text-2)',
                transition: 'background 0.15s',
              }}
            >
              {rp.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <div className="caption fade-up fade-up-3">Computing allocation…</div>}
      {error && (
        <div className="info-box warning fade-up fade-up-3">
          {error.includes('No strategies') ? (
            <>No strategies with real backtest data are available yet. Run the analytics engine to generate backtest results.</>
          ) : (
            <>Advisor unavailable: {error}</>
          )}
        </div>
      )}

      {data && !error && (
        <>
          {/* Regime banner */}
          <div className="card-flat fade-up fade-up-3" style={{ padding: 20, marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: rColor, display: 'inline-block' }} />
                <span style={{ fontWeight: 700, fontSize: '1rem', color: rColor, textTransform: 'uppercase' }}>
                  {regimeLabel}
                </span>
              </div>
              <span className="caption">confidence {fmtPct(data.regime_confidence)}</span>
            </div>
            {data.regime_narrative && (
              <p className="body" style={{ margin: 0, color: 'var(--text-3)', lineHeight: 1.5 }}>
                {data.regime_narrative}
              </p>
            )}
          </div>

          {/* Allocation breakdown */}
          <div className="card-elevated fade-up fade-up-4" style={{ padding: 24, marginBottom: 20 }}>
            <div className="label mb-4">Recommended Allocation</div>

            {/* USDC floor */}
            <AllocationBar
              label="USDC"
              weight={data.usdc_weight ?? 0}
              isUsdc
            />

            {/* Synth allocations */}
            {(data.allocations || []).map((a) => (
              <AllocationBar
                key={a.id}
                label={a.symbol || a.title?.slice(0, 30) || a.id}
                weight={a.weight}
                kelly={a.kelly_fraction}
                rigorPassed={a.passes_rigor_gate}
                isCandidate={!a.passes_rigor_gate}
              />
            ))}

            {data.allocations?.length === 0 && (
              <div className="caption" style={{ color: 'var(--text-4)' }}>
                No strategy allocations — all synth budget held as USDC under current regime conditions.
              </div>
            )}
          </div>

          {/* Expected portfolio metrics */}
          {data.expected_portfolio && (
            <div className="card-flat fade-up fade-up-5" style={{ padding: 20, marginBottom: 20 }}>
              <div className="label mb-3">Expected Portfolio Metrics</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
                <div>
                  <div className="caption">Sharpe Ratio</div>
                  <div style={{ fontWeight: 700, fontSize: '1.4rem' }}>
                    {fmt(data.expected_portfolio.sharpe)}
                  </div>
                </div>
                <div>
                  <div className="caption">CAGR</div>
                  <div className="positive" style={{ fontWeight: 700, fontSize: '1.4rem' }}>
                    {fmtPct(data.expected_portfolio.cagr)}
                  </div>
                </div>
                <div>
                  <div className="caption">Max Drawdown</div>
                  <div className="negative" style={{ fontWeight: 700, fontSize: '1.4rem' }}>
                    -{fmtPct(data.expected_portfolio.max_drawdown)}
                  </div>
                </div>
              </div>
              <p className="caption" style={{ marginTop: 12, color: 'var(--text-4)' }}>
                Weighted average of strategy metrics at current allocations.
                Actual results will vary — regime shifts and rebalancing will change weights over time.
              </p>
            </div>
          )}

          {/* Strategy detail table */}
          {data.allocations?.length > 0 && (
            <div className="fade-up fade-up-5">
              <div className="label mb-3">Strategy Breakdown</div>
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Strategy</th>
                      <th className="text-right">Weight</th>
                      <th className="text-right">Sharpe</th>
                      <th className="text-right">CAGR</th>
                      <th className="text-right">Kelly f*</th>
                      <th>Rigor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.allocations.map(a => (
                      <tr key={a.id}>
                        <td style={{ maxWidth: 240 }}>
                          <div style={{ fontWeight: 500, fontSize: '0.83rem' }}>{a.title?.slice(0, 50)}{a.title?.length > 50 ? '…' : ''}</div>
                          <div className="caption" style={{ color: 'var(--text-4)' }}>{a.symbol}</div>
                        </td>
                        <td className="text-right mono">{fmtPct(a.weight)}</td>
                        <td className="text-right mono">{fmt(a.sharpe)}</td>
                        <td className="text-right positive mono">{fmtPct(a.cagr)}</td>
                        <td className="text-right mono">{fmtPct(a.kelly_fraction)}</td>
                        <td>
                          {a.passes_rigor_gate ? (
                            <span style={{ color: 'var(--positive)', fontSize: '0.72rem', fontWeight: 600 }}>✓ Passed</span>
                          ) : (
                            <span style={{ color: 'var(--text-4)', fontSize: '0.72rem' }}>Candidate</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
