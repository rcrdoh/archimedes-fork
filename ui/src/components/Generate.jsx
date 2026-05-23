import { useEffect, useState } from 'react'
import { StrategyArchitect } from './Strategies'
import GenerationStream from './GenerationStream'
import GenerationStatus from './GenerationStatus'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// /generate spine page. Two paths today:
//   1. Streaming agent (default) — SSE-driven, per docs/specs/generation-streaming-spec.md
//   2. Architect "fast preview" toggle — synchronous curated-library pick, kept
//      around because it's instant and useful when you just want a quick sanity check.

const STORAGE_JOB_KEY = 'archimedes:currentJobId'
const RISK_PROFILES = [
  { id: 'fixed_income', label: 'Fixed income' },
  { id: 'conservative', label: 'Conservative' },
  { id: 'moderate', label: 'Moderate' },
  { id: 'aggressive', label: 'Aggressive' },
  { id: 'hyper_risky', label: 'Hyper-risky' },
]

export default function Generate({ onNavigate }) {
  const [mode, setMode] = useState('agent')  // 'agent' | 'architect'
  const [intent, setIntent] = useState('')
  const [riskAppetite, setRiskAppetite] = useState('moderate')
  const [nCandidates, setNCandidates] = useState(1)
  const [jobId, setJobId] = useState(() => localStorage.getItem(STORAGE_JOB_KEY) || null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState('')

  // Architect path needs the library pre-fetched.
  const [strategies, setStrategies] = useState([])
  const [libLoading, setLibLoading] = useState(true)
  const [libError, setLibError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE}/api/strategies/`)
      .then(r => r.ok ? r.json() : r.text().then(t => { throw new Error(t) }))
      .then(data => { if (!cancelled) setStrategies(data.strategies || []) })
      .catch(e => { if (!cancelled) setLibError(e.message || 'Failed to load library') })
      .finally(() => { if (!cancelled) setLibLoading(false) })
    return () => { cancelled = true }
  }, [])

  const startJob = async () => {
    setStartError('')
    if (!intent.trim()) {
      setStartError('Describe what you want in a sentence or two.')
      return
    }
    setStarting(true)
    try {
      const res = await fetch(`${API_BASE}/api/generate/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          brief: { intent, risk_appetite: riskAppetite },
          n_candidates: nCandidates,
        }),
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      localStorage.setItem(STORAGE_JOB_KEY, data.job_id)
      setJobId(data.job_id)
    } catch (e) {
      setStartError(e.message || 'Failed to start generation')
    } finally {
      setStarting(false)
    }
  }

  const onJobDone = (result) => {
    localStorage.removeItem(STORAGE_JOB_KEY)
    if (result?.strategy_id && onNavigate) {
      // Soft hand-off — the persisted strategy is the canonical target.
      onNavigate('library', { highlight: result.strategy_id })
    }
  }

  const resetJob = () => {
    localStorage.removeItem(STORAGE_JOB_KEY)
    setJobId(null)
  }

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

      {/* Mode toggle */}
      <div className="strat-filter-bar fade-up fade-up-2 mb-4">
        <span
          className={`tag ${mode === 'agent' ? 'tag-accent' : 'tag-muted'} cursor-pointer`}
          onClick={() => setMode('agent')}
          title="Live streaming agent — each iteration appears as it runs"
        >
          🔴 Streaming agent
        </span>
        <span
          className={`tag ${mode === 'architect' ? 'tag-accent' : 'tag-muted'} cursor-pointer`}
          onClick={() => setMode('architect')}
          title="Skip the fusion engine and let the architect pick from the curated library — faster but less novel"
        >
          ⚡ Architect (fast preview)
        </span>
      </div>

      {mode === 'agent' && (
        <div className="fade-up fade-up-2">
          {!jobId && (
            <div className="card p-5 mb-4">
              <div className="label mb-2">What would you like?</div>
              <textarea
                value={intent}
                onChange={e => setIntent(e.target.value)}
                placeholder="e.g. A 13-week treasury alternative with low volatility and crypto upside on Fridays"
                rows={3}
                className="chat-input w-full mb-3 p-2.5 leading-relaxed"
                disabled={starting}
              />
              <div className="flex gap-3 items-center flex-wrap">
                <label className="caption flex items-center gap-1.5">
                  Risk
                  <select
                    value={riskAppetite}
                    onChange={e => setRiskAppetite(e.target.value)}
                    className="chat-input w-auto px-2 py-1"
                    disabled={starting}
                  >
                    {RISK_PROFILES.map(r => (
                      <option key={r.id} value={r.id}>{r.label}</option>
                    ))}
                  </select>
                </label>
                <label className="caption flex items-center gap-1.5">
                  Candidates
                  <select
                    value={nCandidates}
                    onChange={e => setNCandidates(Number(e.target.value))}
                    className="chat-input w-auto px-2 py-1"
                    disabled={starting}
                    title="Agent runs N variants internally; best is surfaced, rejects browsable"
                  >
                    {[1, 2, 3].map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                </label>
                <button
                  className="btn btn-primary ml-auto"
                  onClick={startJob}
                  disabled={starting || !intent.trim()}
                >
                  {starting ? 'Starting…' : 'Generate →'}
                </button>
              </div>
              {startError && (
                <div className="info-box warning mt-3">{startError}</div>
              )}
            </div>
          )}

          {jobId && (
            <GenerationStream
              jobId={jobId}
              onDone={onJobDone}
              onReset={resetJob}
            />
          )}

          <div className="mt-6">
            <GenerationStatus
              activeJobId={jobId}
              onSelect={(id) => { localStorage.setItem(STORAGE_JOB_KEY, id); setJobId(id) }}
            />
          </div>
        </div>
      )}

      {mode === 'architect' && (
        <div className="fade-up fade-up-2">
          <div className="info-box mb-4">
            <strong>Architect path</strong> — Claude selects + weights from the curated
            library synchronously. No streaming, no novel synthesis; useful when you just
            want a fast read on what the library would recommend for your brief.
          </div>
          {libLoading && <div className="caption">Loading strategy library…</div>}
          {libError && (
            <div className="info-box warning mb-4">
              Couldn't load library: {libError}. The architect needs the library to pick from.
            </div>
          )}
          {!libLoading && !libError && <StrategyArchitect strategies={strategies} />}
        </div>
      )}
    </div>
  )
}
