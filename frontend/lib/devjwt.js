/**
 * Dev-only, in-browser HS256 JWT minting (Phase 6.1 convenience).
 *
 * WHY: the scoring API verifies access tokens signed with JWT_SECRET_KEY. Rather
 * than make you run a script to mint one, the dev token gate lets you paste the
 * SECRET and we sign a valid {sub, type:"access", exp} token right here using the
 * browser's built-in Web Crypto (SubtleCrypto HMAC-SHA256) — no dependency, and
 * exactly the token shape scripts/live_test.py produces.
 *
 * This is a DEV stopgap. The secret only lives in this tab and is used solely to
 * sign a local token; it is never sent to any server. Real login replaces all of
 * this in 6.5.
 */

const enc = new TextEncoder();

function bytesToB64url(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function strToB64url(str) {
  return bytesToB64url(enc.encode(str));
}

function b64urlDecode(str) {
  const pad = str.length % 4 === 0 ? "" : "=".repeat(4 - (str.length % 4));
  return atob(str.replace(/-/g, "+").replace(/_/g, "/") + pad);
}

/**
 * True if the string is already a well-formed JWT (3 segments whose header has
 * an `alg` and whose payload is a JSON object). Lets the gate accept a real
 * token OR a secret transparently.
 */
export function looksLikeJwt(str) {
  const parts = str.split(".");
  if (parts.length !== 3) return false;
  try {
    const header = JSON.parse(b64urlDecode(parts[0]));
    const payload = JSON.parse(b64urlDecode(parts[1]));
    return Boolean(header && header.alg) && typeof payload === "object";
  } catch {
    return false;
  }
}

/**
 * Mint an HS256 access token signed with `secret`.
 * Mirrors the backend's contract: { sub: <uuid>, type: "access", iat, exp }.
 */
export async function mintAccessToken(secret, { hours = 2 } = {}) {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: "HS256", typ: "JWT" };
  const payload = {
    sub: crypto.randomUUID(),
    type: "access",
    iat: now,
    exp: now + hours * 3600,
  };

  const signingInput = `${strToB64url(JSON.stringify(header))}.${strToB64url(
    JSON.stringify(payload)
  )}`;

  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(signingInput));
  return `${signingInput}.${bytesToB64url(new Uint8Array(sig))}`;
}
