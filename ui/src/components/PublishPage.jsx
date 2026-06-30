import { useState } from 'react'
import { apiPost } from '../api'
import { getWalletClient, getAddress } from '../config'
import { authenticateWithSIWE } from '../siwe'

export default function PublishPage({ walletAddr, onNavigate }) {
  const [strategyId, setStrategyId] = useState('')
  const [poolId, setPoolId] = useState('')
  const [vaultAddress, setVaultAddress] = useState('')
  const [platformWallet, setPlatformWallet] = useState('')
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  const handlePublish = async (e) => {
    e.preventDefault()
    if (!walletAddr) {
      setError('Connect a wallet first')
      return
    }
    setPublishing(true)
    setError('')
    setResult(null)
    try {
      const walletClient = await getWalletClient()
      if (!walletClient) throw new Error('No wallet client available')
      await authenticateWithSIWE(walletClient, getAddress())

      const res = await apiPost('/api/marketplace/publish', {
        strategy_id: strategyId,
        pool_id: poolId || '0x' + '0'.repeat(64),
        vault_address: vaultAddress || '',
        platform_wallet: platformWallet || '',
      })
      setResult(res)
    } catch (e) {
      setError(e.message || 'Publish failed')
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div>
      <button className="btn-ghost mb-4" onClick={() => onNavigate?.('marketplace')}>
        ← Back to Marketplace
      </button>

      <div style={{ maxWidth: 520 }}>
        <h2 className="serif text-[2rem] mb-2">Publish a Strategy</h2>
        <p className="body mb-5">
          Deploy a publisher agent container for your strategy. Subscribers will
          be able to find and subscribe to it from the marketplace.
        </p>

        {result ? (
          <div className="card" style={{ padding: 18 }}>
            <p className="body mb-3" style={{ color: 'var(--positive)' }}>
              ✓ Publisher spawned successfully
            </p>
            <div className="caption flex flex-col gap-1.5">
              <div><span className="text-[var(--text-4)]">Container:</span> <code>{result.container_name}</code></div>
              <div><span className="text-[var(--text-4)]">Endpoint:</span> <code>{result.publisher_endpoint}</code></div>
              <div><span className="text-[var(--text-4)]">Strategy:</span> <code>{result.strategy_id}</code></div>
              <div><span className="text-[var(--text-4)]">Vault:</span> <code>{result.vault_address || '—'}</code></div>
            </div>
            <div className="flex gap-3 mt-4">
              <button className="btn-primary" onClick={() => onNavigate?.('strategy-detail', { strategyId: result.strategy_id })}>
                View Strategy
              </button>
              <button className="btn-secondary" onClick={() => { setResult(null); setStrategyId(''); setPoolId(''); setVaultAddress(''); setPlatformWallet('') }}>
                Publish Another
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handlePublish}>
            {error && (
              <div className="info-box warning" style={{ padding: 12, marginBottom: 16 }}>
                {error}
              </div>
            )}

            <div className="mb-4">
              <label className="caption text-[var(--text-4)] block mb-1">Strategy ID *</label>
              <input
                className="input"
                value={strategyId}
                onChange={e => setStrategyId(e.target.value)}
                placeholder="e.g. momentum_reversion_v1"
                required
                style={{ width: '100%' }}
              />
            </div>

            <div className="mb-4">
              <label className="caption text-[var(--text-4)] block mb-1">Pool ID (bytes32 hex)</label>
              <input
                className="input"
                value={poolId}
                onChange={e => setPoolId(e.target.value)}
                placeholder="0x0000... (auto-generated if empty)"
                style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.75rem' }}
              />
            </div>

            <div className="mb-4">
              <label className="caption text-[var(--text-4)] block mb-1">Vault Address</label>
              <input
                className="input"
                value={vaultAddress}
                onChange={e => setVaultAddress(e.target.value)}
                placeholder="0x... (optional — created if empty)"
                style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.75rem' }}
              />
            </div>

            <div className="mb-5">
              <label className="caption text-[var(--text-4)] block mb-1">Platform Wallet (fee recipient)</label>
              <input
                className="input"
                value={platformWallet}
                onChange={e => setPlatformWallet(e.target.value)}
                placeholder="0x... (uses PLATFORM_WALLET from env if empty)"
                style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.75rem' }}
              />
            </div>

            <button className="btn-primary" type="submit" disabled={publishing || !strategyId.trim()}>
              {publishing ? 'Publishing…' : 'Publish'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
