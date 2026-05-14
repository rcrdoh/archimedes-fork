// seed-liquidity.mjs
//
// Mints synthetic tokens and adds liquidity to all AMM pools.
// Uses the Circle developer wallet to fund the pools.
//
// Usage: node --env-file=../.env seed-liquidity.mjs

import crypto from "crypto";
import fs from "fs";
import path from "path";

const API_KEY = process.env.CIRCLE_API_KEY;
const ENTITY_SECRET = process.env.CIRCLE_ENTITY_SECRET;
const WALLET_ID = process.env.WALLET_ID;
const WALLET_ADDRESS = process.env.WALLET_ADDRESS;
const API = "https://api.circle.com/v1/w3s";

if (!API_KEY || !ENTITY_SECRET || !WALLET_ID || !WALLET_ADDRESS) {
  console.error("ERROR: Need CIRCLE_API_KEY, CIRCLE_ENTITY_SECRET, WALLET_ID, WALLET_ADDRESS");
  process.exit(1);
}

const USDC = "0x3600000000000000000000000000000000000000";

// Load deployed addresses from .env
const envPath = path.resolve(import.meta.dirname, "../.env");
const envContent = fs.readFileSync(envPath, "utf8");
function getEnv(key) {
  const m = envContent.match(new RegExp(`${key}=(.*)`, "m"));
  return m ? m[1].trim() : null;
}

const AMM_ROUTER = getEnv("AMM_ROUTER");
if (!AMM_ROUTER) {
  console.error("AMM_ROUTER not found in .env. Run deploy-new.mjs first.");
  process.exit(1);
}

const ASSETS = [
  { id: "TSLA",   env: "TSLA",   mintAmount: "3000000",     liqToken: "3000000000000000" },       // 3 USDC, ~6.7 synth
  { id: "NVDA",   env: "NVDA",   mintAmount: "3000000",     liqToken: "6000000000000000" },
  { id: "SPY",    env: "SPY",    mintAmount: "3000000",     liqToken: "2000000000000000" },
  { id: "BTC",    env: "BTC",    mintAmount: "3000000",     liqToken: "20000000000000" },
  { id: "GOLD",   env: "GOLD",   mintAmount: "3000000",     liqToken: "2000000000000000" },
  { id: "OIL",    env: "OIL",    mintAmount: "3000000",     liqToken: "10000000000000000" },
  { id: "NIKKEI", env: "NIKKEI", mintAmount: "3000000",     liqToken: "10000000000000000" },
];

// ─── Helpers ────────────────────────────────────────────────

let ciphertextCache = null;

async function getCiphertext() {
  if (ciphertextCache) return ciphertextCache;
  const pkRes = await fetch(`${API}/config/entity/publicKey`, {
    headers: { Authorization: `Bearer ${API_KEY}`, Accept: "application/json" },
  });
  const { data } = await pkRes.json();
  const pub = crypto.createPublicKey({ key: data.publicKey, format: "pem" });
  ciphertextCache = crypto.publicEncrypt(
    { key: pub, padding: crypto.constants.RSA_PKCS1_OAEP_PADDING, oaepHash: "sha256" },
    Buffer.from(ENTITY_SECRET, "hex")
  ).toString("base64");
  return ciphertextCache;
}

function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

async function callContract(contractAddress, signature, params) {
  ciphertextCache = null;
  const entitySecretCiphertext = await getCiphertext();
  const res = await fetch(`${API}/developer/transactions/contractExecution`, {
    method: "POST",
    headers: { Authorization: `Bearer ${API_KEY}`, "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      idempotencyKey: crypto.randomUUID(),
      walletId: WALLET_ID,
      contractAddress,
      abiFunctionSignature: signature,
      abiParameters: params,
      feeLevel: "MEDIUM",
      entitySecretCiphertext,
    }),
  });
  const data = await res.json();
  if (res.status >= 400) throw new Error(`API ${res.status}: ${JSON.stringify(data)}`);
  const txId = data.data?.id;

  // Wait for tx
  const start = Date.now();
  while (Date.now() - start < 60_000) {
    const check = await fetch(`${API}/transactions/${txId}`, {
      headers: { Authorization: `Bearer ${API_KEY}`, Accept: "application/json" },
    });
    const checkData = await check.json();
    const tx = checkData.data?.transaction;
    if (tx?.state === "COMPLETE") return txId;
    if (tx?.state === "FAILED") throw new Error(`TX ${txId} failed`);
    await wait(3000);
  }
  console.log(`  ⚠️ TX ${txId} timed out (may still succeed)`);
  return txId;
}

// ─── Main ───────────────────────────────────────────────────

async function main() {
  console.log("=== Seeding AMM Liquidity ===\n");

  for (const asset of ASSETS) {
    const vaultAddr = getEnv(`${asset.env}_VAULT`);
    const tokenAddr = getEnv(`${asset.env}_TOKEN`);
    if (!vaultAddr || !tokenAddr) {
      console.log(`${asset.id}: SKIP (no addresses)`);
      continue;
    }

    console.log(`── ${asset.id} ──`);

    // Step 1: Approve vault to spend USDC (for mint)
    process.stdout.write(`  Approving USDC → vault...`);
    try {
      await callContract(USDC, "approve(address,uint256)", [vaultAddr, "115792089237316195423570985008687907853269984665640564039457584007913129639935"]);
      console.log(" ✅");
    } catch (err) {
      console.log(` ❌ ${err.message}`);
      continue;
    }

    // Step 2: Mint synthetics by depositing USDC into the vault
    process.stdout.write(`  Minting ${asset.id} synthetics...`);
    try {
      await callContract(vaultAddr, "mint(uint256)", [asset.mintAmount]);
      console.log(" ✅");
    } catch (err) {
      console.log(` ❌ ${err.message}`);
      continue;
    }

    // Step 3: Approve router to spend synth tokens
    process.stdout.write(`  Approving synth token...`);
    try {
      // max approval
      await callContract(tokenAddr, "approve(address,uint256)", [AMM_ROUTER, "115792089237316195423570985008687907853269984665640564039457584007913129639935"]);
      console.log(" ✅");
    } catch (err) {
      console.log(` ❌ ${err.message}`);
      continue;
    }

    // Step 4: Approve router to spend USDC
    process.stdout.write(`  Approving USDC → router...`);
    try {
      await callContract(USDC, "approve(address,uint256)", [AMM_ROUTER, "115792089237316195423570985008687907853269984665640564039457584007913129639935"]);
      console.log(" ✅");
    } catch (err) {
      console.log(` ❌ ${err.message}`);
      continue;
    }

    // Step 5: Add liquidity
    process.stdout.write(`  Adding liquidity...`);
    try {
      await callContract(AMM_ROUTER, "addLiquidity(address,address,uint256,uint256,uint256)", [
        USDC,
        tokenAddr,
        asset.mintAmount,     // USDC amount (6 dec)
        asset.liqToken,       // synth amount (18 dec)
        "0",                  // min LP tokens
      ]);
      console.log(" ✅");
    } catch (err) {
      console.log(` ❌ ${err.message}`);
    }
  }

  console.log("\n=== Liquidity Seeding Complete ===");
}

main().catch((err) => {
  console.error("\nFailed:", err.message || err);
  process.exit(1);
});
