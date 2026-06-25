// Starter prompt library for the Generate flow (T1.6).
//
// Hand-picked briefs that route cleanly through the backend auto-router
// (_pick_pipeline → Fusion / Architect / Agent) and produce a strategy a user
// can deploy without further coaching. Clicking one fills the brief textarea so
// the user can edit/vary it before submitting.
//
// Each entry pairs a short, clickable `label` (what the chip/card shows) with
// the full `brief` text that lands in the input. `suggestedAssets` (optional)
// are display symbols from the supported universe (see assetUniverse.js) the
// example pairs well with — the UI can pre-select them alongside the brief.
//
// Keep this list tight and high-signal: a few good examples beat a long menu.

export const PROMPT_LIBRARY = [
  {
    id: 'treasury-alt-crypto-friday',
    label: 'Treasury alternative with Friday crypto upside',
    brief:
      'A 13-week treasury alternative with low volatility and crypto upside on Fridays',
    suggestedAssets: ['SHY', 'BIL', 'BTC'],
  },
  {
    id: 'trend-momentum-etfs',
    label: 'Regime-aware trend momentum on US ETFs',
    brief:
      'Trend-following momentum on liquid US equity ETFs, rebalanced monthly, regime-aware',
    suggestedAssets: ['SPY', 'QQQ', 'IWM'],
  },
  {
    id: 'defensive-vol-rotation',
    label: 'Defensive equity that rotates to bonds in vol spikes',
    brief:
      'Defensive equity strategy that rotates into bonds when realized volatility spikes',
    suggestedAssets: ['SPY', 'TLT', 'IEF'],
  },
  {
    id: 'value-quality-circuit-breaker',
    label: 'Large-cap value + quality with a drawdown circuit breaker',
    brief:
      'Long-only large-cap value with a quality screen and a max-drawdown circuit breaker',
    suggestedAssets: ['SPY', 'XLF', 'XLV'],
  },
  {
    id: 'gold-miners-pairs',
    label: 'Gold vs. gold-miners relative-value pair',
    brief:
      'A relative-value pair trade between gold and gold miners, mean-reverting on the spread, with a volatility-scaled position size',
    suggestedAssets: ['GLD', 'GDX'],
  },
  {
    id: 'sector-momentum-rotation',
    label: 'Monthly sector-momentum rotation',
    brief:
      'Rotate monthly into the top-performing US sectors by 6-month momentum, with a defensive cash sleeve when the broad market is below its 200-day average',
    suggestedAssets: ['XLK', 'XLE', 'XLF', 'XLV', 'XLI'],
  },
  {
    id: 'risk-parity-60-40',
    label: 'Risk-parity 60/40 with a regime overlay',
    brief:
      'A risk-parity take on the classic 60/40 stocks-and-bonds portfolio, with a macro-regime overlay that trims equity exposure in contractions',
    suggestedAssets: ['SPY', 'TLT', 'GLD'],
  },
  {
    id: 'crypto-momentum-vol-target',
    label: 'Volatility-targeted crypto momentum',
    brief:
      'Trend-following momentum on major crypto with a volatility target so position size shrinks when realized vol rises',
    suggestedAssets: ['BTC', 'ETH', 'SOL'],
  },
]

export default PROMPT_LIBRARY
