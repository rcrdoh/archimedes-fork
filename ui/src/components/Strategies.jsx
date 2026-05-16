import { useState, useEffect, useCallback } from 'react'

// Mirrors the apiGet pattern in Trade.jsx (relative paths in prod).
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

async function apiPost(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

const RISK_PROFILES = [
  { id: 'conservative', label: 'Conservative' },
  { id: 'moderate', label: 'Moderate' },
  { id: 'aggressive', label: 'Aggressive' },
  { id: 'hyper_risky', label: 'Hyper-risky' },
]

function pct(w) {
  return `${(w * 100).toFixed(1)}%`
}

function WeightBar({ weight, accent }) {
  return (
    <div style={{ background: 'rgba(255,255,255,0.06)', borderRadius: 4, height: 8, overflow: 'hidden' }}>
      <div style={{ width: pct(weight), height: '100%', background: accent || 'var(--accent, #6366F1)' }} />
    </div>
  )
}

export default function Strategies() {
  const [strategies, setStrategies] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const [intent, setIntent] = useState(
    'I have idle USDC and want thoughtful, research-backed growth without stomach-churning drawdowns.',
  )
  const [riskProfile, setRiskProfile] = useState('moderate')
  const [capital, setCapital] = useState(5000)

  const [result, setResult] = useState(null)
  const [constructing, setConstructing] = useState(false)
  const [constructError, setConstructError] = useState('')

  const loadStrategies = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const data = await apiGet('/api/strategies/')
      setStrategies(data.strategies || [])
    } catch (e) {
      setLoadError(e.message || 'Failed to load strategies')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadStrategies() }, [loadStrategies])

  const construct = useCallback(async () => {
    setConstructing(true)
    setConstructError('')
    setResult(null)
    try {
      const data = await apiPost('/api/strategies/construct', {
        intent,
        risk_profile: riskProfile,
        capital_usdc: Number(capital),
      })
      setResult(data)
    } catch (e) {
      setConstructError(e.message || 'Construction failed')
    } finally {
      setConstructing(false)
    }
  }, [intent, riskProfile, capital])

  const isFallback = result?.model_id === 'canned-fallback'

  return (
    <div className="panel">
      <h2>Strategy Architect</h2>
      <p className="hint" style={{ marginTop: 8 }}>
        Describe what you want. The agent selects paper-grounded strategies, weights them
        under hard risk constraints, and anchors a verifiable reasoning trace.
      </p>

      {/* ── Construct form ─────────────────────────────── */}
      <div className="card" style={{ marginTop: 20 }}>
        <div className="form-group">
          <label className="label">What do you want from this portfolio?</label>
          <textarea
            className="chat-input"
            style={{ width: '100%', minHeight: 80, resize: 'vertical' }}
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            placeholder="e.g. steady growth, low drawdowns, trend-following…"
          />
        </div>
        <div className="form-row" style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 12 }}>
          <div className="form-group">
            <label className="label">Risk profile</label>
            <select className="chat-input" value={riskProfile} onChange={(e) => setRiskProfile(e.target.value)}>
              {RISK_PROFILES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label className="label">Capital (USDC)</label>
            <input
              className="chat-input"
              type="number"
              min="1"
              value={capital}
              onChange={(e) => setCapital(e.target.value)}
            />
          </div>
          <div className="form-group" style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button className="btn btn-primary" onClick={construct} disabled={constructing || !intent.trim()}>
              {constructing ? 'Constructing…' : 'Construct portfolio'}
            </button>
          </div>
        </div>
      </div>

      {constructError && (
        <div className="info-box warning" style={{ marginTop: 16 }}>
          Construction failed: {constructError}
        </div>
      )}

      {/* ── Result ─────────────────────────────────────── */}
      {result && (
        <div className="card" style={{ marginTop: 20 }}>
          {isFallback && (
            <div className="info-box warning" style={{ marginBottom: 16 }}>
              ⚠️ Offline fallback (no <code>ANTHROPIC_API_KEY</code>) — equal-weighted,
              not model reasoning. The guardrail + trace are still real.
            </div>
          )}

          <h3>Proposed portfolio</h3>
          <p className="hint" style={{ marginTop: 4 }}>
            {result.risk_profile} · {Number(result.capital_usdc).toLocaleString()} USDC ·
            model: <span className="mono">{result.model_id}</span>
          </p>

          {result.overall_reasoning && (
            <p style={{ marginTop: 12, lineHeight: 1.5 }}>{result.overall_reasoning}</p>
          )}

          <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
            {result.selected.map((s) => (
              <div key={s.strategy_id}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <strong>{s.paper_title || s.strategy_id}</strong>
                  <span className="mono">{pct(s.weight)}</span>
                </div>
                <WeightBar weight={s.weight} />
                {s.rationale && <p className="hint" style={{ marginTop: 6 }}>{s.rationale}</p>}
                {s.paper_citation && (
                  <p className="caption" style={{ marginTop: 2 }}>📄 {s.paper_citation}</p>
                )}
              </div>
            ))}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <strong>USYC (cash-yield sleeve)</strong>
                <span className="mono">{pct(result.usyc_weight)}</span>
              </div>
              <WeightBar weight={result.usyc_weight} accent="#10B981" />
            </div>
          </div>

          {result.risk_notes && (
            <p className="hint" style={{ marginTop: 16 }}><strong>Risk notes:</strong> {result.risk_notes}</p>
          )}

          {result.guardrail_notes?.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div className="label">Guardrail adjustments</div>
              <ul className="hint" style={{ marginTop: 6, paddingLeft: 18 }}>
                {result.guardrail_notes.map((n, i) => <li key={i}>{n}</li>)}
              </ul>
            </div>
          )}

          {result.trace && (
            <div className="trace-card" style={{ marginTop: 18 }}>
              <div className="trace-id">
                {result.trace.decision_type} · {result.trace.trigger}
                <span
                  className={`badge ${result.trace.is_anchored ? 'tier-1' : ''}`}
                  style={{ marginLeft: 8 }}
                >
                  {result.trace.is_anchored ? 'anchored on-chain' : 'pending anchor'}
                </span>
              </div>
              <div className="mono" style={{ marginTop: 6, wordBreak: 'break-all', fontSize: 12 }}>
                {result.trace.trace_hash}
              </div>
              <p className="caption" style={{ marginTop: 6 }}>
                SHA-256 of the decision — recompute it from this response to verify.
                Anchored on Arc via ReasoningTraceRegistry.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── Library ────────────────────────────────────── */}
      <h3 style={{ marginTop: 28 }}>Strategy library</h3>
      {loading && <div className="loading" style={{ marginTop: 12 }}>Loading strategies…</div>}
      {loadError && (
        <div className="info-box warning" style={{ marginTop: 12 }}>
          Couldn’t load the library: {loadError}
          <div className="hint" style={{ marginTop: 6 }}>
            If empty in Docker, the backend image needs <code>analytics-engine/strategies/</code>
            mounted (infra follow-up).
          </div>
        </div>
      )}
      {!loading && !loadError && strategies.length === 0 && (
        <p className="hint" style={{ marginTop: 12 }}>No strategies loaded.</p>
      )}
      <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {strategies.map((s) => (
          <div key={s.id} className="vault-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <strong>{s.paper_title}</strong>
              <span className="badge">{s.status}</span>
            </div>
            {s.paper_authors?.length > 0 && (
              <p className="caption" style={{ marginTop: 2 }}>{s.paper_authors.join(', ')}</p>
            )}
            <p className="hint" style={{ marginTop: 6 }}>{s.methodology_summary}</p>
            <p className="caption" style={{ marginTop: 6 }}>
              {s.asset_universe?.join(' · ')} · {s.position_sizing} · {s.rebalance_frequency}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
