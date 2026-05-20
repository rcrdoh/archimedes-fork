import { useState } from 'react'
import WalletConnect from './WalletConnect'
import Breadcrumbs from './Breadcrumbs'
import { NEW_CONTRACTS } from '../config'

// Spine per docs/user-stories.md. Reasoning is in nav until the per-page modal
// affordances are fully wired (user-stories.md ideal); for now traces need a
// browse surface so users can actually inspect them.
const NAV = [
  { group: '', items: [
    { id: 'landing',   label: 'Home' },
    { id: 'generate',  label: 'Generate' },
    { id: 'library',   label: 'Library' },
    { id: 'corpus',    label: 'Corpus' },
    { id: 'portfolio', label: 'Portfolio' },
    { id: 'reasoning', label: 'Reasoning' },
    { id: 'learnings', label: 'Learnings' },
  ]},
]

export const PAGE_LABELS = {
  landing: 'Home',
  generate: 'Generate',
  library: 'Library',
  corpus: 'Corpus',
  portfolio: 'Portfolio',
  reasoning: 'Reasoning',
  learnings: 'Learnings',
  'vault-detail': 'Vault Details',
  about: 'About',
  imprint: 'Imprint',
}

export default function Layout({ page, setPage, walletAddr, onConnect, onDisconnect, children }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const blockLabel = Object.keys(NEW_CONTRACTS).length ? 'Arc · Testnet live' : 'Arc · Connecting'

  const handleNav = (id) => {
    setPage(id)
    setMenuOpen(false)
  }
  // Semi-hard gate: prompt for wallet on every page except Landing (the marketing
  // surface) until it's connected. Browse is still allowed; deploy + portfolio
  // surfaces themselves enforce wallet at their own action sites.
  const showWalletBanner = !walletAddr && page !== 'landing'

  return (
    <div className="shell">
      {/* Mobile overlay — uses UnoCSS `fixed inset-0` + App.css `.sidebar-overlay` */}
      {menuOpen && (
        <div
          className="fixed inset-0 sidebar-overlay"
          onClick={() => setMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      {showWalletBanner && (
        <div
          role="banner"
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, zIndex: 50,
            background: 'linear-gradient(90deg, rgba(245, 158, 11, 0.18), rgba(245, 158, 11, 0.06))',
            borderBottom: '1px solid rgba(245, 158, 11, 0.35)',
            padding: '8px 16px',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16,
            fontSize: '0.85rem', color: 'var(--text-2)',
            backdropFilter: 'blur(8px)',
          }}
        >
          <span>
            <strong style={{ color: 'var(--accent)' }}>⚠ Wallet not connected.</strong>{' '}
            You can browse and generate strategies, but you can't deploy, deposit, or see your portfolio without a wallet.
          </span>
          <a
            href="#wallet"
            onClick={(e) => { e.preventDefault(); document.querySelector('.wallet-chip')?.click() }}
            style={{
              padding: '4px 12px', borderRadius: 6, background: 'var(--accent)', color: '#0c0a09',
              fontWeight: 600, textDecoration: 'none', fontSize: '0.8rem',
            }}
          >
            Connect Wallet →
          </a>
        </div>
      )}
      <aside className={`sidebar${menuOpen ? ' sidebar-open' : ''}`} style={showWalletBanner ? { paddingTop: 50 } : undefined}>
        <div className="sidebar-brand">
          <div className="logo-mark">
            <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M8 1L14 5v6l-6 4-6-4V5l6-4z" stroke="#09090B" strokeWidth="1.5"/>
              <circle cx="8" cy="8" r="2.5" stroke="#09090B" strokeWidth="1.5"/>
            </svg>
          </div>
          <div className="flex-1 min-w-0">
            <div className="logo-text">Archimedes</div>
            <div className="logo-sub">Portfolio Intelligence</div>
          </div>
          <button
            className="sidebar-close-btn"
            onClick={() => setMenuOpen(false)}
            aria-label="Close menu"
          >
            ✕
          </button>
        </div>

        <nav>
          {NAV.map((group, gi) => (
            <div key={group.group || gi} className="nav-group">
              {group.group && <div className="nav-group-label">{group.group}</div>}
              {group.items.map(item => (
                <button
                  key={item.id}
                  type="button"
                  className={`nav-link${page === item.id || (item.id === 'portfolio' && page === 'vault-detail') ? ' active' : ''}`}
                  onClick={() => handleNav(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="live-dot" />
          {blockLabel}
        </div>
      </aside>

      <div className="main-area" style={showWalletBanner ? { paddingTop: 42 } : undefined}>
        <div className="topbar">
          {/* Left: hamburger (mobile) + breadcrumbs */}
          <div className="flex items-center gap-3">
            <button
              className={`hamburger-btn${menuOpen ? ' open' : ''}`}
              onClick={() => setMenuOpen(v => !v)}
              aria-label="Toggle navigation"
              aria-expanded={menuOpen}
            >
              <span className="hamburger-line" />
              <span className="hamburger-line" />
              <span className="hamburger-line" />
            </button>
            <Breadcrumbs page={page} setPage={setPage} />
          </div>
          <WalletConnect address={walletAddr} onConnect={onConnect} onDisconnect={onDisconnect} />
        </div>
        <main className={`page-content page-${page}`}>{children}</main>
      </div>
    </div>
  )
}
