// Bundler-based transaction executor for Circle Modular Wallets.
//
// EOA wallets sign each tx individually via viem.writeContract; the user
// sees N wallet popups for N calls. Smart accounts sign ONE user operation
// containing N batched calls — single biometric prompt for the whole
// sequence, gas sponsored by Circle Gas Station (paymaster: true).
//
// Reference: submodules/context-arc/docs/circlefin-skills/use-modular-wallets.md
// SDK: viem/account-abstraction createBundlerClient + sendUserOperation

import { createBundlerClient } from 'viem/account-abstraction'
import { encodeFunctionData } from 'viem'
import { toModularTransport } from '@circle-fin/modular-wallets-core'

const CLIENT_KEY = import.meta.env.VITE_CIRCLE_CLIENT_KEY ?? ''
const CLIENT_URL = import.meta.env.VITE_CIRCLE_CLIENT_URL
  ?? 'https://modular-sdk.circle.com/v1/rpc/w3s/buidl'

// Build a fresh bundler client for the given smart account. Cheap to make
// (just wires up the transport + paymaster config) so we don't bother
// caching — the smart account itself is what holds the heavy state.
function makeBundlerClient(smartAccount, client) {
  const transport = toModularTransport(`${CLIENT_URL}/arcTestnet`, CLIENT_KEY)
  return createBundlerClient({
    account: smartAccount,
    client,
    // paymaster: true tells the bundler to request gas sponsorship from
    // Circle Gas Station. On testnet this is typically free / automatic.
    // On mainnet a Gas Station policy must be configured in Circle Console
    // first — sendUserOperation will return error 155509 if it's not.
    paymaster: true,
    transport,
  })
}

// Map a chain-call descriptor (the same shape viem.writeContract takes) to
// the raw {to, data, value} a user operation needs. Lets DepositFlow keep
// its existing ABI imports + readable call site.
export function encodeCall({ address, abi, functionName, args, value = 0n }) {
  return {
    to: address,
    data: encodeFunctionData({ abi, functionName, args }),
    value,
  }
}

// Translate Circle's numeric error codes into user-actionable messages.
// Falls back to the raw error.message when nothing matches so the user
// always sees *something* useful.
function friendlyError(err) {
  const code = err?.code ?? err?.cause?.code
  const map = {
    155203: 'First transaction from this passkey wallet — please retry; the smart account is deploying.',
    155505: 'Smart account is still deploying from the prior transaction. Wait a moment and retry.',
    155507: 'Smart accounts are not supported on this chain. Switch to Arc Testnet.',
    155509: 'Gas sponsorship is not configured for this network. Contact the operator.',
    155512: 'Passkey owner could not be verified. Try disconnecting and reconnecting.',
    AA21: 'Gas sponsorship failed. The transaction would require you to pay gas, which is not supported for passkey wallets.',
    AA23: 'Passkey signature was rejected by the smart account. Try disconnecting and reconnecting.',
    AA25: 'Transaction nonce mismatch. Refresh the page and retry.',
    AA33: 'Gas sponsorship was rejected. The operator may need to update the paymaster policy.',
  }
  if (code && map[code]) return map[code]
  if (err?.name === 'NotAllowedError') return 'You cancelled the passkey prompt. Click again to retry.'
  if (err?.name === 'SecurityError') return 'Passkey domain mismatch — this passkey was registered on a different domain.'
  return err?.shortMessage || err?.message || 'Transaction failed.'
}

// Execute one or more contract calls as a single batched user operation.
// Returns { userOpHash, receipt, txHash } on success; throws on failure.
//
// onStateChange is an optional callback invoked at lifecycle transitions
// (SENT / CONFIRMED / COMPLETE) so callers can update UI feedback.
export async function executeUserOp({ smartAccount, client, calls, onStateChange }) {
  if (!smartAccount) throw new Error('Smart account is not initialized.')
  if (!calls?.length) throw new Error('At least one call is required.')

  const bundler = makeBundlerClient(smartAccount, client)

  let userOpHash
  try {
    onStateChange?.('SIGNING')
    userOpHash = await bundler.sendUserOperation({ calls })
    onStateChange?.('SENT')
  } catch (err) {
    throw new Error(friendlyError(err), { cause: err })
  }

  let receipt
  try {
    receipt = await bundler.waitForUserOperationReceipt({ hash: userOpHash })
    onStateChange?.(receipt.success ? 'COMPLETE' : 'FAILED')
  } catch (err) {
    throw new Error(friendlyError(err), { cause: err })
  }

  if (!receipt.success) {
    throw new Error(
      'User operation reverted on-chain. ' +
      `Reason: ${receipt.reason || 'unknown'}. Tx: ${receipt.receipt?.transactionHash || 'n/a'}`,
    )
  }

  return {
    userOpHash,
    receipt,
    // The actual on-chain tx that included this user op — what arcscan
    // shows. Distinct from userOpHash (which is bundler-internal).
    txHash: receipt.receipt?.transactionHash,
  }
}
