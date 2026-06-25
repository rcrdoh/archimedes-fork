// Single source of truth for how market regimes are presented to users.
//
// The WIRE VALUES — 'risk_on' | 'transition' | 'risk_off' | 'crisis' — are
// NEVER renamed: they're persisted to Redis, embedded in the fitted GMM model
// pickle (backend/archimedes/services/gmm_model.pkl), and sent over
// /api/regime/*. This module is a DISPLAY layer only: it maps each stable wire
// value to a plain-language name, a one-line definition, and the agent's actual
// exposure response, so the UI can stop showing esoteric labels like "risk_on".
//
// The exposure multipliers below mirror REGIME_MULTIPLIER in
// backend/archimedes/services/portfolio_constructor.py (RISK_ON 1.0 /
// TRANSITION 0.7 / RISK_OFF 0.4 / CRISIS 0.1) — keep them in sync if that
// table changes.

export const REGIME_META = {
  risk_on: {
    label: 'Calm',
    tagline: 'Low volatility, positive trend',
    definition:
      'Low VIX, prices above their moving averages, and tight credit spreads. ' +
      'Conditions favor taking risk, so the agent sizes positions in full.',
    exposure: 'Full risk exposure (≈1.0× position sizing)',
    color: 'var(--positive)',
    bg: 'rgba(16,185,129,0.08)',
    border: 'rgba(16,185,129,0.25)',
    tag: 'tag-positive',
  },
  transition: {
    label: 'Choppy',
    tagline: 'Mixed signals, rising uncertainty',
    definition:
      'Conflicting signals and increasing uncertainty — the market is between ' +
      'regimes. The agent trims exposure as a precaution while direction resolves.',
    exposure: 'Reduced exposure (≈0.7× position sizing)',
    color: '#f59e0b',
    bg: 'rgba(245,158,11,0.08)',
    border: 'rgba(245,158,11,0.25)',
    tag: 'tag-accent',
  },
  risk_off: {
    label: 'Defensive',
    tagline: 'Elevated volatility, weakening trend',
    definition:
      'Rising VIX, prices breaking below moving averages, and widening credit ' +
      'spreads. The agent cuts risk and rotates the freed weight toward cash-like assets.',
    exposure: 'Low exposure (≈0.4× position sizing)',
    color: 'var(--negative)',
    bg: 'rgba(239,68,68,0.08)',
    border: 'rgba(239,68,68,0.25)',
    tag: 'tag-muted',
  },
  crisis: {
    label: 'Crisis',
    tagline: 'Extreme volatility, flight to safety',
    definition:
      'Extreme VIX, cross-asset correlations spiking toward 1, and a broad flight ' +
      'to safety. The agent moves to near-flat, capital-preservation mode.',
    exposure: 'Minimal exposure (≈0.1× position sizing)',
    color: 'var(--negative)',
    bg: 'rgba(239,68,68,0.12)',
    border: 'rgba(239,68,68,0.35)',
    tag: 'tag-muted',
  },
}

// Display order from calmest to most defensive — used by the definitions panel.
export const REGIME_ORDER = ['risk_on', 'transition', 'risk_off', 'crisis']

const UNKNOWN_META = {
  label: 'Unknown',
  tagline: 'Regime unavailable',
  definition:
    'No market-regime read is available yet — the agent feed is not connected or ' +
    'has not produced a classification. The agent falls back to a conservative default.',
  exposure: 'Conservative default until a regime is detected',
  color: 'var(--text-4)',
  bg: 'rgba(255,255,255,0.04)',
  border: 'var(--glass-border)',
  tag: 'tag-muted',
}

// Look up presentation metadata for a wire value. Unknown / consensus-only
// values fall back to a safe "Unknown" descriptor rather than throwing.
export function regimeMeta(value) {
  return REGIME_META[value] || UNKNOWN_META
}

// Plain-language label for a wire value (e.g. 'risk_on' -> 'Calm').
export function regimeLabel(value) {
  return regimeMeta(value).label
}
