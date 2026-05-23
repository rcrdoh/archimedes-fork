import { useState, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'

const STORAGE_KEY = 'archimedes.onboarding.v1'

// Card content — kept here, not in a separate JSON, so contributors can
// edit the copy alongside the visuals. Order matches the user journey:
// understand → browse → generate → inspect → deploy → monitor.
const CARDS = [
  {
    id: 'what',
    title: 'What is Archimedes?',
    body: (
      <>
        <strong>Research-grounded strategy generation</strong> — not a robo-advisor.
        You describe what you want; Archimedes fuses your intent with live market
        data and ~10k peer-reviewed q-fin papers into novel strategies, then gates
        them through selection-bias rigor before any execution.
      </>
    ),
    cta: { label: 'Tell me more', target: null },
    illustration: 'archimedes',
  },
  {
    id: 'corpus',
    title: 'Browse the corpus',
    body: (
      <>
        Every strategy is anchored in <strong>peer-reviewed research</strong>. The
        Corpus page shows the papers in our library — methodology, year, authors,
        and which strategies cite them. Strategy generation pulls from this corpus,
        so the provenance is visible end-to-end.
      </>
    ),
    cta: { label: 'Open Corpus', target: 'corpus' },
    illustration: 'corpus',
  },
  {
    id: 'generate',
    title: 'Generate a strategy',
    body: (
      <>
        Describe what you want in plain English — the agent picks and weights
        paper-grounded strategies under hard risk constraints, surfaces multiple
        candidates, and computes a blended expected profile from real backtests.
        Each iteration streams live so you can see the deliberation.
      </>
    ),
    cta: { label: 'Open Generate', target: 'generate' },
    illustration: 'generate',
  },
  {
    id: 'reasoning',
    title: 'Inspect the reasoning',
    body: (
      <>
        Every autonomous decision — strategy registration, rebalance, regime shift
        — is <strong>hashed and anchored on Arc</strong> via the ReasoningTraceRegistry
        contract. You can verify any trace against its on-chain anchor and follow
        the trace back to the strategy and the source paper.
      </>
    ),
    cta: { label: 'Open Reasoning', target: 'reasoning' },
    illustration: 'reasoning',
  },
  {
    id: 'deploy',
    title: 'Deploy as a vault',
    body: (
      <>
        Generated strategies are <strong>time-bound</strong> — they're keyed to the
        market context at generation time, so they go stale. Deploy a strategy into
        an ERC-4626 vault before the window expires. Funds stay non-custodial;
        the agent has rebalance authority only.
      </>
    ),
    cta: { label: 'Open Portfolio', target: 'portfolio' },
    illustration: 'vault',
  },
  {
    id: 'watch',
    title: 'Watch the agent work',
    body: (
      <>
        After deployment, the Portfolio page shows live performance, the agent's
        decisions over time, and on-chain reasoning traces for every action. The
        Learnings page accumulates lessons across your strategies as they age.
      </>
    ),
    cta: { label: 'Open Portfolio', target: 'portfolio' },
    illustration: 'watch',
  },
]

function Illustration({ name }) {
  // Simple geometric SVGs — no external dependencies, theme-aware via
  // CSS variables. Each is ~80px tall, sized to fit the card hero.
  const accent = 'var(--accent)'
  const text = 'var(--text-2)'
  const muted = 'var(--text-4)'
  const bg = 'var(--bg-2)'

  switch (name) {
    case 'archimedes':
      return (
        <svg viewBox="0 0 160 80" width="100%" height="80" aria-hidden="true">
          <rect x="2" y="2" width="156" height="76" rx="6" fill={bg} />
          <text x="80" y="50" textAnchor="middle" fontFamily="serif" fontSize="44" fill={accent}>Λ</text>
          <text x="80" y="68" textAnchor="middle" fontFamily="serif" fontStyle="italic" fontSize="9" fill={muted}>archimedes</text>
        </svg>
      )
    case 'corpus':
      return (
        <svg viewBox="0 0 160 80" width="100%" height="80" aria-hidden="true">
          <rect x="2" y="2" width="156" height="76" rx="6" fill={bg} />
          {[0, 1, 2, 3].map(i => (
            <rect key={i} x={20 + i * 30} y={20 + (i % 2) * 6} width="22" height="40" rx="2" fill={i === 2 ? accent : muted} opacity={i === 2 ? 1 : 0.5} />
          ))}
          <text x="80" y="73" textAnchor="middle" fontFamily="monospace" fontSize="8" fill={muted}>10,000 papers</text>
        </svg>
      )
    case 'generate':
      return (
        <svg viewBox="0 0 160 80" width="100%" height="80" aria-hidden="true">
          <rect x="2" y="2" width="156" height="76" rx="6" fill={bg} />
          <circle cx="40" cy="40" r="6" fill={muted} opacity="0.5" />
          <circle cx="40" cy="22" r="6" fill={muted} opacity="0.5" />
          <circle cx="40" cy="58" r="6" fill={muted} opacity="0.5" />
          <path d="M 50 22 L 110 40 M 50 40 L 110 40 M 50 58 L 110 40" stroke={accent} strokeWidth="1.5" fill="none" />
          <circle cx="118" cy="40" r="8" fill={accent} />
          <text x="118" y="44" textAnchor="middle" fontFamily="monospace" fontSize="8" fill="#000">α</text>
          <text x="80" y="73" textAnchor="middle" fontFamily="monospace" fontSize="8" fill={muted}>fusion → strategy</text>
        </svg>
      )
    case 'reasoning':
      return (
        <svg viewBox="0 0 160 80" width="100%" height="80" aria-hidden="true">
          <rect x="2" y="2" width="156" height="76" rx="6" fill={bg} />
          <rect x="20" y="20" width="50" height="40" rx="3" fill="none" stroke={text} strokeWidth="1" />
          <text x="45" y="44" textAnchor="middle" fontFamily="monospace" fontSize="9" fill={text}>0xc4a3…</text>
          <path d="M 75 40 L 100 40" stroke={accent} strokeWidth="1.5" strokeDasharray="3 2" />
          <polygon points="100,36 108,40 100,44" fill={accent} />
          <rect x="113" y="20" width="42" height="40" rx="3" fill={accent} opacity="0.2" stroke={accent} strokeWidth="1" />
          <text x="134" y="38" textAnchor="middle" fontFamily="monospace" fontSize="7" fill={accent}>arc</text>
          <text x="134" y="50" textAnchor="middle" fontFamily="monospace" fontSize="7" fill={accent}>anchor</text>
          <text x="80" y="73" textAnchor="middle" fontFamily="monospace" fontSize="8" fill={muted}>hash → on-chain</text>
        </svg>
      )
    case 'vault':
      return (
        <svg viewBox="0 0 160 80" width="100%" height="80" aria-hidden="true">
          <rect x="2" y="2" width="156" height="76" rx="6" fill={bg} />
          <rect x="55" y="18" width="50" height="46" rx="3" fill="none" stroke={text} strokeWidth="1.5" />
          <circle cx="80" cy="41" r="10" fill={accent} opacity="0.3" stroke={accent} strokeWidth="1.5" />
          <text x="80" y="45" textAnchor="middle" fontFamily="monospace" fontSize="10" fill={accent}>$</text>
          <text x="80" y="73" textAnchor="middle" fontFamily="monospace" fontSize="8" fill={muted}>non-custodial · ERC-4626</text>
        </svg>
      )
    case 'watch':
      return (
        <svg viewBox="0 0 160 80" width="100%" height="80" aria-hidden="true">
          <rect x="2" y="2" width="156" height="76" rx="6" fill={bg} />
          <polyline points="20,55 40,42 55,48 75,30 95,35 115,22 140,28" fill="none" stroke={accent} strokeWidth="1.5" />
          {[20, 40, 55, 75, 95, 115, 140].map((x, i) => {
            const ys = [55, 42, 48, 30, 35, 22, 28]
            return <circle key={i} cx={x} cy={ys[i]} r="1.8" fill={accent} />
          })}
          <text x="80" y="73" textAnchor="middle" fontFamily="monospace" fontSize="8" fill={muted}>live performance + traces</text>
        </svg>
      )
    default:
      return null
  }
}

export function hasCompletedOnboarding() {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'completed'
  } catch {
    return false
  }
}

export default function OnboardingTour({ open, onClose, setPage }) {
  const [cardIndex, setCardIndex] = useState(0)

  // Reset to first card every time the tour is opened, so the "?" reopen
  // affordance always starts the user at card 1.
  useEffect(() => {
    if (open) setCardIndex(0)
  }, [open])

  const card = CARDS[cardIndex]
  const isLast = cardIndex === CARDS.length - 1

  const finish = useCallback(() => {
    try {
      localStorage.setItem(STORAGE_KEY, 'completed')
    } catch {
      // localStorage unavailable (e.g. SSR / private mode) — non-fatal;
      // we just won't remember the dismissal next visit.
    }
    onClose()
  }, [onClose])

  const handleContinue = useCallback(() => {
    if (isLast) {
      finish()
    } else {
      setCardIndex(i => i + 1)
    }
  }, [isLast, finish])

  const handleCta = useCallback(() => {
    if (card.cta.target) {
      setPage(card.cta.target)
      finish()
    } else {
      handleContinue()
    }
  }, [card, setPage, finish, handleContinue])

  // Keyboard support — Esc closes, ArrowRight advances, ArrowLeft goes back.
  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key === 'Escape') finish()
      if (e.key === 'ArrowRight') handleContinue()
      if (e.key === 'ArrowLeft' && cardIndex > 0) setCardIndex(i => i - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, cardIndex, finish, handleContinue])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center z-[1000]"
      style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)' }}
      onClick={finish}
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
    >
      <div
        className="card-elevated p-6 max-w-[460px] w-[90vw]"
        onClick={e => e.stopPropagation()}
      >
        <div className="caption mb-2 text-[var(--text-4)] uppercase tracking-wider">
          Welcome · {cardIndex + 1} of {CARDS.length}
        </div>

        <Illustration name={card.illustration} />

        <h3 id="onboarding-title" className="font-serif text-[1.4rem] mt-4 mb-2">
          {card.title}
        </h3>

        <p className="body leading-relaxed mb-5">
          {card.body}
        </p>

        {/* Pagination dots */}
        <div className="flex gap-1.5 justify-center mb-5" role="tablist" aria-label="Tour progress">
          {CARDS.map((c, i) => (
            <button
              key={c.id}
              type="button"
              role="tab"
              aria-selected={i === cardIndex}
              aria-label={`Card ${i + 1}: ${c.title}`}
              onClick={() => setCardIndex(i)}
              className="w-2 h-2 rounded-full border-none cursor-pointer"
              style={{
                background: i === cardIndex ? 'var(--accent)' : 'var(--text-4)',
                opacity: i === cardIndex ? 1 : 0.4,
                padding: 0,
              }}
            />
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 justify-between">
          <button type="button" className="btn btn-outline btn-sm" onClick={finish}>
            Skip
          </button>
          <div className="flex gap-2">
            {cardIndex > 0 && (
              <button type="button" className="btn btn-outline btn-sm" onClick={() => setCardIndex(i => i - 1)}>
                Back
              </button>
            )}
            {card.cta.target && (
              <button type="button" className="btn btn-outline btn-sm" onClick={handleCta}>
                {card.cta.label}
              </button>
            )}
            <button type="button" className="btn btn-primary btn-sm" onClick={handleContinue}>
              {isLast ? 'Done' : 'Continue'}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
