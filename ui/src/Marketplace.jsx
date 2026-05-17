import { useState, useEffect } from 'react'
import { ASSETS, USDC } from './config'

const API_BASE = 'http://localhost:8000'

// Mock ecosystem stats (matches mockup)
const ECOSYSTEM_STATS = {
  totalAum: '$2.4M',
  aumChange: '+12.3%',
  activeVaults: 18,
  verifiedVaults: 12,
  communityVaults: 6,
  totalTraces: 247,
  avgSharpe: 1.82,
  sharpeDelta: '+0.14',
}

// Mock vault data (matches mockup table)
const MOCK_VAULTS = [
  {
    id: '0x1a2b3c4d5e6f7890abcdef1234567890abcdef12',
    name: 'Momentum Alpha',
    symbol: 'vMOMENTUM',
    tier: 1,
    aum: 524200,
    return30d: 12.3,
    sharpe: 1.84,
    maxDrawdown: -8.2,
    allocations: [
      { symbol: 'sTSLA', color: '#3B82F6', weight: 28 },
      { symbol: 'sSPY', color: '#6366F1', weight: 25 },
      { symbol: 'sGLD', color: '#D4A853', weight: 12 },
      { symbol: 'sBTC', color: '#F97316', weight: 5 },
      { symbol: 'USYC', color: '#22C55E', weight: 30 },
    ],
    managementFee: 1.5,
    performanceFee: 20,
  },
  {
    id: '0x2b3c4d5e6f7890abcdef1234567890abcdef1234',
    name: 'Yield Optimizer',
    symbol: 'vYIELD',
    tier: 1,
    aum: 312800,
    return30d: 8.1,
    sharpe: 2.12,
    maxDrawdown: -4.1,
    allocations: [
      { symbol: 'USYC', color: '#22C55E', weight: 55 },
      { symbol: 'sSPY', color: '#6366F1', weight: 20 },
      { symbol: 'sGLD', color: '#D4A853', weight: 15 },
      { symbol: 'sTSLA', color: '#3B82F6', weight: 10 },
    ],
    managementFee: 1.0,
    performanceFee: 15,
  },
  {
    id: '0x3c4d5e6f7890abcdef1234567890abcdef12345',
    name: 'DeFi Degen',
    symbol: 'vDEGEN',
    tier: 2,
    aum: 87400,
    return30d: 18.7,
    sharpe: 0.94,
    maxDrawdown: -22.1,
    allocations: [
      { symbol: 'sBTC', color: '#F97316', weight: 60 },
      { symbol: 'sTSLA', color: '#3B82F6', weight: 25 },
      { symbol: 'USYC', color: '#22C55E', weight: 15 },
    ],
    managementFee: 2.0,
    performanceFee: 25,
  },
  {
    id: '0x4d5e6f7890abcdef1234567890abcdef123456',
    name: 'Safe Haven',
    symbol: 'vSAFE',
    tier: 2,
    aum: 145600,
    return30d: 5.2,
    sharpe: 1.54,
    maxDrawdown: -3.8,
    allocations: [
      { symbol: 'USYC', color: '#22C55E', weight: 60 },
      { symbol: 'sGLD', color: '#D4A853', weight: 25 },
      { symbol: 'sSPY', color: '#6366F1', weight: 15 },
    ],
    managementFee: 0.5,
    performanceFee: 10,
  },
  {
    id: '0x5e6f7890abcdef1234567890abcdef1234567',
    name: 'Multi-Factor Quant',
    symbol: 'vMFQ',
    tier: 1,
    aum: 298100,
    return30d: 9.8,
    sharpe: 1.67,
    maxDrawdown: -11.4,
    allocations: [
      { symbol: 'sTSLA', color: '#3B82F6', weight: 35 },
      { symbol: 'sSPY', color: '#6366F1', weight: 25 },
      { symbol: 'sGLD', color: '#D4A853', weight: 20 },
      { symbol: 'USYC', color: '#22C55E', weight: 20 },
    ],
    managementFee: 1.5,
    performanceFee: 20,
  },
]

// Mock strategy data (matches mockup)
const MOCK_STRATEGIES = [
  {
    id: 'cross-sectional-momentum',
    name: 'Cross-Sectional Momentum',
    description: 'Buy top-decile 12-month performers, sell bottom decile. Monthly rebalance.',
    author: 'Jegadeesh & Titman (1993)',
    venue: 'Journal of Finance',
    year: 1993,
    arxivId: '9301001',
    citations: 12847,
    risk: 'Medium',
    status: 'live',
    vaultCount: 3,
    sharpe: 1.42,
    cagr: 18.4,
    maxDrawdown: -14.2,
    winRate: 58.3,
    tags: ['q-fin.PM', 'Momentum', 'Monthly'],
  },
  {
    id: 'mean-reversion-pairs',
    name: 'Mean Reversion Pairs',
    description: 'Exploit short-term deviations from long-term equilibrium relationships.',
    author: 'Gatev, Goetzmann & Rouwenhorst (2006)',
    venue: 'Review of Financial Studies',
    year: 2006,
    arxivId: '0607124',
    citations: 4218,
    risk: 'Low',
    status: 'live',
    vaultCount: 2,
    sharpe: 1.28,
    cagr: 12.1,
    maxDrawdown: -11.8,
    winRate: 62.1,
    tags: ['q-fin.TR', 'Pairs Trading', 'Stat-Arb'],
  },
  {
    id: 'risk-parity',
    name: 'Risk Parity',
    description: 'Equal-risk contribution allocation across asset classes.',
    author: 'Asness, Frazzini & Pedersen (2012)',
    venue: 'Financial Analysts Journal',
    year: 2012,
    arxivId: '1205346',
    citations: 2891,
    risk: 'Low',
    status: 'live',
    vaultCount: 4,
    sharpe: 1.56,
    cagr: 9.8,
    maxDrawdown: -7.4,
    winRate: 55.8,
    tags: ['q-fin.PM', 'Portfolio', 'Low-Vol'],
  },
  {
    id: 'trend-following-cta',
    name: 'Trend Following CTA',
    description: 'Time-series momentum across futures and FX. Long-only on rising assets.',
    author: 'Moskowitz, Ooi & Pedersen (2012)',
    venue: 'Journal of Financial Economics',
    year: 2012,
    arxivId: '1209177',
    citations: 3421,
    risk: 'High',
    status: 'live',
    vaultCount: 2,
    sharpe: 1.14,
    cagr: 15.2,
    maxDrawdown: -18.3,
    winRate: 51.2,
    tags: ['q-fin.TR', 'Trend', 'CTA'],
  },
  {
    id: 'kelly-criterion',
    name: 'Kelly Criterion Sizing',
    description: 'Optimal position sizing based on edge and variance estimates.',
    author: 'Thorp (2006)',
    venue: 'Kelly Capital Growth Investment Criterion',
    year: 2006,
    arxivId: '0611823',
    citations: 1523,
    risk: 'High',
    status: 'live',
    vaultCount: 3,
    sharpe: 1.88,
    cagr: 22.1,
    maxDrawdown: -19.7,
    winRate: 48.9,
    tags: ['q-fin.RM', 'Position-Sizing', 'Optimal'],
  },
]

// Mock agent activity
const MOCK_ACTIVITY = [
  {
    type: 'rebalance',
    vault: 'Momentum Alpha',
    time: 3,
    message: 'Reduced sTSLA 33% → 28%, shifted to USYC. Drift threshold exceeded. Cost-benefit: +$294 net.',
    traceId: 247,
  },
  {
    type: 'regime',
    vault: 'Global Detection',
    time: 60,
    message: 'Regime confirmed Risk-On. VIX 14.2, positive equity momentum, tight credit spreads. No action.',
    traceId: null,
  },
  {
    type: 'rotation',
    vault: 'Multi-Factor Quant',
    time: 240,
    message: 'Rotated out "Mean Reversion Small Cap" (Sharpe 0.38) → "Cross-Sectional Momentum" (Sharpe 1.42, correlation 0.12).',
    traceId: 246,
  },
]

function formatNumber(num) {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M'
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K'
  return num.toString()
}

function formatAddress(addr) {
  return addr.slice(0, 6) + '…' + addr.slice(-4)
}

export default function Marketplace() {
  const [stats, setStats] = useState(ECOSYSTEM_STATS)
  const [vaults, setVaults] = useState(MOCK_VAULTS)
  const [strategies, setStrategies] = useState(MOCK_STRATEGIES)
  const [activity, setActivity] = useState(MOCK_ACTIVITY)
  const [regime, setRegime] = useState('Risk-On')
  const [vaultFilter, setVaultFilter] = useState('all')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [sortBy, setSortBy] = useState('aum')
  const [searchQuery, setSearchQuery] = useState('')

  // Fetch regime on mount
  useEffect(() => {
    fetch(`${API_BASE}/api/regime/current`)
      .then(r => r.json())
      .then(data => {
        if (data.regime) {
          setRegime(data.regime === 'risk_on' ? 'Risk-On' : data.regime === 'risk_off' ? 'Risk-Off' : 'Transition')
        }
      })
      .catch(() => setRegime('Risk-On'))
  }, [])

  const filteredVaults = vaults
    .filter(v => {
      if (vaultFilter === 'verified') return v.tier === 1
      if (vaultFilter === 'community') return v.tier === 2
      return true
    })
    .sort((a, b) => {
      if (sortBy === 'aum') return b.aum - a.aum
      if (sortBy === 'return') return b.return30d - a.return30d
      if (sortBy === 'sharpe') return b.sharpe - a.sharpe
      if (sortBy === 'risk') return a.maxDrawdown - b.maxDrawdown
      return 0
    })

  const filteredStrategies = strategies
    .filter(s => {
      if (categoryFilter !== 'all' && !s.tags.includes(categoryFilter)) return false
      if (searchQuery) {
        const q = searchQuery.toLowerCase()
        return s.name.toLowerCase().includes(q) || s.author.toLowerCase().includes(q)
      }
      return true
    })

  return (
    <div className="fade-up fade-up-1">
      {/* Top bar with regime */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <span className="label">Marketplace</span>
        </div>
        <div className="flex items-center gap-5">
          <span className="caption">
            Regime <strong className={regime === 'Risk-On' ? 'positive' : regime === 'Risk-Off' ? 'negative' : 'accent'}>{regime}</strong>
          </span>
        </div>
      </div>

      {/* Ecosystem Stats */}
      <div className="grid g-4 mb-7" style={{ gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <div>
          <div className="label mb-2">Ecosystem AUM</div>
          <div className="stat" style={{ fontSize: '1.8rem' }}>{stats.totalAum}</div>
          <div className="caption positive" style={{ marginTop: 6 }}>{stats.aumChange} this week</div>
        </div>
        <div>
          <div className="label mb-2">Active Vaults</div>
          <div className="stat" style={{ fontSize: '1.8rem' }}>{stats.activeVaults}</div>
          <div className="caption" style={{ marginTop: 6 }}>{stats.verifiedVaults} verified · {stats.communityVaults} community</div>
        </div>
        <div>
          <div className="label mb-2">On-Chain Traces</div>
          <div className="stat" style={{ fontSize: '1.8rem' }}>{stats.totalTraces}</div>
          <div className="caption accent" style={{ marginTop: 6 }}>All verifiable</div>
        </div>
        <div>
          <div className="label mb-2">Avg Sharpe (T1)</div>
          <div className="stat" style={{ fontSize: '1.8rem' }}>{stats.avgSharpe}</div>
          <div className="caption positive" style={{ marginTop: 6 }}>{stats.sharpeDelta} vs benchmark</div>
        </div>
      </div>

      <div className="divider" style={{ marginBottom: 24 }} />

      {/* Synthetic Prices (from ASSETS) */}
      <div className="mb-7">
        <div className="flex items-center justify-between mb-5">
          <div className="label">Synthetic Assets</div>
          <span className="caption">Live oracle prices</span>
        </div>
        <div className="grid g-5" style={{ gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
          {ASSETS.slice(0, 5).map(asset => (
            <div key={asset.id} className="card-flat" style={{ padding: 16 }}>
              <div className="flex items-center gap-3 mb-3">
                <div className="token-dot" style={{
                  width: 32, height: 32, fontSize: '0.75rem',
                  background: asset.id === 'TSLA' ? '#3B82F6' :
                            asset.id === 'SPY' ? '#6366F1' :
                            asset.id === 'GOLD' ? '#D4A853' :
                            asset.id === 'BTC' ? '#F97316' : '#22C55E'
                }}>
                  {asset.emoji}
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{asset.sym}</div>
                  <div className="caption">{asset.name}</div>
                </div>
              </div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, letterSpacing: '-0.02em' }}>
                ${asset.id === 'BTC' ? '67,842' : asset.id === 'GOLD' ? '2,341' : asset.id === 'SPY' ? '532.18' : asset.id === 'TSLA' ? '287.42' : '1.0012'}
              </div>
              <div className={`caption ${Math.random() > 0.3 ? 'positive' : 'negative'}`}>
                {Math.random() > 0.3 ? '+' : '-'}{(Math.random() * 5).toFixed(2)}%
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Vault Leaderboard */}
      <div className="mb-7">
        <div className="flex items-center justify-between mb-5">
          <div className="label">Vault Leaderboard</div>
          <div className="flex gap-2">
            <span
              className={`tag ${vaultFilter === 'all' ? 'tag-accent' : 'tag-muted'}`}
              style={{ cursor: 'pointer' }}
              onClick={() => setVaultFilter('all')}
            >All</span>
            <span
              className={`tag ${vaultFilter === 'verified' ? 'tag-accent' : 'tag-muted'}`}
              style={{ cursor: 'pointer' }}
              onClick={() => setVaultFilter('verified')}
            >Verified</span>
            <span
              className={`tag ${vaultFilter === 'community' ? 'tag-accent' : 'tag-muted'}`}
              style={{ cursor: 'pointer' }}
              onClick={() => setVaultFilter('community')}
            >Community</span>
          </div>
        </div>

        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th style={{ width: 32 }}>#</th>
                <th>Vault</th>
                <th>Tier</th>
                <th className="text-right">AUM</th>
                <th className="text-right">30d Return</th>
                <th className="text-right">Sharpe</th>
                <th className="text-right">Max DD</th>
                <th>Allocation</th>
                <th className="text-right">Fees</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filteredVaults.map((vault, idx) => (
                <tr key={vault.id} className="pointer" style={{ cursor: 'pointer' }}>
                  <td style={{ fontWeight: 700, color: idx === 0 ? 'var(--accent)' : 'var(--text-3)' }}>
                    {idx + 1}
                  </td>
                  <td>
                    <div><span style={{ fontWeight: 600 }}>{vault.name}</span></div>
                    <div className="mono caption">{vault.symbol}</div>
                  </td>
                  <td>
                    <span className={`tier ${vault.tier === 1 ? 'tier-verified' : 'tier-community'}`}>
                      {vault.tier === 1 ? 'Verified' : 'Community'}
                    </span>
                  </td>
                  <td className="text-right" style={{ fontWeight: 600 }}>
                    ${formatNumber(vault.aum)}
                  </td>
                  <td className="text-right positive" style={{ fontWeight: 600 }}>
                    +{vault.return30d}%
                  </td>
                  <td className="text-right" style={{ fontWeight: 600 }}>
                    {vault.sharpe}
                  </td>
                  <td className="text-right negative">
                    {vault.maxDrawdown}%
                  </td>
                  <td>
                    <div className="alloc-bar" style={{ width: 80 }}>
                      {vault.allocations.map((alloc, i) => (
                        <div
                          key={i}
                          className="seg"
                          style={{
                            width: alloc.weight + '%',
                            background: alloc.color,
                          }}
                        />
                      ))}
                    </div>
                  </td>
                  <td className="text-right caption">
                    {vault.managementFee}% + {vault.performanceFee}%
                  </td>
                  <td>
                    <button className="btn btn-primary btn-sm">Invest</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Strategy Library */}
      <div className="mb-7">
        <div className="flex items-center justify-between mb-5">
          <div className="label">Strategy Library</div>
          <div className="flex gap-2 items-center">
            <input
              type="text"
              placeholder="Search strategies..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                padding: '6px 12px',
                background: 'var(--surface-2)',
                border: '1px solid var(--glass-border)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-1)',
                fontSize: '0.8rem',
                outline: 'none',
                minWidth: 180,
              }}
            />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              style={{
                padding: '6px 12px',
                background: 'var(--surface-2)',
                border: '1px solid var(--glass-border)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-1)',
                fontSize: '0.8rem',
                outline: 'none',
              }}
            >
              <option value="aum">Sort by TVL</option>
              <option value="return">Sort by APY</option>
              <option value="sharpe">Sort by Sharpe</option>
              <option value="risk">Sort by Risk</option>
            </select>
          </div>
        </div>

        <div className="flex gap-2 mb-6">
          <span
            className={`tag ${categoryFilter === 'all' ? 'tag-accent' : 'tag-muted'}`}
            style={{ cursor: 'pointer' }}
            onClick={() => setCategoryFilter('all')}
          >All ({strategies.length})</span>
          <span
            className={`tag ${categoryFilter === 'q-fin.PM' ? 'tag-accent' : 'tag-muted'}`}
            style={{ cursor: 'pointer' }}
            onClick={() => setCategoryFilter('q-fin.PM')}
          >Portfolio Mgmt</span>
          <span
            className={`tag ${categoryFilter === 'q-fin.TR' ? 'tag-accent' : 'tag-muted'}`}
            style={{ cursor: 'pointer' }}
            onClick={() => setCategoryFilter('q-fin.TR')}
          >Trading</span>
          <span
            className={`tag ${categoryFilter === 'q-fin.RM' ? 'tag-accent' : 'tag-muted'}`}
            style={{ cursor: 'pointer' }}
            onClick={() => setCategoryFilter('q-fin.RM')}
          >Risk Mgmt</span>
        </div>

        <div className="strat-grid-3">
          {filteredStrategies.map(strategy => (
            <div key={strategy.id} className="card">
              <div className="flex items-center gap-3 mb-4">
                <h3 style={{ fontSize: '1rem' }}>{strategy.name}</h3>
                <span className="tag tag-positive">Live</span>
                {strategy.vaultCount > 0 && (
                  <span className="tag tag-accent">In {strategy.vaultCount} vault{strategy.vaultCount > 1 ? 's' : ''}</span>
                )}
              </div>
              <div className="caption mb-4" style={{ lineHeight: 1.5 }}>
                {strategy.author} · {strategy.venue} · {strategy.year}
              </div>
              <div className="strat-metric-grid mb-4" style={{ marginBottom: 12 }}>
                <div>
                  <div className="caption">Sharpe</div>
                  <div style={{ fontWeight: 700 }}>{strategy.sharpe}</div>
                </div>
                <div>
                  <div className="caption">CAGR</div>
                  <div className="positive" style={{ fontWeight: 700 }}>{strategy.cagr}%</div>
                </div>
                <div>
                  <div className="caption">Max DD</div>
                  <div className="negative" style={{ fontWeight: 700 }}>{strategy.maxDrawdown}%</div>
                </div>
              </div>
              <div className="flex gap-2 flex-wrap">
                {strategy.tags.map(tag => (
                  <span key={tag} className="tag tag-muted">{tag}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Agent Activity */}
      <div>
        <div className="flex items-center justify-between mb-5">
          <div className="label">Agent Activity</div>
        </div>
        <div className="timeline">
          {activity.map((item, idx) => (
            <div key={idx} className={`tl-item ${idx === 0 ? 'active' : ''}`}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                  <span className={`tag ${item.type === 'rebalance' ? 'tag-positive' : item.type === 'regime' ? 'tag-muted' : 'tag-accent'}`}>
                    {item.type === 'rebalance' ? 'Rebalance' : item.type === 'regime' ? 'Regime' : 'Rotation'}
                  </span>
                  <span style={{ fontWeight: 600, fontSize: '0.88rem' }}>{item.vault}</span>
                </div>
                <span className="caption">
                  {item.time < 60 ? `${item.time} min ago` : `${Math.floor(item.time / 60)} hr ago`}
                </span>
              </div>
              <div className="body">
                {item.message}
                {item.traceId && (
                  <span className="accent"> Trace #{item.traceId} →</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
