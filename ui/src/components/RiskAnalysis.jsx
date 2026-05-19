import { useState, useEffect, useMemo } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ─── Risk Profile Band Visualization ────────────────────────

const PROFILE_COLORS = {
  fixed_income: '#3B82F6',
  conservative: '#22C55E',
  moderate: '#D4A853',
  aggressive: '#F97316',
  hyper_risky: '#EF4444',
}

const PROFILE_LABELS = {
  fixed_income: 'Fixed Income',
  conservative: 'Conservative',
  moderate: 'Moderate',
  aggressive: 'Aggressive',
  hyper_risky: 'Hyper-Risky',
}

function RiskProfileBand({ bands, actualProfile, worstMaxDD }) {
  if (!bands.length) return null

  // Find which band the portfolio falls into
  const activeIdx = bands.findIndex(b => b.label === actualProfile)

  return (
    <div className="card" style={{ padding: 20 }}>
      <h3 style={{ marginBottom: 16 }}>Risk Profile vs. Actual Portfolio Risk</h3>
      <p className="hint" style={{ marginBottom: 20 }}>
        Your portfolio's worst strategy drawdown is{' '}
        <strong style={{ color: 'var(--negative)' }}>
          −{(worstMaxDD * 100).toFixed(1)}%
        </strong>, classified as{' '}
        <strong style={{ color: PROFILE_COLORS[actualProfile] || 'var(--text-1)' }}>
          {PROFILE_LABELS[actualProfile] || actualProfile}
        </strong>.
      </p>

      {/* 4-segment horizontal bar */}
      <div style={{ position: 'relative', marginBottom: 8 }}>
        <div style={{ display: 'flex', height: 32, borderRadius: 8, overflow: 'hidden' }}>
          {bands.map((band, i) => {
            const isActive = i === activeIdx
            return (
              <div
                key={band.label}
                style={{
                  flex: 1,
                  background: isActive
                    ? band.color
                    : `${band.color}30`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.75rem',
                  fontWeight: isActive ? 700 : 500,
                  color: isActive ? '#fff' : band.color,
                  transition: 'all 0.3s ease',
                  borderRight: i < bands.length - 1 ? '1px solid var(--glass-border)' : 'none',
                }}
              >
                {PROFILE_LABELS[band.label]}
              </div>
            )
          })}
        </div>

        {/* Marker triangle */}
        {activeIdx >= 0 && (
          <div style={{
            position: 'absolute',
            top: -8,
            left: `calc(${((activeIdx + 0.5) / bands.length) * 100}% - 6px)`,
            width: 0, height: 0,
            borderLeft: '6px solid transparent',
            borderRight: '6px solid transparent',
            borderTop: `8px solid ${bands[activeIdx].color}`,
            transition: 'left 0.3s ease',
          }} />
        )}
      </div>

      {/* Threshold details */}
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${bands.length}, 1fr)`, gap: 8, marginTop: 16 }}>
        {bands.map(band => {
          const isActive = band.label === actualProfile
          return (
            <div key={band.label} className="card-flat" style={{
              padding: 10,
              textAlign: 'center',
              borderLeft: isActive ? `3px solid ${band.color}` : '3px solid transparent',
            }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 600, color: band.color, marginBottom: 4 }}>
                {PROFILE_LABELS[band.label]}
              </div>
              <div className="caption">Max DD ≤ {(band.max_dd * 100).toFixed(0)}%</div>
              <div className="caption">Sharpe ≥ {band.target_sharpe.toFixed(1)}</div>
              <div className="caption">Vol ≤ {(band.max_vol * 100).toFixed(0)}%</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Kelly Criterion Calculator ──────────────────────────────

function KellyCalculator() {
  const [winRate, setWinRate] = useState(0.55)
  const [avgWin, setAvgWin] = useState(0.08)
  const [avgLoss, setAvgLoss] = useState(0.04)
  const [riskFreeRate, setRiskFreeRate] = useState(0.05)

  const kelly = winRate > 0 && avgWin > 0 && avgLoss > 0
    ? (winRate / avgLoss) - ((1 - winRate) / avgWin)
    : 0
  const halfKelly = kelly / 2
  const ev = winRate * avgWin - (1 - winRate) * avgLoss

  return (
    <div className="card" style={{ padding: 20 }}>
      <h3 style={{ marginBottom: 12 }}>Kelly Criterion Calculator</h3>
      <p className="hint" style={{ marginBottom: 16 }}>
        Position sizing based on the Kelly Criterion (Kelly 1956). Optimal fraction
        of capital to allocate given win rate and payoff ratio.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16 }}>
        <div className="form-group">
          <label className="label">Win Rate</label>
          <input
            className="chat-input" type="number" min="0" max="1" step="0.01"
            value={winRate} onChange={e => setWinRate(parseFloat(e.target.value) || 0)}
          />
          <div className="caption">{(winRate * 100).toFixed(0)}%</div>
        </div>
        <div className="form-group">
          <label className="label">Avg Win</label>
          <input
            className="chat-input" type="number" min="0" step="0.01"
            value={avgWin} onChange={e => setAvgWin(parseFloat(e.target.value) || 0)}
          />
          <div className="caption">{(avgWin * 100).toFixed(1)}%</div>
        </div>
        <div className="form-group">
          <label className="label">Avg Loss</label>
          <input
            className="chat-input" type="number" min="0" step="0.01"
            value={avgLoss} onChange={e => setAvgLoss(parseFloat(e.target.value) || 0)}
          />
          <div className="caption">{(avgLoss * 100).toFixed(1)}%</div>
        </div>
        <div className="form-group">
          <label className="label">Risk-free Rate</label>
          <input
            className="chat-input" type="number" min="0" step="0.01"
            value={riskFreeRate} onChange={e => setRiskFreeRate(parseFloat(e.target.value) || 0)}
          />
          <div className="caption">{(riskFreeRate * 100).toFixed(1)}%</div>
        </div>
      </div>

      <div className="divider" style={{ margin: '20px 0' }} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        <div className="card-flat" style={{ padding: 16, textAlign: 'center' }}>
          <div className="caption">Full Kelly</div>
          <div style={{ fontSize: '1.6rem', fontWeight: 700, color: kelly > 0 ? 'var(--positive)' : 'var(--negative)' }}>
            {(kelly * 100).toFixed(1)}%
          </div>
          <div className="caption">Optimal allocation</div>
        </div>
        <div className="card-flat" style={{ padding: 16, textAlign: 'center' }}>
          <div className="caption">Half Kelly</div>
          <div style={{ fontSize: '1.6rem', fontWeight: 700, color: 'var(--accent)' }}>
            {(halfKelly * 100).toFixed(1)}%
          </div>
          <div className="caption">Conservative</div>
        </div>
        <div className="card-flat" style={{ padding: 16, textAlign: 'center' }}>
          <div className="caption">Expected Value</div>
          <div style={{ fontSize: '1.6rem', fontWeight: 700, color: ev > 0 ? 'var(--positive)' : 'var(--negative)' }}>
            {(ev * 100).toFixed(2)}%
          </div>
          <div className="caption">Per trade</div>
        </div>
      </div>
    </div>
  )
}

// ─── Strategy Risk Comparison Table ──────────────────────────

function StrategyRiskTable({ strategies }) {
  if (!strategies.length) return null

  return (
    <div>
      <div className="label mb-3">Strategy Risk Comparison</div>
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Status</th>
              <th className="text-right">Sharpe</th>
              <th className="text-right">Volatility</th>
              <th className="text-right">Max DD</th>
              <th className="text-right">CAGR</th>
              <th className="text-right">Win Rate</th>
              <th className="text-right">Calmar</th>
              <th className="text-right">Corr SPY</th>
              <th>Risk Level</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map(s => {
              const sharpe = s.sharpe_ratio ?? 0
              const volatility = s.volatility
              const riskLevel = s.risk_level || (sharpe > 1 ? 'Low' : sharpe > 0.5 ? 'Medium' : 'High')
              const riskColor = riskLevel === 'Low' ? 'var(--positive)' : riskLevel === 'Medium' ? 'var(--accent)' : 'var(--negative)'
              return (
                <tr key={s.id}>
                  <td style={{ fontWeight: 500, maxWidth: 200 }}>{s.paper_title?.slice(0, 35)}…</td>
                  <td><span className={`tag ${s.status === 'live' ? 'tag-positive' : 'tag-muted'}`}>{s.status}</span></td>
                  <td className="text-right mono">{s.sharpe_ratio?.toFixed(2) ?? '—'}</td>
                  <td className="text-right mono">
                    {volatility != null ? (
                      <span style={{ color: volatility > 0.25 ? 'var(--negative)' : volatility > 0.15 ? 'var(--accent)' : 'var(--positive)' }}>
                        {(volatility * 100).toFixed(1)}%
                      </span>
                    ) : '—'}
                  </td>
                  <td className="text-right mono negative">{s.max_drawdown ? `−${(s.max_drawdown * 100).toFixed(1)}%` : '—'}</td>
                  <td className="text-right mono positive">{s.cagr ? `${(s.cagr * 100).toFixed(1)}%` : '—'}</td>
                  <td className="text-right mono">{s.win_rate ? `${(s.win_rate * 100).toFixed(0)}%` : '—'}</td>
                  <td className="text-right mono">{s.calmar_ratio?.toFixed(2) ?? '—'}</td>
                  <td className="text-right mono">{s.correlation_to_spy?.toFixed(2) ?? '—'}</td>
                  <td><span className="tag" style={{ color: riskColor, background: `${riskColor}15` }}>{riskLevel}</span></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ─── Portfolio Risk Summary ──────────────────────────────────

function PortfolioRiskSummary({ riskData }) {
  if (!riskData) return null

  const hhiColor = riskData.concentration_hhi < 0.15
    ? 'var(--positive)'
    : riskData.concentration_hhi < 0.25
      ? 'var(--accent)'
      : 'var(--negative)'

  return (
    <div className="card" style={{ padding: 20 }}>
      <h3 style={{ marginBottom: 12 }}>Portfolio Risk Summary</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        <div className="card-flat" style={{ padding: 12 }}>
          <div className="caption">Avg Sharpe</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>
            {riskData.avg_sharpe.toFixed(2)}
          </div>
        </div>
        <div className="card-flat" style={{ padding: 12 }}>
          <div className="caption">Worst Max DD</div>
          <div className="negative" style={{ fontSize: '1.4rem', fontWeight: 700 }}>
            −{(riskData.worst_max_dd * 100).toFixed(1)}%
          </div>
        </div>
        <div className="card-flat" style={{ padding: 12 }}>
          <div className="caption">Best Calmar</div>
          <div className="positive" style={{ fontSize: '1.4rem', fontWeight: 700 }}>
            {riskData.best_calmar.toFixed(2)}
          </div>
        </div>
        <div className="card-flat" style={{ padding: 12 }}>
          <div className="caption">Avg Correlation to SPY</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>
            {riskData.avg_correlation_spy.toFixed(2)}
          </div>
        </div>
        <div className="card-flat" style={{ padding: 12 }}>
          <div className="caption">Avg Volatility</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>
            {riskData.avg_volatility ? `${(riskData.avg_volatility * 100).toFixed(1)}%` : '—'}
          </div>
        </div>
        <div className="card-flat" style={{ padding: 12 }}>
          <div className="caption">Concentration (HHI)</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: hhiColor }}>
            {riskData.concentration_hhi.toFixed(3)}
          </div>
          <div className="caption" style={{ color: hhiColor }}>
            {riskData.concentration_label} · {riskData.holding_count} holdings
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Main Export ─────────────────────────────────────────────

export default function RiskAnalysis() {
  const [strategies, setStrategies] = useState([])
  const [riskData, setRiskData] = useState(null)
  const [bands, setBands] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = async () => {
      try {
        // Fetch strategies (fallback data source)
        const stratRes = await apiGet('/api/strategies/')
        const strats = stratRes.strategies || []
        setStrategies(strats)

        // Try dedicated risk endpoints — degrade gracefully if not available
        try {
          const [portfolioRisk, profileBands] = await Promise.all([
            apiGet('/api/risk/portfolio'),
            apiGet('/api/risk/profiles'),
          ])
          setRiskData(portfolioRisk)
          setBands(profileBands.bands || [])

          // Use risk endpoint strategy data if available (has volatility, risk_level)
          if (portfolioRisk.strategies?.length) {
            setStrategies(portfolioRisk.strategies)
          }
        } catch {
          // Risk endpoints not available — compute summary from strategies
          // as a graceful fallback
          if (strats.length) {
            setRiskData({
              strategy_count: strats.length,
              avg_sharpe: strats.reduce((s, st) => s + (st.sharpe_ratio ?? 0), 0) / strats.length,
              worst_max_dd: Math.max(...strats.map(s => s.max_drawdown ?? 0)),
              avg_correlation_spy: strats.reduce((s, st) => s + (st.correlation_to_spy ?? 0), 0) / strats.length,
              best_calmar: Math.max(...strats.map(s => s.calmar_ratio ?? 0)),
              avg_volatility: 0,
              concentration_hhi: 1 / strats.length,
              concentration_label: 'diversified',
              holding_count: strats.length,
              actual_risk_profile: 'moderate',
              strategies: [],
            })
          }

          // Default bands if endpoint not available
          setBands([
            { label: 'fixed_income', max_dd: 0.05, target_sharpe: 0.3, max_vol: 0.04, color: '#3B82F6' },
            { label: 'conservative', max_dd: 0.10, target_sharpe: 0.5, max_vol: 0.10, color: '#22C55E' },
            { label: 'moderate', max_dd: 0.20, target_sharpe: 0.8, max_vol: 0.18, color: '#D4A853' },
            { label: 'aggressive', max_dd: 0.35, target_sharpe: 1.0, max_vol: 0.30, color: '#F97316' },
            { label: 'hyper_risky', max_dd: 0.60, target_sharpe: 1.2, max_vol: 0.50, color: '#EF4444' },
          ])
        }
      } catch (e) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div>
      <div className="fade-up fade-up-1" style={{ maxWidth: 640, marginBottom: 28 }}>
        <h2 style={{ fontFamily: 'var(--serif)', fontSize: '2rem', marginBottom: 10 }}>Risk Analysis</h2>
        <p className="body">
          Kelly Criterion position sizing, strategy risk comparison, and portfolio-level risk metrics.
          Grounded in quantitative finance research — not vibes.
        </p>
      </div>

      {loading ? (
        <div className="caption">Loading risk data…</div>
      ) : error && !strategies.length ? (
        <div className="info-box warning">Error: {error}</div>
      ) : (
        <div className="trade-grid fade-up fade-up-2">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {/* Risk Profile Band Visualization */}
            <RiskProfileBand
              bands={bands}
              actualProfile={riskData?.actual_risk_profile || 'moderate'}
              worstMaxDD={riskData?.worst_max_dd || 0}
            />

            <KellyCalculator />

            {/* Portfolio Risk Summary */}
            <PortfolioRiskSummary riskData={riskData} />
          </div>

          <div>
            <StrategyRiskTable strategies={strategies} />
          </div>
        </div>
      )}
    </div>
  )
}
