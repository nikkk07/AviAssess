/**
 * Dev-token storage (ported from the Next.js app).
 *
 * There is no real login UI yet, so the user pastes an access token minted with
 * the shared JWT_SECRET_KEY (the SAME kind of token scripts/live_test.py mints)
 * and we send it as the Bearer credential.
 *
 * It lives in sessionStorage so a page reload during testing doesn't lose it,
 * but it is NOT persisted to localStorage (cleared when the tab closes) and is
 * never written to env/disk. A real login flow will replace this.
 */

const KEY = "aviassess.devToken";

/** Read the stored dev token, or "" if none / not in the browser. */
export function getToken(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(KEY) || "";
}

/** Persist (or clear, when falsy) the dev token for this tab. */
export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  if (token) window.sessionStorage.setItem(KEY, token);
  else window.sessionStorage.removeItem(KEY);
}

/** A token is a JWT if it has 3 dot-separated segments (eyJ...). */
export function looksLikeJwt(str: string): boolean {
  return str.split(".").length === 3;
}

/**
 * Best-effort read of a JWT's payload for display ONLY (e.g. show sub/expiry).
 * Does NOT verify the signature — that's the server's job — it just
 * base64url-decodes the middle segment.
 */
export function peekClaims(token: string): Record<string, any> | null {
  try {
    const [, payload] = token.split(".");
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json);
  } catch {
    return null;
  }
}
