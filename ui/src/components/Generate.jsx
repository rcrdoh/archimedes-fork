import { useEffect, useRef, useState } from 'react'
import { StrategyArchitect } from './Strategies'
import GenerationStream from './GenerationStream'
import GenerationStatus from './GenerationStatus'
import FusionResult from './FusionResult'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// /generate spine page. Three paths:
//   1. Streaming agent (default) — SSE-driven, per docs/specs/generation-streaming-spec.md
//   2. Architect "fast preview" toggle — synchronous curated-library pick, kept
//      around because it's instant and useful when you just want a quick sanity check.
//   3. Fusion (novel) — multi-paper synthesis through strategy_fusion.py + the
//      fusion_evaluator rigor gate. The wedge: paper-grounded novel hypotheses
//      with externally verifiable DSR/PBO/OOS verdicts. Backend-complete since
//      #133; Phase 9 adds the UI per docs/specs/phase8-9-landing-and-fusion-spec.md.

const STORAGE_JOB_KEY = 'archimedes:currentJobId'
const STORAGE_FUSION_JOB_KEY = 'archimedes:currentFusionJobId'
const RISK_PROFILES = [
  { id: 'fixed_income', label: 'Fixed income' },
  { id: 'conservative', label: 'Conservative' },
  { id: 'moderate', label: 'Moderate' },
  { id: 'aggressive', label: 'Aggressive' },
  { id: 'hyper_risky', label: 'Hyper-risky' },
]
const ASSET_CLASSES = ['equities', 'bonds', 'commodities', 'crypto', 'fx']

export default function Generate({ onNavigate }) {
  const [mode, setMode] = useState('agent')  // 'agent' | 'architect' | 'fusion'
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

  // Fusion path — form fields + job state (no SSE — simple GET poll every 2s).
  const [fusionAssets, setFusionAssets] = useState(['equities'])
  const [fusionDirection, setFusionDirection] = useState('')
  const [fusionMaxPapers, setFusionMaxPapers] = useState(4)
  const [fusionJobId, setFusionJobId] = useState(() => localStorage.getItem(STORAGE_FUSION_JOB_KEY) || null)
  const [fusionStatus, setFusionStatus] = useState(null) // 'queued' | 'running' | 'done' | 'failed'
  const [fusionResult, setFusionResult] = useState(null)
  const [fusionError, setFusionError] = useState('')
  const [fusionStarting, setFusionStarting] = useState(false)
  const fusionPollRef = useRef(null)

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

  // ── Fusion path ────────────────────────────────────────────────
  const stopFusionPoll = () => {
    if (fusionPollRef.current) {
      clearInterval(fusionPollRef.current)
      fusionPollRef.current = null
    }
  }

  const pollFusion = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/api/strategies/generate/${encodeURIComponent(id)}`)
      if (!res.ok) {
        // 404 = job lost; clear and surface honestly
        if (res.status === 404) {
          setFusionError('Fusion job not found — backend may have restarted.')
          setFusionStatus('failed')
          stopFusionPoll()
          localStorage.removeItem(STORAGE_FUSION_JOB_KEY)
        }
        return
      }
      const data = await res.json()
      setFusionStatus(data.status)
      if (data.status === 'done') {
        setFusionResult(data.result || null)
        stopFusionPoll()
        localStorage.removeItem(STORAGE_FUSION_JOB_KEY)
      } else if (data.status === 'failed') {
        setFusionError(data.error || 'Fusion job failed.')
        stopFusionPoll()
        localStorage.removeItem(STORAGE_FUSION_JOB_KEY)
      }
    } catch (e) {
      // Network blip — keep polling silently
    }
  }

  // Auto-poll while a fusion job is in flight (resumes across reloads via localStorage).
  useEffect(() => {
    if (!fusionJobId) {
      stopFusionPoll()
      return
    }
    pollFusion(fusionJobId)
    fusionPollRef.current = setInterval(() => pollFusion(fusionJobId), 2000)
    return stopFusionPoll
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fusionJobId])

  const startFusionJob = async () => {
    setFusionError('')
    if (fusionAssets.length === 0) {
      setFusionError('Pick at least one asset class to fuse.')
      return
    }
    setFusionStarting(true)
    setFusionResult(null)
    setFusionStatus(null)
    try {
      const params = new URLSearchParams({
        asset_classes: fusionAssets.join(','),
        risk_appetite: riskAppetite,
        strategic_direction: fusionDirection,
        max_papers: String(fusionMaxPapers),
        mode: 'fusion',
      })
      const res = await fetch(`${API_BASE}/api/strategies/generate?${params}`, { method: 'POST' })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      if (!data.job_id) throw new Error('Backend did not return a job_id')
      localStorage.setItem(STORAGE_FUSION_JOB_KEY, data.job_id)
      setFusionJobId(data.job_id)
      setFusionStatus(data.status || 'queued')
    } catch (e) {
      setFusionError(e.message || 'Failed to start fusion job')
    } finally {
      setFusionStarting(false)
    }
  }

  const resetFusion = () => {
    stopFusionPoll()
    localStorage.removeItem(STORAGE_FUSION_JOB_KEY)
    setFusionJobId(null)
    setFusionStatus(null)
    setFusionResult(null)
    setFusionError('')
  }

  const toggleAsset = (a) => {
    setFusionAssets(prev => prev.includes(a) ? prev.filter(x => x !== a) : [...prev, a])
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
        <span
          className={`tag ${mode === 'fusion' ? 'tag-accent' : 'tag-muted'} cursor-pointer`}
          onClick={() => setMode('fusion')}
          title="Multi-paper synthesis through the fusion engine — novel hypotheses, rigor-gated"
        >
          🧪 Fusion (novel)
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

      {mode === 'fusion' && (
        <div className="fade-up fade-up-2">
          <div className="info-box mb-4">
            <strong>Fusion path</strong> — multi-paper synthesis through the fusion engine.
            The agent picks N papers from the corpus, fuses their methodologies into a
            novel hypothesis, runs a backtest, and gates the result through DSR / PBO /
            walk-forward OOS / look-ahead audit. Slowest path (~30–90s) but the only
            one that produces genuinely novel strategies.
          </div>

          {!fusionJobId && !fusionResult && (
            <div className="card p-5 mb-4">
              <div className="label mb-3">Asset classes (pick at least one)</div>
              <div className="flex gap-2 flex-wrap mb-4">
                {ASSET_CLASSES.map(a => (
                  <span
                    key={a}
                    className={`tag ${fusionAssets.includes(a) ? 'tag-accent' : 'tag-muted'} cursor-pointer capitalize`}
                    onClick={() => toggleAsset(a)}
                  >
                    {a}
                  </span>
                ))}
              </div>

              <div className="label mb-2">Strategic direction (optional)</div>
              <textarea
                value={fusionDirection}
                onChange={e => setFusionDirection(e.target.value)}
                placeholder="e.g. Combine momentum signals with vol-of-vol; we want crypto exposure on Fridays"
                rows={3}
                className="chat-input w-full mb-3 p-2.5 leading-relaxed"
                disabled={fusionStarting}
              />

              <div className="flex gap-3 items-center flex-wrap">
                <label className="caption flex items-center gap-1.5">
                  Risk
                  <select
                    value={riskAppetite}
                    onChange={e => setRiskAppetite(e.target.value)}
                    className="chat-input w-auto px-2 py-1"
                    disabled={fusionStarting}
                  >
                    {RISK_PROFILES.map(r => (
                      <option key={r.id} value={r.id}>{r.label}</option>
                    ))}
                  </select>
                </label>
                <label className="caption flex items-center gap-1.5">
                  Max papers
                  <select
                    value={fusionMaxPapers}
                    onChange={e => setFusionMaxPapers(Number(e.target.value))}
                    className="chat-input w-auto px-2 py-1"
                    disabled={fusionStarting}
                    title="Number of papers the fusion engine will combine"
                  >
                    {[2, 3, 4, 5, 6].map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                </label>
                <button
                  className="btn btn-primary ml-auto"
                  onClick={startFusionJob}
                  disabled={fusionStarting || fusionAssets.length === 0}
                >
                  {fusionStarting ? 'Starting…' : 'Fuse →'}
                </button>
              </div>

              {fusionError && (
                <div className="info-box warning mt-3">{fusionError}</div>
              )}
            </div>
          )}

          {fusionJobId && !fusionResult && (
            <div className="card p-5 mb-4">
              <div className="label mb-2">
                Status: <span className="capitalize">{fusionStatus || 'queued'}</span>
              </div>
              <div className="caption mb-3">
                Polling <code>/api/strategies/generate/{fusionJobId.slice(0, 8)}…</code> every 2s.
                Fusion typically takes 30–90 seconds — the engine fetches papers, synthesizes a
                methodology, runs a backtest, and computes selection-bias-corrected rigor.
              </div>
              <div className="flex gap-2">
                <div
                  className="h-1 flex-1 rounded"
                  style={{
                    background: 'var(--bg-2)',
                    overflow: 'hidden',
                    position: 'relative',
                  }}
                >
                  <div
                    style={{
                      position: 'absolute',
                      inset: 0,
                      width: '30%',
                      background: 'var(--accent)',
                      animation: 'fusion-progress 1.6s ease-in-out infinite',
                    }}
                  />
                </div>
                <button className="btn btn-outline btn-sm" onClick={resetFusion}>Cancel</button>
              </div>
              {fusionError && <div className="info-box warning mt-3">{fusionError}</div>}
            </div>
          )}

          {fusionResult && (
            <>
              <FusionResult result={fusionResult} onNavigate={onNavigate} />
              <div className="mt-4">
                <button className="btn btn-outline btn-sm" onClick={resetFusion}>
                  Fuse another →
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
