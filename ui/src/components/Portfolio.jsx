import { useState, useEffect, useCallback } from 'react'
import {
  publicClient,
  VAULT_ABI, VAULT_FACTORY_ABI, NEW_CONTRACTS,
} from '../config'
import PortfolioAdvisor from './PortfolioAdvisor'
import RegimePanel from './RegimePanel'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// Portfolio page — consolidates the old Dashboard + Vaults + Risk + agent
// activity into the single "what do I own and what is the agent doing"
// surface per docs/user-stories.md §④ Monitor. Wallet-gated — without a
// connected wallet we show the connect prompt rather than fake data.

function timeAgo(iso) {
  const d = typeof iso === 'string' ? new Date(iso) : new Date(iso * 1000)
  const secs = Math.floor((Date.now() - d.getTime()) / 1000)
  if (Number.isNaN(secs)) return '—'
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

function shortAddr(a) {
  return a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '—'
}

export default function Portfolio({ walletAddr, onSelectVault, onSelectTrace }) {
  const [userVaults, setUserVaults] = useState([])
  const [agentStatus, setAgentStatus] = useState(null)
  const [recentTraces, setRecentTraces] = useState([])
  const [tracesLoading, setTracesLoading] = useState(false)
  const [vaultsLoading, setVaultsLoading] = useState(false)
  const [advisorOpen, setAdvisorOpen] = useState(false)

  const loadVaults = useCallback(async () => {
    const factoryAddr = NEW_CONTRACTS.vaultFactory
    if (!factoryAddr || !walletAddr) { setUserVaults([]); return }
    setVaultsLoading(true)
    try {
      const creatorVaults = await publicClient.readContract({
        address: factoryAddr, abi: VAULT_FACTORY_ABI, functionName: 'getVaultsByCreator', args: [walletAddr],
      })
      const rows = await Promise.all((creatorVaults || []).map(async (addr) => {
        try {
          const [totalAssets, tier, name] = await Promise.all([
            publicClient.readContract({ address: addr, abi: VAULT_ABI, functionName: 'totalAssets' }),
            publicClient.readContract({ address: addr, abi: VAULT_ABI, functionName: 'tier' }),
            publicClient.readContract({ address: addr, abi: VAULT_ABI, functionName: 'name' }).catch(() => ''),
          ])
          return { address: addr, aum: Number(totalAssets) / 1e6, tier: Number(tier), name }
        } catch { return null }
      }))
      setUserVaults(rows.filter(Boolean))
    } catch {
      setUserVaults([])
    } finally {
      setVaultsLoading(false)
    }
  }, [walletAddr])

  const loadAgentAndRegime = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/agent/status`)
      if (r.ok) setAgentStatus(await r.json())
    } catch {}
    // Regime is loaded + rendered by <RegimePanel /> above, not duplicated here.
  }, [])

  const loadTraces = useCallback(async () => {
    setTracesLoading(true)
    try {
      const r = await fetch(`${API_BASE}/api/traces/?limit=20`)
      if (r.ok) {
        const data = await r.json()
        setRecentTraces(data.traces || [])
      }
    } catch {}
    setTracesLoading(false)
  }, [])

  useEffect(() => { loadVaults() }, [loadVaults])
  useEffect(() => { loadAgentAndRegime(); loadTraces() }, [loadAgentAndRegime, loadTraces])
  useEffect(() => {
    const t = setInterval(() => { loadAgentAndRegime(); loadTraces() }, 30_000)
    return () => clearInterval(t)
  }, [loadAgentAndRegime, loadTraces])

  const totalAum = userVaults.reduce((s, v) => s + v.aum, 0)

  return (
    <div>
      <div className="max-w-[720px] mb-6">
        <h2 className="serif text-[2rem] mb-2.5">Portfolio</h2>
        <p className="body">
          What you own, how the agent is managing it, and what it's been doing recently.
          Every rebalance has a reasoning trace anchored on Arc — click into any decision
          to inspect what the agent saw and why it acted.
        </p>
      </div>

      {!walletAddr && (
        <div className="info-box warning mb-6">
          Connect your wallet (top right) to load your vault positions. Agent activity
          and the live regime classification are visible without a wallet.
        </div>
      )}

      {/* Regime sidebar — top of portfolio page */}
      <RegimePanel />

      {/* Status strip — agent state is Redis-backed (regardless of wallet); regime
          lives in the RegimePanel block above to avoid duplication. */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <div className="card-flat p-4">
          <div className="label mb-2">Your Vaults</div>
          <div className="text-[1.8rem] font-bold">{walletAddr ? userVaults.length : '—'}</div>
          <div className="caption mt-1.5">
            {walletAddr ? `${userVaults.filter(v => v.tier === 1).length} Tier 1 · ${userVaults.filter(v => v.tier === 2).length} Tier 2` : 'connect wallet'}
          </div>
        </div>
        <div className="card-flat p-4">
          <div className="label mb-2">Total AUM</div>
          <div className="text-[1.8rem] font-bold">
            {walletAddr ? `$${totalAum.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
          </div>
          <div className="caption positive mt-1.5">Arc Testnet</div>
        </div>
        <div className="card-flat p-4">
          <div className="label mb-2">Agent</div>
          <div className="flex items-center gap-2 font-bold text-[1.8rem]">
            <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${agentStatus?.alive ? 'bg-[var(--positive)] shadow-[0_0_6px_var(--positive)]' : 'bg-[var(--negative)]'}`} />
            {agentStatus?.alive ? 'Alive' : 'Offline'}
          </div>
          <div className="caption mt-1.5">
            Last heartbeat: {agentStatus?.last_heartbeat ? timeAgo(agentStatus.last_heartbeat) : '—'}
          </div>
        </div>
      </div>

      {/* User vaults */}
      {walletAddr && (
        <div className="mb-7">
          <div className="label mb-3">Your Vault Positions</div>
          {vaultsLoading && <div className="caption">Loading vaults…</div>}
          {!vaultsLoading && userVaults.length === 0 && (
            <div className="card" style={{ padding: 18 }}>
              <p className="body mb-2">You don't own any vaults yet.</p>
              <p className="caption">
                Go to <a href="/generate" style={{ color: 'var(--accent)' }}>Generate</a> to design a
                strategy, then deploy it into a non-custodial vault from the result card.
              </p>
            </div>
          )}
          {userVaults.length > 0 && (
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
              {userVaults.map(v => (
                <div key={v.address} className="card vault-card-clickable" onClick={() => onSelectVault?.(v.address)}>
                  <div className="flex justify-between mb-2">
                    <code style={{ fontSize: '0.8rem' }}>{shortAddr(v.address)}</code>
                    <span className={`tag ${v.tier === 1 ? 'tag-accent' : 'tag-muted'}`}>T{v.tier}</span>
                  </div>
                  {v.name && <div className="caption" style={{ marginBottom: 4 }}>{v.name}</div>}
                  <div className="text-[1.2rem] font-bold">${v.aum.toFixed(2)}</div>
                  <div className="caption">AUM</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Allocation Advisor — collapsible section */}
      <div className="mb-7">
        <button
          type="button"
          className="flex items-center gap-2 w-full text-left mb-3"
          onClick={() => setAdvisorOpen(v => !v)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
        >
          <span className={`i-lucide-chevron-${advisorOpen ? 'down' : 'right'} w-4 h-4 text-[var(--text-4)]`} />
          <span className="label" style={{ margin: 0 }}>Allocation Advisor</span>
        </button>
        {advisorOpen && <PortfolioAdvisor />}
      </div>

      {/* Agent activity feed — real traces from /api/traces */}
      <div>
        <div className="label mb-3">Recent Agent Activity</div>
        {tracesLoading && <div className="caption">Loading traces…</div>}
        {!tracesLoading && recentTraces.length === 0 && (
          <div className="card" style={{ padding: 18 }}>
            <p className="body" style={{ marginBottom: 6 }}>No agent activity yet.</p>
            <p className="caption">
              The agent runner persists a reasoning trace every time it makes a decision.
              Construction traces from the Generate page also appear here.
            </p>
          </div>
        )}
        {recentTraces.length > 0 && (
          <div className="flex flex-col gap-2">
            {recentTraces.map(t => (
              <div
                key={t.id}
                className="trace-card vault-card-clickable"
                onClick={() => onSelectTrace?.(t.id)}
                style={{ cursor: 'pointer' }}
              >
                <div className="flex justify-between items-center gap-3 flex-wrap">
                  <div>
                    <span className="tag tag-muted mr-2 capitalize">{t.decision_type}</span>
                    <strong style={{ fontSize: '0.9rem' }}>{t.trigger}</strong>
                  </div>
                  <span className="caption">{t.timestamp ? timeAgo(t.timestamp) : ''}</span>
                </div>
                {t.reasoning && (
                  <div className="caption mt-1.5 leading-relaxed">
                    {t.reasoning.slice(0, 180)}{t.reasoning.length > 180 ? '…' : ''}
                  </div>
                )}
                <div className="caption mt-1.5 flex gap-3 text-[var(--text-3)]">
                  {t.vault_address && <span>vault {shortAddr(t.vault_address)}</span>}
                  {t.trace_hash && <span className="mono">{t.trace_hash.slice(0, 10)}…</span>}
                  {t.is_verified
                    ? <span className="flex items-center gap-1 text-[var(--positive)]"><span className="i-lucide-check-circle w-3.5 h-3.5" /> anchored on Arc</span>
                    : <span className="flex items-center gap-1 text-[var(--text-3)]" title="Trace hashed + persisted off-chain; on-chain anchor pending (registry write didn't complete yet — usually transient).">
                        <span className="i-lucide-clock w-3.5 h-3.5" /> anchor pending
                      </span>
                  }
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
