import { useState } from 'react'
import { createPortal } from 'react-dom'
import { connectWallet, getAvailableProviders } from '../config'

export default function WalletConnect({ address, onConnect, onDisconnect }) {
  const [showModal, setShowModal] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const available = getAvailableProviders()

  const handleConnect = async (providerId) => {
    setBusy(true)
    setError('')
    try {
      const result = await connectWallet(providerId)
      setShowModal(false)
      onConnect(result.address)
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  if (address) {
    return (
      <div className="wallet-chip" onClick={onDisconnect} title="Click to disconnect">
        <span className="dot" />
        <span>{address.slice(0, 6)}…{address.slice(-4)}</span>
      </div>
    )
  }

  return (
    <>
      <button className="wallet-chip" onClick={() => setShowModal(true)}>
        Connect Wallet
      </button>

      {showModal && createPortal(
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Connect Wallet</h3>
            <p className="caption">Select a wallet to interact with Arc Testnet contracts.</p>

            {available.length === 0 ? (
              <div className="info-box warning mt-3">
                No wallets detected. Install <a href="https://metamask.io" target="_blank" rel="noreferrer">MetaMask</a> or{' '}
                <a href="https://www.coinbase.com/wallet" target="_blank" rel="noreferrer">Coinbase Wallet</a>.
              </div>
            ) : (
              <div className="wallet-options">
                {available.map(p => (
                  <button key={p.id} className="wallet-option" onClick={() => handleConnect(p.id)} disabled={busy}>
                    <span className={`wallet-icon ${p.icon} w-5 h-5`} />
                    <span>{p.name}</span>
                  </button>
                ))}
              </div>
            )}

            {error && <div className="status mt-3">{error}</div>}

            <button className="btn btn-outline mt-3 w-full" onClick={() => setShowModal(false)}>Cancel</button>
          </div>
        </div>,
        document.body
      )}
    </>
  )
}
