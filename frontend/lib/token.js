/**
 * Dev-token storage for Phase 6.1.
 *
 * In 6.1 there is no login UI yet (deferred to 6.5). Instead the user pastes an
 * access token minted with the shared JWT_SECRET_KEY — the SAME kind of token
 * scripts/live_test.py mints — and we send it as the Bearer credential.
 *
 * It lives in sessionStorage so a page reload during testing doesn't lose it,
 * but it is NOT persisted to localStorage (cleared when the tab closes) and is
 * never written to env/disk. This whole module is a stopgap that the real login
 * flow will replace.
 */

const KEY = "aviassess.devToken";

/** Read the stored dev token, or "" if none / not in the browser. */
export function getToken() {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(KEY) || "";
}

/** Persist (or clear, when falsy) the dev token for this tab. */
export function setToken(token) {
  if (typeof window === "undefined") return;
  if (token) window.sessionStorage.setItem(KEY, token);
  else window.sessionStorage.removeItem(KEY);
}

/**
 * Best-effort sanity read of a JWT's payload for display ONLY (e.g. show the
 * sub / expiry). This does NOT verify the signature — verification is the
 * server's job — it just base64url-decodes the middle segment.
 */
export function peekClaims(token) {
  try {
    const [, payload] = token.split(".");
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json);
  } catch {
    return null;
  }
}
