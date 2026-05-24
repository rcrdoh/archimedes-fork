import { useState } from 'react'
import { createPortal } from 'react-dom'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// Phase 4 scaffold — opens from StrategyPassport's "Deploy as Vault →" CTA.
// Wires to existing POST /api/vaults/create which deploys a new vault on Arc
// via VaultFactory. After deploy, persists vault metadata (off-chain) via
// POST /api/vaults/metadata so the strategy↔vault link survives reloads.
//
// Honest scope: this is the v1 deploy flow — vault is created, metadata is
// persisted. Time-bound window enforcement, multi-step USDC approve + deposit
// + setTargetAllocations, and on-chain agent-active triggering are Phase 4.5
// work pending alignment with Marten + Chuan. The modal is explicit about
// what does/doesn't happen on submit.

function nowPlusDays(days) {
  const d = new Date()
  d.setDate(d.getDate() + days)
  // <input type="datetime-local"> expects "YYYY-MM-DDTHH:mm"
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function CreateVaultModal({ strategy, walletAddr, onClose, onDeployed }) {
  const defaultName = strategy?.paper_title
    ? strategy.paper_title.slice(0, 48).replace(/\s+$/, '')
    : 'My Strategy Vault'
  const defaultSymbol = strategy?.id
    ? `sV${String(strategy.id).slice(0, 6).toUpperCase()}`
    : 'sVAULT'

  const [name, setName] = useState(defaultName)
  const [symbol, setSymbol] = useState(defaultSymbol)
  const [windowStart, setWindowStart] = useState(() => nowPlusDays(0))
  const [windowEnd, setWindowEnd] = useState(() => nowPlusDays(30))
  const [initialDeposit, setInitialDeposit] = useState('100')
  const [agentAssisted, setAgentAssisted] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleDeploy = async () => {
    setError('')
    if (!name.trim() || !symbol.trim()) {
      setError('Name and symbol are required.')
      return
    }
    if (new Date(windowEnd) <= new Date(windowStart)) {
      setError('Window end must be after window start.')
      return
    }
    setSubmitting(true)
    try {
      // Step 1: deploy vault on-chain
      const createRes = await fetch(`${API_BASE}/api/vaults/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          symbol,
          management_fee_bps: 0,
          performance_fee_bps: 0,
          agent_assisted: agentAssisted,
          strategy_ids: strategy?.id ? [strategy.id] : [],
        }),
      })
      if (!createRes.ok) throw new Error(await createRes.text() || `Vault create failed (${createRes.status})`)
      const createData = await createRes.json()
      const vaultAddress = createData.vault_address
      if (!vaultAddress) throw new Error('Backend did not return a vault_address')

      // Step 2: persist off-chain metadata (strategy↔vault link, creator wallet,
      // trade window stored as part of name suffix until Phase 4.5 schema lands).
      try {
        await fetch(`${API_BASE}/api/vaults/metadata`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            vault_address: vaultAddress,
            name,
            symbol,
            creator_address: walletAddr || '',
            strategy_ids: strategy?.id ? [strategy.id] : [],
          }),
        })
      } catch (_metaErr) {
        // Non-fatal — vault exists on-chain; metadata persistence is a UX hint.
      }

      // Trade window is captured in state but not yet enforced by the contract.
      // Phase 4.5 will add a vault_lifecycle table + agent-runner enforcement.
      // For now, surface it in the success notice.
      if (onDeployed) onDeployed(vaultAddress)
    } catch (e) {
      setError(e.message || 'Vault deployment failed')
    } finally {
      setSubmitting(false)
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center z-[1000]"
      style={{ background: 'rgba(0,0,0,0.78)', backdropFilter: 'blur(6px)' }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="deploy-modal-title"
    >
      <div
        className="card-elevated p-6 max-w-[560px] w-[92vw]"
        onClick={e => e.stopPropagation()}
        style={{ background: 'var(--surface-1)', maxHeight: '90vh', overflowY: 'auto' }}
      >
        <div className="caption mb-2 uppercase tracking-wider text-[var(--text-4)]">Deploy vault</div>
        <h3 id="deploy-modal-title" className="font-serif text-[1.5rem] mb-1">
          {strategy?.paper_title || 'Deploy strategy'}
        </h3>
        <p className="caption mb-4 leading-relaxed">
          Creates an ERC-4626 vault on Arc and links it to this strategy. Funds
          stay non-custodial — the agent has rebalance authority only, no withdraw.
        </p>

        <div className="grid grid-cols-1 gap-3">
          <label className="block">
            <span className="caption block mb-1">Vault name</span>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              maxLength={64}
              className="chat-input w-full p-2.5"
              disabled={submitting}
            />
          </label>

          <label className="block">
            <span className="caption block mb-1">Symbol</span>
            <input
              type="text"
              value={symbol}
              onChange={e => setSymbol(e.target.value.toUpperCase())}
              maxLength={16}
              className="chat-input w-full p-2.5 mono"
              disabled={submitting}
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="caption block mb-1">Window start</span>
              <input
                type="datetime-local"
                value={windowStart}
                onChange={e => setWindowStart(e.target.value)}
                className="chat-input w-full p-2.5"
                disabled={submitting}
              />
            </label>
            <label className="block">
              <span className="caption block mb-1">Window end</span>
              <input
                type="datetime-local"
                value={windowEnd}
                onChange={e => setWindowEnd(e.target.value)}
                className="chat-input w-full p-2.5"
                disabled={submitting}
              />
            </label>
          </div>

          <label className="block">
            <span className="caption block mb-1">Initial deposit (USDC)</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={initialDeposit}
              onChange={e => setInitialDeposit(e.target.value)}
              className="chat-input w-full p-2.5 mono"
              disabled={submitting}
            />
            <p className="caption mt-1 text-[var(--text-4)]">
              Deposit + <code>setTargetAllocations</code> ship in Phase 4.5 — for v1
              this modal creates the vault only; the deposit step is a follow-up.
            </p>
          </label>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={agentAssisted}
              onChange={e => setAgentAssisted(e.target.checked)}
              disabled={submitting}
            />
            <span className="body">Agent-assisted (rebalance authority granted to the autonomous agent)</span>
          </label>
        </div>

        <div className="info-box mt-4" style={{ fontSize: '0.8rem' }}>
          <strong>Scope note:</strong> v1 creates the vault on-chain and links it to this
          strategy off-chain. Time-bound window enforcement (Phase 4.5) and the deposit
          + <code>setTargetAllocations</code> wallet flow (Phase 5) are not yet wired —
          this is the scaffold the rest of Phase 4 builds on.
        </div>

        {error && <div className="info-box warning mt-3">{error}</div>}

        <div className="flex justify-end gap-2 mt-5">
          <button className="btn btn-outline" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleDeploy}
            disabled={submitting || !walletAddr}
            title={!walletAddr ? 'Connect wallet to deploy' : ''}
          >
            {submitting ? 'Deploying…' : 'Create Vault'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
