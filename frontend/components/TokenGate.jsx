"use client";

import { useState } from "react";
import { peekClaims } from "@/lib/token";
import { looksLikeJwt, mintAccessToken } from "@/lib/devjwt";

/**
 * Phase 6.1 dev access gate.
 *
 * You can paste EITHER:
 *   • the service's JWT_SECRET_KEY  → we generate a valid token from it here, or
 *   • an actual access token (eyJ...) → we use it as-is.
 *
 * Pasting the secret is the easy path for dev; a real login flow replaces this
 * in 6.5. The secret never leaves this tab — it's only used to sign a local
 * token (see lib/devjwt.js).
 */
export default function TokenGate({ onSubmit }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const trimmed = value.trim();
  const isToken = trimmed ? looksLikeJwt(trimmed) : false;
  const claims = isToken ? peekClaims(trimmed) : null;
  const exp = claims?.exp ? new Date(claims.exp * 1000) : null;
  const expired = exp ? exp.getTime() < Date.now() : false;

  async function handleUse() {
    if (!trimmed || busy) return;
    setErr("");
    setBusy(true);
    try {
      // A real token is used directly; anything else is treated as the secret
      // and signed into a fresh token in the browser.
      const token = isToken ? trimmed : await mintAccessToken(trimmed);
      onSubmit(token);
    } catch {
      setErr("Couldn't prepare a token from that input. Double-check the value.");
      setBusy(false);
    }
  }

  return (
    <div className="card stack">
      <div>
        <h2 style={{ marginTop: 0 }}>Developer access</h2>
        <p className="muted small">
          Paste the service&apos;s <code>JWT_SECRET_KEY</code> and we&apos;ll
          generate a valid token for you — or paste an existing access token
          (<code>eyJ…</code>) to use directly. Either stays only in this tab. A
          real login screen replaces this in 6.5.
        </p>
      </div>

      <div>
        <label className="field" htmlFor="tok">
          JWT_SECRET_KEY (or an access token)
        </label>
        <input
          id="tok"
          type="text"
          value={value}
          placeholder="paste your JWT_SECRET_KEY here"
          onChange={(e) => setValue(e.target.value)}
          spellCheck={false}
          autoComplete="off"
        />
      </div>

      {trimmed && (
        <p className="small muted">
          {isToken ? (
            <>
              Detected an access token · sub <code>{String(claims?.sub)}</code> ·
              type <code>{String(claims?.type)}</code>
              {exp && (
                <>
                  {" "}· expires {exp.toLocaleString()}{" "}
                  {expired && <span style={{ color: "var(--bad)" }}>(expired)</span>}
                </>
              )}
            </>
          ) : (
            <>Will generate a 2-hour access token from this secret.</>
          )}
        </p>
      )}

      {err && <div className="banner error">{err}</div>}

      <div className="row">
        <button disabled={!trimmed || busy} onClick={handleUse}>
          {busy ? (
            <>
              <span className="spinner" /> Preparing…
            </>
          ) : isToken ? (
            "Use this token"
          ) : (
            "Generate token & continue"
          )}
        </button>
      </div>
    </div>
  );
}
