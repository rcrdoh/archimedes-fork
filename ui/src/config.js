import { createPublicClient, createWalletClient, custom, http } from 'viem'
import {
  connectCirclePasskey,
  clearCircleSession,
  circlePasskeyEnabled,
  rehydrateSmartAccount,
} from './circle-wallet'

const arcTestnet = {
  id: 5042002,
  name: 'Arc Testnet',
  nativeCurrency: { name: 'USD Coin', symbol: 'USDC', decimals: 18 },
  rpcUrls: { default: { http: ['https://rpc.testnet.arc.network'] } },
}

export const publicClient = createPublicClient({
  chain: arcTestnet,
  transport: http(),
})

// ─── Wallet Connection ──────────────────────────────────────
//
// Discovery follows EIP-6963 (Multi Injected Provider Discovery) when the
// wallet supports it; falls back to legacy window.ethereum sniffing for
// older wallets. EIP-6963 is the modern standard — newer Coinbase Wallet,
// Rabby, Brave, Phantom EVM, etc. only announce themselves this way.
// Reference: https://eips.ethereum.org/EIPS/eip-6963

// Keyed by rdns (reverse-DNS identifier the wallet self-declares).
const eip6963Providers = new Map()

if (typeof window !== 'undefined') {
  window.addEventListener('eip6963:announceProvider', (event) => {
    const detail = event.detail
    if (detail?.info?.rdns && detail?.provider) {
      eip6963Providers.set(detail.info.rdns, detail)
    }
  })
  // Ask wallets that loaded before this listener was attached to re-announce.
  window.dispatchEvent(new Event('eip6963:requestProvider'))
}

// Known wallets we ship icons + curated names for. Any EIP-6963 wallet not in
// this list still surfaces via discoverEip6963Wallets() with the wallet's own
// self-declared name + icon.
const KNOWN_WALLET_RDNS = {
  metamask: ['io.metamask', 'io.metamask.flask'],
  coinbase: ['com.coinbase.wallet'],
}

function findEip6963Provider(rdnsList) {
  for (const rdns of rdnsList) {
    const entry = eip6963Providers.get(rdns)
    if (entry) return entry.provider
  }
  return null
}

export const WALLET_PROVIDERS = [
  {
    id: 'metamask',
    name: 'MetaMask',
    icon: 'i-token-branded-metamask',
    detect: () => {
      // EIP-6963 first (modern MetaMask)
      const announced = findEip6963Provider(KNOWN_WALLET_RDNS.metamask)
      if (announced) return announced
      // Legacy: window.ethereum.isMetaMask
      if (!window.ethereum) return null
      if (window.ethereum.isMetaMask) return window.ethereum
      // Multi-provider legacy
      if (window.ethereum.providers?.find(p => p.isMetaMask)) {
        return window.ethereum.providers.find(p => p.isMetaMask)
      }
      return null
    },
  },
  {
    id: 'coinbase',
    name: 'Coinbase Wallet',
    icon: 'i-simple-icons-coinbase',
    detect: () => {
      // EIP-6963 first (modern Coinbase Wallet extension)
      const announced = findEip6963Provider(KNOWN_WALLET_RDNS.coinbase)
      if (announced) return announced
      // Legacy patterns (older versions)
      if (window.ethereum?.isCoinbaseWallet) return window.ethereum
      if (window.coinbaseWalletExtension) return window.coinbaseWalletExtension
      if (window.ethereum?.providers?.find(p => p.isCoinbaseWallet)) {
        return window.ethereum.providers.find(p => p.isCoinbaseWallet)
      }
      return null
    },
  },
  {
    id: 'browser',
    name: 'Browser Wallet',
    icon: 'i-lucide-globe',
    detect: () => {
      // Fallback: any window.ethereum provider not already covered.
      return window.ethereum || null
    },
  },
]

// Returns EIP-6963 wallets that aren't in our curated WALLET_PROVIDERS list —
// e.g. Rabby, Brave, Phantom EVM. Each entry shape matches WALLET_PROVIDERS so
// the modal can render them with the wallet's self-declared name + icon.
export function discoverEip6963Wallets() {
  const knownRdns = new Set(Object.values(KNOWN_WALLET_RDNS).flat())
  const wallets = []
  for (const [rdns, entry] of eip6963Providers) {
    if (knownRdns.has(rdns)) continue
    wallets.push({
      id: `eip6963:${rdns}`,
      name: entry.info.name || rdns,
      // Wallet self-declared base64 data URI (per EIP-6963); render directly
      // in <img src=...>. We pass `iconDataUri` instead of `icon` so the
      // modal can branch on which to render.
      iconDataUri: entry.info.icon || null,
      icon: 'i-lucide-wallet',
      detect: () => entry.provider,
    })
  }
  return wallets
}

const STORAGE_KEY = 'archimedes_wallet'

// Synthetic provider id for the Circle Modular Wallets path. Distinct from
// the EOA paths (metamask / coinbase / eip6963:*) so connectWallet() +
// reconnectWallet() can branch cleanly. The MSCA path has no EIP-1193
// provider and no viem WalletClient — txs go through bundler.sendUserOperation
// (Phase 2.5 follow-up); for this PR we surface the MSCA address only.
export const CIRCLE_PROVIDER_ID = 'circle-passkey'

let _walletClient = null
let _provider = null
let _address = null
let _providerId = null
let _smartAccount = null      // populated for the Circle path; null for EOA paths
let _smartAccountClient = null // Circle modular-transport viem client (for bundler)

export function getConnectedProvider() { return _providerId }
export function getAddress() { return _address }
// Returns the Circle smart account when connected via passkey, else null.
// Phase 2.5 uses this to wrap deposit calls in sendUserOperation.
export function getSmartAccount() { return _smartAccount }
// Returns the modular-transport public client paired with the smart
// account — required for createBundlerClient. Null for EOA paths.
export function getSmartAccountClient() { return _smartAccountClient }

function saveWalletMeta(providerId, address) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ providerId, address }))
  } catch { /* storage unavailable */ }
}

function clearWalletMeta() {
  try { localStorage.removeItem(STORAGE_KEY) } catch { /* */ }
}

function loadWalletMeta() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

// Try to reconnect to a previously connected wallet on page load.
// Uses eth_accounts (non-popup) for EOA wallets to check if the user is
// still authorised. For Circle passkey wallets we DO NOT auto-trigger
// a WebAuthn prompt on page load (would spam users); we restore the
// address from localStorage only, and the smart-account object is
// lazily re-hydrated on the first tx via a fresh login flow.
export async function reconnectWallet() {
  const meta = loadWalletMeta()
  if (!meta) return null

  // Circle passkey path: rebuild the smart account from the stored
  // credential without triggering a WebAuthn prompt. The credential
  // only holds the public key (private key stays in the device's
  // secure enclave), so we can derive the address + signer wrapper
  // silently. Prompt only happens when the user actually signs a
  // user operation later.
  if (meta.providerId === CIRCLE_PROVIDER_ID) {
    if (!circlePasskeyEnabled()) { clearWalletMeta(); return null }
    try {
      const restored = await rehydrateSmartAccount()
      if (!restored) { clearWalletMeta(); return null }
      _address = restored.address
      _providerId = CIRCLE_PROVIDER_ID
      _provider = null
      _walletClient = null
      _smartAccount = restored.smartAccount
      _smartAccountClient = restored.client
      saveWalletMeta(CIRCLE_PROVIDER_ID, _address)
      return { address: _address, provider: _providerId }
    } catch {
      // If rehydration fails (corrupted credential, SDK error, etc.)
      // fall back gracefully — user can re-connect manually.
      clearWalletMeta()
      return null
    }
  }

  const provider = findWalletProvider(meta.providerId)
  if (!provider) { clearWalletMeta(); return null }

  const ethereum = provider.detect()
  if (!ethereum) { clearWalletMeta(); return null }

  try {
    const accounts = await ethereum.request({ method: 'eth_accounts' })
    if (!accounts?.length) { clearWalletMeta(); return null }

    const addr = accounts[0]
    await ensureArcChain(ethereum)

    _provider = ethereum
    _address = addr
    _providerId = meta.providerId
    _walletClient = createWalletClient({
      account: _address,
      chain: arcTestnet,
      transport: custom(ethereum),
    })

    saveWalletMeta(_providerId, _address)
    return { address: _address, provider: _providerId }
  } catch {
    clearWalletMeta()
    return null
  }
}

const ARC_CHAIN_HEX = '0x4cef52'  // 5042002

// MetaMask returns -32002 when a wallet_requestPermissions / eth_requestAccounts
// is already pending — usually because the user dismissed the popup without
// confirming, leaving the request live. Turn this into an actionable message
// instead of bubbling the raw RPC error.
function isAlreadyPendingError(err) {
  return err?.code === -32002
}

async function ensureArcChain(ethereum) {
  // Skip the switch popup if we're already on Arc.
  try {
    const current = await ethereum.request({ method: 'eth_chainId' })
    if (current?.toLowerCase() === ARC_CHAIN_HEX) return
  } catch { /* fall through to switch */ }

  try {
    await ethereum.request({
      method: 'wallet_switchEthereumChain',
      params: [{ chainId: ARC_CHAIN_HEX }],
    })
  } catch (switchError) {
    if (switchError.code === 4902) {
      await ethereum.request({
        method: 'wallet_addEthereumChain',
        params: [{
          chainId: ARC_CHAIN_HEX,
          chainName: 'Arc Testnet',
          nativeCurrency: { name: 'USD Coin', symbol: 'USDC', decimals: 18 },
          rpcUrls: ['https://rpc.testnet.arc.network'],
          blockExplorerUrls: [],
        }],
      })
    } else if (isAlreadyPendingError(switchError)) {
      throw new Error(
        'A wallet request is already open — check your MetaMask extension popup, then try again.',
        { cause: switchError },
      )
    } else {
      throw switchError
    }
  }
}

// Resolve any provider id (curated WALLET_PROVIDERS *or* a dynamic
// `eip6963:<rdns>` id surfaced via discoverEip6963Wallets()).
function findWalletProvider(providerId) {
  const curated = WALLET_PROVIDERS.find(p => p.id === providerId)
  if (curated) return curated
  if (providerId?.startsWith('eip6963:')) {
    return discoverEip6963Wallets().find(p => p.id === providerId) || null
  }
  return null
}

// Connect via Circle Modular Wallets passkey. Returns the same shape as
// connectWallet() so the WalletConnect onConnect callback works
// uniformly. Triggers a WebAuthn prompt (biometric / hardware key) for
// the user — caller should debounce + show a "Authenticating..." state.
export async function connectCircleWallet() {
  if (!circlePasskeyEnabled()) {
    throw new Error('Circle passkey wallet is not configured.')
  }
  const result = await connectCirclePasskey({ mode: 'auto' })
  _address = result.address
  _providerId = CIRCLE_PROVIDER_ID
  _provider = null
  _walletClient = null
  _smartAccount = result.smartAccount
  _smartAccountClient = result.client
  saveWalletMeta(CIRCLE_PROVIDER_ID, _address)
  return { address: _address, provider: CIRCLE_PROVIDER_ID }
}

export async function connectWallet(providerId) {
  if (providerId === CIRCLE_PROVIDER_ID) return connectCircleWallet()

  const provider = findWalletProvider(providerId)
  if (!provider) throw new Error(`Unknown provider: ${providerId}`)

  const ethereum = provider.detect()
  if (!ethereum) throw new Error(`${provider.name} not detected. Please install the extension.`)

  let accounts
  try {
    accounts = await ethereum.request({ method: 'eth_requestAccounts' })
  } catch (err) {
    if (isAlreadyPendingError(err)) {
      throw new Error(
        'A wallet request is already open — check your MetaMask extension popup, then try again.',
        { cause: err },
      )
    }
    if (err?.code === 4001) {
      throw new Error(
        'Connection rejected — approve the request in MetaMask to continue.',
        { cause: err },
      )
    }
    throw err
  }
  if (!accounts?.length) throw new Error('No accounts returned from wallet.')

  await ensureArcChain(ethereum)

  _provider = ethereum
  _address = accounts[0]
  _providerId = providerId
  _walletClient = createWalletClient({
    account: _address,
    chain: arcTestnet,
    transport: custom(ethereum),
  })

  saveWalletMeta(providerId, _address)
  return { address: _address, provider: providerId }
}

export function disconnectWallet() {
  // If we were connected via passkey, also clear the stored P256
  // credential so the next connect starts a fresh register flow.
  if (_providerId === CIRCLE_PROVIDER_ID) clearCircleSession()
  _walletClient = null
  _provider = null
  _address = null
  _providerId = null
  _smartAccount = null
  _smartAccountClient = null
  clearWalletMeta()
}

export async function getWalletClient() {
  if (_walletClient) return _walletClient
  if (_providerId === CIRCLE_PROVIDER_ID) {
    // Passkey wallets sign via Circle's bundler (executeUserOp), not viem
    // writeContract — callers should branch on getConnectedProvider() and
    // use the executor for that path. This error fires only if a code path
    // forgot to branch.
    throw new Error(
      'This action is not yet wired for passkey wallets. ' +
      'The deposit flow uses Circle bundler execution; other flows still need that wrapper.',
    )
  }
  throw new Error('No wallet connected. Click "Connect Wallet" to continue.')
}

// Returns all wallet providers detected in the page — curated WALLET_PROVIDERS
// that pass their detect(), plus any EIP-6963 wallet the dApp doesn't have a
// curated entry for (Rabby, Brave, Phantom EVM, etc.). The Circle passkey
// option is included whenever VITE_CIRCLE_CLIENT_KEY is set — it requires no
// extension, just WebAuthn support, so it shows up in every browser.
export function getAvailableProviders() {
  const curated = WALLET_PROVIDERS.filter(p => p.detect() !== null)
  const discovered = discoverEip6963Wallets()
  // Drop the generic 'browser' fallback if a real EIP-6963 wallet is present —
  // the generic option exists for users who only have window.ethereum injected
  // without identifying itself, which is exactly what EIP-6963 fixes.
  const hasReal = curated.some(p => p.id !== 'browser') || discovered.length > 0
  const filtered = hasReal ? curated.filter(p => p.id !== 'browser') : curated
  const passkey = circlePasskeyEnabled()
    ? [{
        id: CIRCLE_PROVIDER_ID,
        name: 'Sign in with Passkey',
        icon: 'i-lucide-fingerprint',
        // Synthetic provider — no EIP-1193 detect; presence is implied by
        // circlePasskeyEnabled() being true.
        detect: () => true,
      }]
    : []
  return [...passkey, ...filtered, ...discovered]
}

// Listen for account/chain changes from the wallet extension
if (typeof window !== 'undefined' && window.ethereum) {
  window.ethereum.on?.('accountsChanged', (accounts) => {
    if (!accounts?.length) {
      disconnectWallet()
      window.dispatchEvent(new CustomEvent('wallet-changed', { detail: { address: null } }))
    } else {
      _address = accounts[0]
      if (_providerId) saveWalletMeta(_providerId, _address)
      if (_provider) {
        _walletClient = createWalletClient({
          account: _address,
          chain: arcTestnet,
          transport: custom(_provider),
        })
      }
      window.dispatchEvent(new CustomEvent('wallet-changed', { detail: { address: _address } }))
    }
  })
  window.ethereum.on?.('chainChanged', () => {
    window.location.reload()
  })
}

// ─── ABIs (minimal, just what we need) ──────────────────────

export const ORACLE_ABI = [
  { name: 'price',       type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { name: 'symbol',      type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'string'  }] },
  { name: 'lastUpdated', type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { name: 'isFresh',     type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'bool'    }] },
  { name: 'setPrice',    type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'uint256', name: '_newPrice' }], outputs: [] },
]

export const TOKEN_ABI = [
  { name: 'totalSupply',   type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { name: 'balanceOf',     type: 'function', stateMutability: 'view', inputs: [{ type: 'address' }], outputs: [{ type: 'uint256' }] },
  { name: 'approve',       type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'address' }, { type: 'uint256' }], outputs: [{ type: 'bool' }] },
  { name: 'allowance',     type: 'function', stateMutability: 'view', inputs: [{ type: 'address' }, { type: 'address' }], outputs: [{ type: 'uint256' }] },
  { name: 'symbol',        type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'string' }] },
  { name: 'decimals',      type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint8' }] },
]

// Minimal ABI for USDC approve/allowance — used by DepositFlow stepper.
// Same as TOKEN_ABI but scoped to the two functions needed for the deposit flow.
export const USDC_ABI = [
  { name: 'approve',       type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'address', name: 'spender' }, { type: 'uint256', name: 'amount' }], outputs: [{ type: 'bool' }] },
  { name: 'allowance',     type: 'function', stateMutability: 'view', inputs: [{ type: 'address', name: 'owner' }, { type: 'address', name: 'spender' }], outputs: [{ type: 'uint256' }] },
]

export const SYNTH_VAULT_ABI = [
  { name: 'mint',                type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'uint256', name: 'amountUsdc' }], outputs: [{ type: 'uint256' }] },
  { name: 'burn',                type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'uint256', name: 'synthAmount' }], outputs: [{ type: 'uint256' }] },
  { name: 'previewMint',         type: 'function', stateMutability: 'view', inputs: [{ type: 'uint256' }], outputs: [{ type: 'uint256' }] },
  { name: 'previewBurn',         type: 'function', stateMutability: 'view', inputs: [{ type: 'uint256' }], outputs: [{ type: 'uint256' }] },
  { name: 'totalCollateral',     type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { name: 'vaultCollateralization', type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
]

export const AMM_ROUTER_ABI = [
  { name: 'createPool',    type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'address' }, { type: 'address' }], outputs: [{ type: 'address' }] },
  { name: 'getPool',       type: 'function', stateMutability: 'view', inputs: [{ type: 'address' }, { type: 'address' }], outputs: [{ type: 'address' }] },
  { name: 'getAllPools',   type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'address[]' }] },
  { name: 'swap',          type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'address' }, { type: 'address' }, { type: 'uint256' }, { type: 'uint256' }], outputs: [{ type: 'uint256' }] },
  { name: 'getAmountOut',  type: 'function', stateMutability: 'view', inputs: [{ type: 'address' }, { type: 'address' }, { type: 'uint256' }], outputs: [{ type: 'uint256' }] },
  { name: 'addLiquidity',  type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'address' }, { type: 'address' }, { type: 'uint256' }, { type: 'uint256' }, { type: 'uint256' }], outputs: [{ type: 'uint256' }] },
]

export const TRACE_REGISTRY_ABI = [
  { name: 'publishTrace',   type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'address' }, { type: 'bytes32' }, { type: 'bytes' }], outputs: [{ type: 'uint256' }] },
  { name: 'verifyTrace',    type: 'function', stateMutability: 'view', inputs: [{ type: 'uint256' }, { type: 'bytes' }], outputs: [{ type: 'bool' }] },
  { name: 'traceCount',     type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { name: 'getTracesByVault', type: 'function', stateMutability: 'view', inputs: [{ type: 'address' }], outputs: [{ type: 'uint256[]' }] },
  { name: 'getTraceById',   type: 'function', stateMutability: 'view', inputs: [{ type: 'uint256' }], outputs: [{ type: 'address', name: 'agent' }, { type: 'address', name: 'vault' }, { type: 'bytes32', name: 'traceHash' }, { type: 'uint256', name: 'timestamp' }, { type: 'bytes', name: 'metadata' }] },
]

export const ASSET_REGISTRY_ABI = [
  { name: 'getAllSynthetics', type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'address[]' }] },
  { name: 'vaultCount',       type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { name: 'getLeaderboard',   type: 'function', stateMutability: 'view', inputs: [{ type: 'uint8' }, { type: 'uint256' }], outputs: [{ type: 'address[]' }] },
]

export const VAULT_ABI = [
  { name: 'deposit',             type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'uint256' }, { type: 'address' }], outputs: [{ type: 'uint256' }] },
  { name: 'withdraw',            type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'uint256' }, { type: 'address' }, { type: 'address' }], outputs: [{ type: 'uint256' }] },
  { name: 'totalAssets',         type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { name: 'totalSupply',         type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { name: 'balanceOf',           type: 'function', stateMutability: 'view', inputs: [{ type: 'address' }], outputs: [{ type: 'uint256' }] },
  { name: 'getHoldings',         type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'address[]' }, { type: 'uint256[]' }] },
  { name: 'creator',             type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'address' }] },
  { name: 'tier',                type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint8' }] },
  { name: 'paused',              type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'bool' }] },
  { name: 'highWaterMark',       type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { name: 'asset',               type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'address' }] },
  { name: 'approve',             type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'address' }, { type: 'uint256' }], outputs: [{ type: 'bool' }] },
  { name: 'name',                type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'string' }] },
  { name: 'symbol',              type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'string' }] },
  { name: 'managementFeeBps',    type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint16' }] },
  { name: 'performanceFeeBps',   type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint16' }] },
  { name: 'setTargetAllocations', type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'address[]', name: 'tokens' }, { type: 'uint256[]', name: 'weightsBps' }], outputs: [] },
  { name: 'getTargetAllocations', type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'address[]' }, { type: 'uint256[]' }] },
  { name: 'setTokenOracles', type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'address[]', name: 'tokens' }, { type: 'address[]', name: 'oracles' }], outputs: [] },
  { name: 'tokenOracle', type: 'function', stateMutability: 'view', inputs: [{ type: 'address' }], outputs: [{ type: 'address' }] },
]

export const VAULT_FACTORY_ABI = [
  { name: 'createVault',    type: 'function', stateMutability: 'nonpayable', inputs: [{ type: 'string' }, { type: 'string' }, { type: 'uint16' }, { type: 'uint16' }, { type: 'bool' }], outputs: [{ type: 'address' }] },
  { name: 'getVaults',      type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'address[]' }] },
  { name: 'vaultCount',     type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'uint256' }] },
  { name: 'agentAddress',   type: 'function', stateMutability: 'view', inputs: [], outputs: [{ type: 'address' }] },
  { name: 'getVaultsByCreator', type: 'function', stateMutability: 'view', inputs: [{ type: 'address' }], outputs: [{ type: 'address[]' }] },
  // VaultCreated event — used to extract new vault address from receipt
  { name: 'VaultCreated',   type: 'event', inputs: [
    { name: 'vault',   type: 'address', indexed: true },
    { name: 'creator', type: 'address', indexed: true },
    { name: 'name',    type: 'string',  indexed: false },
    { name: 'symbol',  type: 'string',  indexed: false },
    { name: 'tier',    type: 'uint8',   indexed: false },
  ]},
]

// ─── Deployed addresses from .env ────────────────────────────

export const USDC = "0x3600000000000000000000000000000000000000"

export const ASSETS = [
  { id: 'TSLA',   name: 'Tesla',      sym: 'sTSLA',   icon: 'i-simple-icons-tesla',          oracle: '0xe1c9f2b11be97097223a66a188fca541e07873a6', vault: '0xf0356600e26c6c403ec4f5b36b0e3380bb0609ab', token: '0xd514cd27baf762c650536765cde9b61c876abacd' },
  { id: 'NVDA',   name: 'Nvidia',     sym: 'sNVDA',   icon: 'i-simple-icons-nvidia',          oracle: '0xeb36acf88e739dd312de8278985262146a017374', vault: '0x4c3cdc2bf44195ad8a4d201c8afbd453949a8781', token: '0x805e75019a1291a598dfc134ad2519121a35fb11' },
  { id: 'SPY',    name: 'S&P 500',    sym: 'sSPY',    icon: 'i-lucide-trending-up',           oracle: '0xd8161a8eeab7c7100e2863abe3d5f346b5ff9e52', vault: '0xd8d7855f76c384638cf1dfc3575ecff3538764b4', token: '0x6fea38dedea0c6bb66ce93e5383c34385d8b889f' },
  { id: 'BTC',    name: 'Bitcoin',    sym: 'sBTC',    icon: 'i-cryptocurrency-color-btc',     oracle: '0x6cc5f621c4e3b46152e69e5c9873689cbb4a85e8', vault: '0x92990ed6f5c8cd72752ca9aeafad422269225c43', token: '0x317e82be8f7cba6c162ab968fcf695d88e8e0359' },
  { id: 'GOLD',   name: 'Gold ETF',   sym: 'sGOLD',   icon: 'i-lucide-coins',                 oracle: '0x35fccde01ae8728c7a7cb83c3f59c701ebecc633', vault: '0x124b5c5da57d209b28d4997aaf6d4e96711efd5a', token: '0xf384562c8bdafce52400eb6839f195695f6fa276' },
  { id: 'OIL',    name: 'Oil ETF',    sym: 'sOIL',    icon: 'i-lucide-fuel',                  oracle: '0x79f354524fd09af16d841a2221af2b2b7bc432c8', vault: '0xfa942399e36959c8060c3a82a610d680a7ac6d22', token: '0x46cead4120f17a968ba1168f1a56563962cf3c4b' },
  { id: 'NIKKEI', name: 'Nikkei ETF', sym: 'sNKY',    icon: 'i-lucide-bar-chart-2',           oracle: '0xcd34a4103ad64a3cf729b1b1a58295ccc957fcee', vault: '0xb26029ca37c09400ca921f00fc541cd42143b508', token: '0x445b8f0f827a0d384d1b8ccf18cbc6ec8a543376' },
]

// New contract addresses — set these after deploying via deploy-new.mjs
export const NEW_CONTRACTS = {
  ammRouter:       '0x090f8E245F2831b81c9ff21661FBd0cb1383f82D',
  vaultFactory:    '0x32A3e0D0a8215D77e3B92fa6d9b4Dbe19f255671',
  traceRegistry:   '0x44bD55c0DdF757e584a41fb7F3B6a47b4C5982ba',
  assetRegistry:   '0x79fc95A10E8240116006084439B650BA9e72F3cA',
}
