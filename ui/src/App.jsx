import { useState, useEffect, useCallback } from 'react'
import { getAddress, disconnectWallet, reconnectWallet } from './config'
import Layout from './components/Layout'
import Landing from './components/Landing'
import Generate from './components/Generate'
import Portfolio from './components/Portfolio'
import Learnings from './components/Learnings'
import Strategies from './components/Strategies'   // serves /library route ("Example Library")
import CorpusExplorer from './components/CorpusExplorer'
import Reasoning from './components/Reasoning'
import VaultDetail from './components/VaultDetail'
import './App.css'

// Spine routing per docs/user-stories.md. Anything not in this map is gone.
// vault-detail is a deep-link only (reached from Portfolio); reasoning is a
// top-level page until per-card trace-modal affordances are wired everywhere.
const PAGE_TO_PATH = {
  landing:   '/',
  generate:  '/generate',
  library:   '/library',
  corpus:    '/corpus',
  portfolio: '/portfolio',
  reasoning: '/reasoning',
  learnings: '/learnings',
  about:     '/about',
  imprint:   '/imprint',
}

const PATH_TO_PAGE = Object.fromEntries(
  Object.entries(PAGE_TO_PATH).map(([page, path]) => [path, page])
)

function resolveRoute(pathname = '/', search = '') {
  if (PATH_TO_PAGE[pathname]) {
    return { page: PATH_TO_PAGE[pathname], vaultAddress: null, traceId: null, matched: true }
  }

  if (pathname.startsWith('/portfolio/vaults/')) {
    const rawAddress = pathname.replace('/portfolio/vaults/', '')
    if (rawAddress) return { page: 'vault-detail', vaultAddress: rawAddress, traceId: null, matched: true }
  }

  if (pathname.startsWith('/reasoning/')) {
    const id = pathname.replace('/reasoning/', '')
    if (id) return { page: 'reasoning', vaultAddress: null, traceId: id, matched: true }
  }

  // Legacy paths still in the wild — funnel them to the spine.
  const params = new URLSearchParams(search)
  const vaultAddress = params.get('vault')
  if (vaultAddress) return { page: 'vault-detail', vaultAddress, traceId: null, matched: true }

  return { page: 'landing', vaultAddress: null, traceId: null, matched: false }
}

function pageToPath(page, selectedVault = null) {
  if (page === 'vault-detail' && selectedVault) return `/portfolio/vaults/${selectedVault}`
  return PAGE_TO_PATH[page] ?? '/'
}

// ─── Main App ────────────────────────────────────────────────

export default function App() {
  const initialRoute = resolveRoute(window.location.pathname, window.location.search)

  const [page, setPage] = useState(initialRoute.page)
  const [walletAddr, setWalletAddr] = useState(null)
  const [selectedVault, setSelectedVault] = useState(initialRoute.vaultAddress)

  // Reconnect a previously connected wallet on mount (silent — uses eth_accounts,
  // no popup). The wallet-changed event keeps state in sync if the user changes
  // accounts or chains from within the extension.
  useEffect(() => {
    reconnectWallet().then(result => {
      if (result) setWalletAddr(result.address)
    })
  }, [])

  useEffect(() => {
    const handler = (e) => setWalletAddr(e.detail.address)
    window.addEventListener('wallet-changed', handler)
    return () => window.removeEventListener('wallet-changed', handler)
  }, [])

  const handleConnect = (addr) => setWalletAddr(addr)
  const handleDisconnect = () => { disconnectWallet(); setWalletAddr(null) }

  const navigateToPage = useCallback((nextPage, opts = {}) => {
    const nextVault = opts.vaultAddress ?? selectedVault
    const nextPath = pageToPath(nextPage, nextVault)
    const method = opts.replace ? 'replaceState' : 'pushState'

    if (window.location.pathname + window.location.search !== nextPath) {
      window.history[method]({}, '', nextPath)
    }

    setPage(nextPage)
    if (Object.prototype.hasOwnProperty.call(opts, 'vaultAddress')) {
      setSelectedVault(opts.vaultAddress)
    } else if (nextPage !== 'vault-detail') {
      setSelectedVault(null)
    }
  }, [selectedVault])

  const selectVault = (addr) => navigateToPage('vault-detail', { vaultAddress: addr })
  const backToPortfolio = () => navigateToPage('portfolio', { vaultAddress: null })
  const selectTrace = (_id) => navigateToPage('reasoning')

  useEffect(() => {
    if (!initialRoute.matched) {
      window.history.replaceState({}, '', '/')
    }
    const onPopState = () => {
      const route = resolveRoute(window.location.pathname, window.location.search)
      setPage(route.page)
      setSelectedVault(route.vaultAddress)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [initialRoute.matched])

  const renderPage = () => {
    switch (page) {
      case 'landing':      return <Landing onNavigate={navigateToPage} onConnect={() => {/* topbar handles modal */}} walletAddr={walletAddr} />
      case 'generate':     return <Generate />
      case 'library':      return <Strategies />
      case 'corpus':       return <CorpusExplorer />
      case 'portfolio':    return <Portfolio walletAddr={walletAddr} onSelectVault={selectVault} onSelectTrace={selectTrace} />
      case 'reasoning':    return <Reasoning />
      case 'learnings':    return <Learnings />
      case 'vault-detail': return <VaultDetail address={selectedVault} onBack={backToPortfolio} />
      default:             return <Landing onNavigate={navigateToPage} onConnect={() => {}} walletAddr={walletAddr} />
    }
  }

  if (page === 'landing') {
    return <Landing onNavigate={navigateToPage} onConnect={handleConnect} walletAddr={walletAddr} />
  }

  return (
    <Layout page={page} setPage={navigateToPage} walletAddr={walletAddr} onConnect={handleConnect} onDisconnect={handleDisconnect}>
      {renderPage()}
    </Layout>
  )
}
