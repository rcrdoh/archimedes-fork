// test-secrets.mjs — tries candidate entity secrets against the Circle API
import crypto from "crypto";
import fs from "fs";

const API_KEY = process.env.CIRCLE_API_KEY;
const API = "https://api.circle.com/v1/w3s";
const WALLET_ID = process.env.WALLET_ID || "81d8797e-d004-5c74-a879-e410ed515aed";

// Candidate secrets from this session
const secrets = [
  "0be28ce5710021f231258af9508bb1afbb82dee304b6b924732d4588a4b6d838",
  "721b87ffb031260373ffb625ef53b442427aaa2e79d295df2d0fd222791ca7fc",
  "040a4a1a95fd699169f0b9dae3cbbc47dfa90a22f905547fc4d79aeb24ea3a9f",
];

const pkRes = await fetch(`${API}/config/entity/publicKey`, {
  headers: { Authorization: `Bearer ${API_KEY}`, Accept: "application/json" },
});
const pkData = await pkRes.json();
const pub = crypto.createPublicKey({ key: pkData.data.publicKey, format: "pem" });

let foundSecret = null;

for (const secret of secrets) {
  const ct = crypto.publicEncrypt(
    { key: pub, padding: crypto.constants.RSA_PKCS1_OAEP_PADDING, oaepHash: "sha256" },
    Buffer.from(secret, "hex")
  ).toString("base64");

  const testRes = await fetch(`${API}/developer/transactions/contractExecution`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      idempotencyKey: crypto.randomUUID(),
      walletId: WALLET_ID,
      contractAddress: "0x8c77f2920a7d440dc07d824fbe7e39166c5a27a0",
      abiFunctionSignature: "setPrice(uint256)",
      abiParameters: ["433450000"],
      feeLevel: "MEDIUM",
      entitySecretCiphertext: ct,
    }),
  });
  const testData = await testRes.json();
  const ok = testRes.status < 400;
  console.log(`${secret.slice(0, 16)}... → ${ok ? "✅ WORKS!" : "❌ " + testData.code}`);

  if (ok) {
    foundSecret = secret;
    console.log(`TX ID: ${testData.data?.id}`);
    break;
  }
}

if (foundSecret) {
  const envPath = ".env";
  let env = fs.readFileSync(envPath, "utf8");
  if (env.includes("CIRCLE_ENTITY_SECRET=")) {
    env = env.replace(/CIRCLE_ENTITY_SECRET=.*/, `CIRCLE_ENTITY_SECRET=${foundSecret}`);
  } else {
    env += `\nCIRCLE_ENTITY_SECRET=${foundSecret}\n`;
  }
  fs.writeFileSync(envPath, env);
  console.log("\n✅ Saved working secret to .env");
} else {
  console.log("\n❌ None of the candidate secrets worked.");
  console.log("You need the ORIGINAL entity secret that was registered with this Circle app.");
  console.log("Check your password manager, notes, or chat history for a 64-char hex string.");
}
