import { useEffect, useState } from 'react'
import { StrategyArchitect } from './Strategies'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// The /generate page: the spine's primary action (per docs/user-stories.md).
// Currently shows the curated-library architect path — the only path with real
// backtest+rigor numbers today. Fusion-mode (novelty synthesis from the 10k
// q-fin corpus) is the stretch goal — see STRETCH todo + the t2o2 spec
// (fusion-to-backtestable-strategy) for the work that unblocks it.
//
// We pre-fetch the full strategy library here so StrategyArchitect can compute
// blended Sharpe/CAGR/MaxDD from per-strategy backtests on the result.

export default function Generate() {
  const [strategies, setStrategies] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE}/api/strategies/`)
      .then(r => r.ok ? r.json() : r.text().then(t => { throw new Error(t) }))
      .then(data => { if (!cancelled) setStrategies(data.strategies || []) })
      .catch(e => { if (!cancelled) setError(e.message || 'Failed to load library') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  return (
    <div>
      <div className="fade-up fade-up-1 max-w-[720px] mb-7">
        <h2 className="serif text-[2rem] mb-2.5">Generate a Strategy</h2>
        <p className="body mb-2">
          Describe what you want in plain English. The agent picks and weights
          paper-grounded strategies under hard risk constraints, computes a blended
          expected profile from real backtests, and anchors a verifiable reasoning trace.
        </p>
        <p className="body text-[var(--text-3)]">
          No wallet required to generate. Wallet is only needed to deposit into a vault.
        </p>
      </div>

      {loading && <div className="caption">Loading strategy library…</div>}
      {error && (
        <div className="info-box warning mb-4">
          Couldn't load library: {error}. The architect needs the library to pick from.
        </div>
      )}
      {!loading && !error && <StrategyArchitect strategies={strategies} />}
    </div>
  )
}
