import { useEffect, useMemo, useState } from 'react'
import { apiGet } from '../api'
import pricing from '../data/modelPricing.json'

// Cost-comparison panel for the Generate page. Surfaces the Bedrock model cost
// landscape (us-east-1 on-demand, $/1M tokens) and highlights the model the
// backend is actually using right now (from /health → llm_model). Collapsible so
// it stays out of the way until a user wants to compare costs. The data is a
// snapshot (ui/src/data/modelPricing.json); the active row is live.

const blended = (m) => m.input * 0.75 + m.output * 0.25
const fmt = (x) => (x == null ? '—' : `$${x.toFixed(x < 1 ? 3 : 2)}`)

export default function ModelCostPanel() {
  const [open, setOpen] = useState(false)
  const [activeModel, setActiveModel] = useState(null)

  useEffect(() => {
    let cancelled = false
    apiGet('/health')
      .then((d) => { if (!cancelled) setActiveModel(d?.llm_model || null) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  const rows = useMemo(() => [...pricing.models].sort((a, b) => blended(a) - blended(b)), [])
  const active = rows.find((m) => m.model_id && m.model_id === activeModel)

  return (
    <div className="card mb-4" style={{ padding: 0, overflow: 'hidden' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          display: 'flex', width: '100%', alignItems: 'center', justifyContent: 'space-between',
          gap: 12, padding: '12px 18px', background: 'transparent', border: 'none',
          cursor: 'pointer', textAlign: 'left', color: 'inherit',
        }}
      >
        <div>
          <div className="label" style={{ marginBottom: 2 }}>Model &amp; cost</div>
          <div className="caption" style={{ color: 'var(--text-3)' }}>
            {active ? (
              <>Running <strong style={{ color: 'var(--text-1)' }}>{active.provider} {active.name}</strong>
                {' · '}{fmt(active.input)} in / {fmt(active.output)} out per 1M tokens</>
            ) : activeModel ? (
              <>Running <strong style={{ color: 'var(--text-1)' }}>{activeModel}</strong></>
            ) : (
              <>Compare model costs across {rows.length} options on Bedrock</>
            )}
          </div>
        </div>
        <span
          className={`${open ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'} w-4 h-4`}
          style={{ color: 'var(--text-3)', flexShrink: 0 }}
        />
      </button>

      {open && (
        <div style={{ padding: '6px 18px 18px', borderTop: '1px solid var(--glass-border)' }}>
          <p className="caption mb-3" style={{ color: 'var(--text-3)' }}>
            {pricing.unit} · {pricing.region} · snapshot {pricing.generated}. Cheaper is usually
            less capable — pick for your budget. <strong style={{ color: '#3fb950' }}>✓</strong> = invokable
            now; <strong>premium</strong> models need a one-time account activation.
          </p>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ color: 'var(--text-3)', textAlign: 'left' }}>
                  <th style={{ padding: '6px 8px', fontWeight: 500 }}>Model</th>
                  <th style={{ padding: '6px 8px', fontWeight: 500, textAlign: 'right' }}>In $/1M</th>
                  <th style={{ padding: '6px 8px', fontWeight: 500, textAlign: 'right' }}>Out $/1M</th>
                  <th style={{ padding: '6px 8px', fontWeight: 500 }} />
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => {
                  const isActive = m.model_id && m.model_id === activeModel
                  return (
                    <tr
                      key={m.model_id || m.name}
                      style={{
                        borderTop: '1px solid var(--glass-border)',
                        background: isActive ? 'color-mix(in srgb, var(--accent) 12%, transparent)' : 'transparent',
                      }}
                    >
                      <td style={{ padding: '7px 8px', color: 'var(--text-1)' }}>
                        <span style={{ fontWeight: isActive ? 600 : 400 }}>{m.name}</span>
                        <span className="caption" style={{ color: 'var(--text-3)', marginLeft: 6 }}>{m.provider}</span>
                      </td>
                      <td style={{ padding: '7px 8px', textAlign: 'right', color: 'var(--text-1)', fontVariantNumeric: 'tabular-nums' }}>{fmt(m.input)}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right', color: 'var(--text-1)', fontVariantNumeric: 'tabular-nums' }}>{fmt(m.output)}</td>
                      <td style={{ padding: '7px 8px', whiteSpace: 'nowrap' }}>
                        {isActive && <span className="tag tag-accent" style={{ marginRight: 4 }}>active</span>}
                        {m.recommended && !isActive && (
                          <span style={{ color: 'var(--accent)', marginRight: 4 }} title="Recommended cheap pick">★</span>
                        )}
                        {m.works_now ? (
                          <span style={{ color: '#3fb950' }} title="Invokable now">✓</span>
                        ) : (
                          <span className="caption" style={{ color: 'var(--text-3)' }}>premium</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="caption mt-3" style={{ color: 'var(--text-3)' }}>{pricing.note}</p>
        </div>
      )}
    </div>
  )
}
