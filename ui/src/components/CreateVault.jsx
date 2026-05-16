import { useState, useEffect, useCallback } from 'react'

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

export default function CreateVault({ onVaultCreated }) {
  const [strategies, setStrategies] = useState([])
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(true)

  const [name, setName] = useState('')
  const [symbol, setSymbol] = useState('')
  const [mgmtFeeBps, setMgmtFeeBps] = useState(50)
  const [perfFeeBps, setPerfFeeBps] = useState(1000)
  const [agentAssisted, setAgentAssisted] = useState(true)
  const [selectedIds, setSelectedIds] = useState([])

  const [deploying, setDeploying] = useState(false)
  const [deployError, setDeployError] = useState('')
  const [vaultAddress, setVaultAddress] = useState(null)

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

  const toggleStrategy = (id) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]
    )
  }

  const deploy = async () => {
    setDeploying(true)
    setDeployError('')
    setVaultAddress(null)
    try {
      const data = await apiPost('/api/vaults/create', {
        name,
        symbol,
        management_fee_bps: Number(mgmtFeeBps),
        performance_fee_bps: Number(perfFeeBps),
        agent_assisted: agentAssisted,
        strategy_ids: selectedIds,
      })
      setVaultAddress(data.vault_address)
      if (onVaultCreated) onVaultCreated(data.vault_address)
    } catch (e) {
      setDeployError(e.message || 'Deployment failed')
    } finally {
      setDeploying(false)
    }
  }

  const canDeploy = name.trim() && symbol.trim() && !deploying

  return (
    <div className="panel">
      <h2>Create Vault</h2>
      <p className="hint" style={{ marginTop: 8 }}>
        Deploy a new managed vault on Arc. Select strategies to associate, set fee
        parameters, and optionally enable agent-assisted rebalancing.
      </p>

      <div className="card" style={{ marginTop: 20 }}>
        <h3>Vault details</h3>

        <div className="form-row" style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 12 }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="label">Vault name</label>
            <input
              className="chat-input"
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Archimedes Moderate Growth"
            />
          </div>
          <div className="form-group">
            <label className="label">Symbol</label>
            <input
              className="chat-input"
              type="text"
              value={symbol}
              onChange={e => setSymbol(e.target.value.toUpperCase())}
              placeholder="AMG"
              maxLength={16}
              style={{ width: 110 }}
            />
          </div>
        </div>

        <div className="form-row" style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 12 }}>
          <div className="form-group">
            <label className="label">Management fee (bps)</label>
            <input
              className="chat-input"
              type="number"
              min="0"
              max="1000"
              value={mgmtFeeBps}
              onChange={e => setMgmtFeeBps(e.target.value)}
              style={{ width: 120 }}
            />
            <div className="caption" style={{ marginTop: 4 }}>
              {(Number(mgmtFeeBps) / 100).toFixed(2)}% / year
            </div>
          </div>

          <div className="form-group">
            <label className="label">Performance fee (bps)</label>
            <input
              className="chat-input"
              type="number"
              min="0"
              max="3000"
              value={perfFeeBps}
              onChange={e => setPerfFeeBps(e.target.value)}
              style={{ width: 120 }}
            />
            <div className="caption" style={{ marginTop: 4 }}>
              {(Number(perfFeeBps) / 100).toFixed(2)}% on profits
            </div>
          </div>

          <div className="form-group" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <label className="label">Agent-assisted</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
              <button
                type="button"
                className={`btn${agentAssisted ? ' btn-primary' : ''}`}
                style={{ width: 'auto', padding: '4px 16px' }}
                onClick={() => setAgentAssisted(true)}
              >
                On
              </button>
              <button
                type="button"
                className={`btn${!agentAssisted ? ' btn-primary' : ''}`}
                style={{ width: 'auto', padding: '4px 16px' }}
                onClick={() => setAgentAssisted(false)}
              >
                Off
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Strategies</h3>
        <p className="hint" style={{ marginTop: 4 }}>
          Select strategies to associate with this vault.
          {selectedIds.length > 0 && ` ${selectedIds.length} selected.`}
        </p>

        {loading && <div className="loading" style={{ marginTop: 12 }}>Loading strategies…</div>}
        {loadError && (
          <div className="info-box warning" style={{ marginTop: 12 }}>
            Couldn't load strategies: {loadError}
          </div>
        )}

        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {strategies.map(s => {
            const selected = selectedIds.includes(s.id)
            return (
              <div
                key={s.id}
                className="vault-card vault-card-clickable"
                style={selected ? { border: '1px solid var(--accent, #6366F1)', background: 'rgba(99,102,241,0.08)' } : {}}
                onClick={() => toggleStrategy(s.id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <strong>{s.paper_title}</strong>
                  <span className={`badge${selected ? ' tier-1' : ''}`}>
                    {selected ? 'selected' : s.status}
                  </span>
                </div>
                {s.paper_authors?.length > 0 && (
                  <p className="caption" style={{ marginTop: 2 }}>{s.paper_authors.join(', ')}</p>
                )}
                <p className="hint" style={{ marginTop: 6 }}>{s.methodology_summary}</p>
                <p className="caption" style={{ marginTop: 4 }}>
                  {s.asset_universe?.join(' · ')} · {s.position_sizing} · {s.rebalance_frequency}
                </p>
              </div>
            )
          })}
        </div>
      </div>

      {deployError && (
        <div className="info-box warning" style={{ marginTop: 16 }}>
          Deployment failed: {deployError}
        </div>
      )}

      {vaultAddress && (
        <div className="info-box" style={{ marginTop: 16 }}>
          Vault deployed at <code>{vaultAddress}</code>. Navigating to vault…
        </div>
      )}

      <button
        className="btn btn-primary"
        style={{ marginTop: 20, width: '100%' }}
        onClick={deploy}
        disabled={!canDeploy}
      >
        {deploying ? 'Deploying vault…' : 'Deploy vault on Arc'}
      </button>
    </div>
  )
}
