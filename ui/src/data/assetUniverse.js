// Supported-asset universe for the Generate asset picker (T1.6).
//
// Mirrors the backend single source of truth — GLOBAL_ASSETS in
// backend/archimedes/services/strategy_signal_evaluator.py (issue #682). These
// are the display symbols the strategy_fusion universe-derivation resolves; the
// picker sends the user's selection as `asset_classes` on the generate request,
// and the backend's derive_asset_universe() turns them into the strategy's
// concrete asset_universe (never a hardcoded ["SPY"]).
//
// Kept add-only by convention: when GLOBAL_ASSETS grows, add the new display
// symbol here so the picker exposes it. Grouped into user-facing buckets so the
// chips stay scannable.

export const ASSET_GROUPS = [
  {
    id: 'us_equity',
    label: 'US equity & sectors',
    assets: [
      'SPY', 'QQQ', 'IWM', 'DIA',
      'XLE', 'XLF', 'XLK', 'XLV', 'XLI', 'XLU',
    ],
  },
  {
    id: 'us_stocks',
    label: 'US stocks',
    assets: [
      'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AMD', 'AVGO',
      'ORCL', 'CRM', 'NFLX', 'JPM', 'BAC', 'GS', 'V', 'MA', 'BRK.B', 'LLY',
      'UNH', 'JNJ', 'MRK', 'PFE', 'XOM', 'CVX', 'COP', 'WMT', 'COST', 'HD',
      'PG', 'COIN', 'MSTR', 'PLTR',
    ],
  },
  {
    id: 'intl_equity',
    label: 'International equity',
    assets: [
      'ASML', 'SAP', 'NESN', 'NVO', 'AZN', 'SHEL', 'BP', 'HSBC', 'TTE', 'RHM',
      'LVMH', 'SIE', 'EZU', 'DAX_ETF', 'FTSE_ETF', 'CAC_ETF', 'FTSE100',
      'DAX40', 'CAC40', 'TSM', 'BABA', 'TM', 'SONY', 'SE', 'TCEHY', 'EWJ',
      'NIKKEI', 'MCHI', 'INDA', 'EWY', 'EEM',
    ],
  },
  {
    id: 'turkey',
    label: 'Turkish equity',
    assets: [
      'THYAO', 'KCHOL', 'GARAN', 'ASELS', 'AKBNK', 'SAHOL', 'BIMAS', 'EREGL',
      'TUR_ETF', 'BIST100',
    ],
  },
  {
    id: 'metals',
    label: 'Metals',
    assets: [
      'GLD', 'GOLD_FUT', 'SLV', 'SILVER_FUT', 'PLATINUM', 'PALLADIUM',
      'COPPER_FUT', 'GDX', 'GDXJ',
    ],
  },
  {
    id: 'energy',
    label: 'Energy',
    assets: ['USO', 'WTI_FUT', 'BRENT_FUT', 'UNG', 'NATGAS_FUT'],
  },
  {
    id: 'agriculture',
    label: 'Agriculture',
    assets: ['CORN_FUT', 'WHEAT_FUT', 'SOY_FUT'],
  },
  {
    id: 'fixed_income',
    label: 'Fixed income & credit',
    assets: [
      'TLT', 'IEF', 'SHY', 'BIL', 'TIP', 'AGG', 'HYG', 'LQD', 'EMB', 'MUB',
    ],
  },
  {
    id: 'fx',
    label: 'FX',
    assets: ['EUR/USD', 'USD/TRY', 'GBP/USD', 'USD/JPY'],
  },
  {
    id: 'crypto',
    label: 'Crypto',
    assets: ['BTC', 'ETH', 'SOL'],
  },
]

// Flat, de-duped list of every supported display symbol (handy for validation
// and search). Mirrors the union of ASSET_GROUPS[*].assets.
export const SUPPORTED_ASSETS = Array.from(
  new Set(ASSET_GROUPS.flatMap((g) => g.assets)),
)

export default ASSET_GROUPS
