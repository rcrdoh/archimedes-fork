// Circle Modular Wallets SDK integration — passkey-based smart contract
// accounts (MSCA) on Arc Testnet. Works in any modern browser (Safari,
// Chrome, Firefox) since it uses the standard WebAuthn API instead of an
// injected wallet extension.
//
// Two flows:
//   - Register: first-time user creates a P256 credential on their device
//     (Face ID / Touch ID / Windows Hello / hardware key). The MSCA is
//     derived deterministically from the public key.
//   - Login: returning user re-authenticates with the same credential to
//     unlock the same MSCA address.
//
// MSCAs are LAZILY DEPLOYED — gas for account creation is deferred until
// the first outbound user operation. The Arc Testnet path is `/arcTestnet`.
//
// Reference: submodules/context-arc/docs/circlefin-skills/use-modular-wallets.md
// Setup: ui/.env.example documents VITE_CIRCLE_CLIENT_KEY + VITE_CIRCLE_CLIENT_URL.

import { createPublicClient } from 'viem'
import { toWebAuthnAccount } from 'viem/account-abstraction'
import {
  toWebAuthnCredential,
  toPasskeyTransport,
  toModularTransport,
  toCircleSmartAccount,
  WebAuthnMode,
} from '@circle-fin/modular-wallets-core'

const CLIENT_KEY = import.meta.env.VITE_CIRCLE_CLIENT_KEY ?? ''
const CLIENT_URL = import.meta.env.VITE_CIRCLE_CLIENT_URL
  ?? 'https://modular-sdk.circle.com/v1/rpc/w3s/buidl'

// Arc Testnet chain definition; matches the EOA-path chain in config.js so
// any downstream code that introspects .chain sees the same object shape.
const arcTestnet = {
  id: 5042002,
  name: 'Arc Testnet',
  nativeCurrency: { name: 'USD Coin', symbol: 'USDC', decimals: 18 },
  rpcUrls: { default: { http: ['https://rpc.testnet.arc.network'] } },
}

// Demo-grade persistence. Per Circle docs, production should use httpOnly
// cookies to mitigate XSS credential theft — out of scope for hackathon demo.
const CREDENTIAL_STORAGE_KEY = 'archimedes_circle_credential'

// True if a CLIENT_KEY was supplied at build time. The modal hides the
// passkey option when this is false so we never show a broken button.
export function circlePasskeyEnabled() {
  return Boolean(CLIENT_KEY)
}

function loadStoredCredential() {
  try {
    const raw = localStorage.getItem(CREDENTIAL_STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function saveCredential(credential) {
  try {
    localStorage.setItem(CREDENTIAL_STORAGE_KEY, JSON.stringify(credential))
  } catch { /* storage unavailable */ }
}

export function clearCircleSession() {
  try { localStorage.removeItem(CREDENTIAL_STORAGE_KEY) } catch { /* */ }
}

// Returns true if a previously-registered passkey is on file for this
// origin. Cheap synchronous check used to decide whether the modal should
// show "Sign in with Passkey" (returning) vs "Create Passkey" (new user).
export function hasStoredPasskey() {
  return loadStoredCredential() !== null
}

// Single entry point for both flows. The caller passes `mode = 'register'`
// for a new user; we default to 'login' if we already have a stored
// credential. Returns the smart account + its address + the credential
// (also persisted to localStorage for next-session re-login).
//
// Throws standard WebAuthn DOMException errors on user cancellation
// (NotAllowedError) or domain mismatch (SecurityError) — caller should
// catch and surface a friendly message.
export async function connectCirclePasskey({ mode = 'auto', username = 'Archimedes user' } = {}) {
  if (!circlePasskeyEnabled()) {
    throw new Error('Circle passkey wallet is not configured (missing VITE_CIRCLE_CLIENT_KEY).')
  }

  const stored = loadStoredCredential()
  const resolvedMode = mode === 'auto'
    ? (stored ? WebAuthnMode.Login : WebAuthnMode.Register)
    : (mode === 'login' ? WebAuthnMode.Login : WebAuthnMode.Register)

  // Passkey transport handles WebAuthn challenge issuance + verification.
  const passkeyTransport = toPasskeyTransport(CLIENT_URL, CLIENT_KEY)

  // Either issue a new P256 credential (Register) OR re-authenticate an
  // existing one (Login). Browser prompts the user for biometrics here.
  const credential = await toWebAuthnCredential({
    transport: passkeyTransport,
    mode: resolvedMode,
    username,
    credentialId: resolvedMode === WebAuthnMode.Login ? stored?.id : undefined,
  })

  // Persist for next-session login. Stores the credential ID + public key,
  // NOT the private key (the private key lives in the device's secure
  // enclave and never leaves it).
  saveCredential(credential)

  // Modular transport handles bundler RPC + chain-specific calls for the
  // smart account on Arc Testnet.
  const modularTransport = toModularTransport(`${CLIENT_URL}/arcTestnet`, CLIENT_KEY)
  const client = createPublicClient({ chain: arcTestnet, transport: modularTransport })

  // Derive a WebAuthnAccount viem account from the credential, then turn
  // it into a Circle smart account. The MSCA address is deterministic
  // from the credential's public key — same passkey → same address.
  const owner = toWebAuthnAccount({ credential })
  const smartAccount = await toCircleSmartAccount({ client, owner })

  return {
    address: smartAccount.address,
    smartAccount,
    client,
    credential,
    mode: resolvedMode,
  }
}

// Rebuild the smart account from a previously-stored credential WITHOUT
// triggering a WebAuthn prompt. Safe to call on every page load — the
// credential only contains the public key (the private key lives in the
// device's secure enclave) so we can derive the smart account address
// + signer wrapper without re-authenticating. The user only sees a
// WebAuthn prompt when they actually try to sign a user operation.
//
// Returns null if there's no stored credential (caller should redirect
// to the register flow).
export async function rehydrateSmartAccount() {
  if (!circlePasskeyEnabled()) return null
  const credential = loadStoredCredential()
  if (!credential) return null

  const modularTransport = toModularTransport(`${CLIENT_URL}/arcTestnet`, CLIENT_KEY)
  const client = createPublicClient({ chain: arcTestnet, transport: modularTransport })

  const owner = toWebAuthnAccount({ credential })
  const smartAccount = await toCircleSmartAccount({ client, owner })

  return {
    address: smartAccount.address,
    smartAccount,
    client,
    credential,
  }
}
