// gen-ciphertext.mjs
// Generates a fresh entity secret ciphertext for use in Circle Console reset UI.
import crypto from "crypto";

const API_KEY = process.env.CIRCLE_API_KEY;
if (!API_KEY) {
  console.error("Need CIRCLE_API_KEY in env");
  process.exit(1);
}

// 1. Fetch public key
console.error("Fetching public key...");
const pkRes = await fetch("https://api.circle.com/v1/w3s/config/entity/publicKey", {
  headers: { Authorization: `Bearer ${API_KEY}` },
});
if (!pkRes.ok) {
  console.error("Failed to fetch public key:", pkRes.status);
  process.exit(1);
}
const { data } = await pkRes.json();
const publicKey = data.publicKey;
console.error("Public key fetched, length:", publicKey.length);

// 2. Generate fresh 32-byte entity secret
const entitySecret = crypto.randomBytes(32).toString("hex");
console.error("New entity secret:", entitySecret);

// 3. Encrypt with RSA-OAEP SHA-256
const ciphertext = crypto
  .publicEncrypt(
    {
      key: publicKey,
      oaepHash: "sha256",
      padding: crypto.constants.RSA_PKCS1_OAEP_PADDING,
    },
    Buffer.from(entitySecret, "hex"),
  )
  .toString("base64");

console.error("Ciphertext length:", ciphertext.length);

// Output only the ciphertext to stdout (clean, no extra whitespace)
console.log(ciphertext);

// Also print the secret to stderr so the user can save it
console.error("\n--- Save this entity secret (keep it safe!) ---");
console.error(entitySecret);
console.error("-----------------------------------------------");
