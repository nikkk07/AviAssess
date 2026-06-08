/**
 * API client for the AviAssess scoring service.
 *
 * One thin wrapper per endpoint. Every authed call attaches the Bearer token,
 * and every response is run through the SAME error handling so the UI sees a
 * consistent ApiError ({ error, message, status }) shaped from the backend's
 * { error, message, details } envelope.
 *
 * The token itself is NOT stored here — callers pass it in (it lives in
 * lib/token.js for the 6.1 dev-token flow). Base URL comes from
 * NEXT_PUBLIC_API_BASE_URL, falling back to the live Render service.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "https://aviassess.onrender.com";

/** Error carrying the backend's error code + a friendly message + HTTP status. */
export class ApiError extends Error {
  constructor(message, { code = "unknown_error", status = 0 } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code; // e.g. "token_expired", "invalid_token", "no_questions"
    this.status = status;
  }
}

/**
 * Core fetch helper. Adds JSON + optional Bearer headers, parses the body, and
 * converts any non-2xx into an ApiError using the backend's envelope.
 */
async function call(path, { method = "GET", token, body, timeoutMs = 65000 } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  // Abort runaway requests (e.g. a wedged cold start) so the UI can recover.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    // Network-level failure: offline, DNS, CORS block, or our abort timeout.
    const aborted = err?.name === "AbortError";
    throw new ApiError(
      aborted
        ? "The request timed out. The service may still be waking up — try again."
        : "Could not reach the scoring service. Check your connection (or CORS allow-list).",
      { code: aborted ? "timeout" : "network_error" }
    );
  } finally {
    clearTimeout(timer);
  }

  // Parse JSON defensively — some error paths may not return a body.
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    const code = data?.error || "http_error";
    const message = data?.message || `Request failed (HTTP ${res.status}).`;
    throw new ApiError(message, { code, status: res.status });
  }

  return data;
}

// ── Endpoint wrappers ──────────────────────────────────────────────────────

/** Public health probe — used to pre-warm a cold-started instance. */
export function getHealth({ timeoutMs = 20000 } = {}) {
  return call("/api/health", { timeoutMs });
}

/** Begin a session → { session_token, questions, issued_at }. */
export function startSession(token, { category, difficulty } = {}) {
  return call("/api/session/start", {
    method: "POST",
    token,
    body: { category: category ?? null, difficulty: difficulty ?? null },
  });
}

/** Score one answer → AnswerScoreResponse. */
export function submitAnswer(token, payload) {
  // payload: { session_token, question_id, student_answer_text,
  //            time_taken_seconds, was_skipped, behavioral_features }
  return call("/api/answer/submit", { method: "POST", token, body: payload });
}

/** Finalize → aggregated report. results is an array of AnswerScoreResponse. */
export function completeSession(token, sessionToken, results) {
  return call("/api/session/complete", {
    method: "POST",
    token,
    body: { session_token: sessionToken, results },
  });
}

/** Caller's interview history (used in 6.5; harmless to expose now). */
export function getInterviews(token) {
  return call("/api/interviews", { token });
}
