/**
 * API client for the AviAssess scoring service (ported from the Next.js app).
 *
 * One thin wrapper per endpoint. Every authed call attaches the Bearer token,
 * and every response runs through the SAME error handling so the UI sees a
 * consistent ApiError ({ code, message, status }) shaped from the backend's
 * { error, message, details } envelope.
 *
 * The token itself is NOT stored here — callers pass it in (it lives in
 * lib/token.ts). Base URL comes from VITE_API_BASE_URL, falling back to the
 * live Render service.
 */

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  "https://aviassess.onrender.com";

// ── Shapes returned by the backend (the fields the UI actually reads) ──
export interface Question {
  id: string;
  question_type?: string;
  category?: string;
  question: string;
  time_limit_seconds?: number;
}

export interface StartSessionResponse {
  session_token: string;
  questions: Question[];
  issued_at?: string;
}

export interface AnswerResult {
  question_id: string;
  final_score: number;
  band: string;
  dimensions?: Record<string, number | null>;
  feedback?: {
    overall?: string;
    technical?: string;
    relevance?: string;
    communication?: string;
    confidence?: string;
    keywords_hit?: string[];
    keywords_missed?: string[];
  };
}

export interface SessionReport {
  total_score: number;
  overall_band: string;
  summary?: string;
  num_questions: number;
  num_skipped: number;
  per_question: Array<{ question_id: string; final_score: number; band: string }>;
}

export interface AnswerPayload {
  session_token: string;
  question_id: string;
  student_answer_text: string;
  time_taken_seconds: number;
  was_skipped: boolean;
  behavioral_features: unknown | null;
}

/** Error carrying the backend's error code + a friendly message + HTTP status. */
export class ApiError extends Error {
  code: string;
  status: number;
  constructor(message: string, { code = "unknown_error", status = 0 } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code; // e.g. "token_expired", "invalid_token", "no_questions"
    this.status = status;
  }
}

interface CallOpts {
  method?: string;
  token?: string;
  body?: unknown;
  timeoutMs?: number;
}

/**
 * Core fetch helper. Adds JSON + optional Bearer headers, parses the body, and
 * converts any non-2xx into an ApiError using the backend's envelope.
 */
async function call(path: string, { method = "GET", token, body, timeoutMs = 65000 }: CallOpts = {}) {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  // Abort runaway requests (e.g. a wedged cold start) so the UI can recover.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err: any) {
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
  let data: any = null;
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
export function getHealth({ timeoutMs = 20000 } = {}): Promise<{ status?: string }> {
  return call("/api/health", { timeoutMs });
}

/** Begin a session → { session_token, questions, issued_at }. */
export function startSession(
  token: string,
  { category, difficulty }: { category?: string | null; difficulty?: string | null } = {}
): Promise<StartSessionResponse> {
  return call("/api/session/start", {
    method: "POST",
    token,
    body: { category: category ?? null, difficulty: difficulty ?? null },
  });
}

/** Score one answer → AnswerResult. */
export function submitAnswer(token: string, payload: AnswerPayload): Promise<AnswerResult> {
  return call("/api/answer/submit", { method: "POST", token, body: payload });
}

/** Finalize → aggregated report. results is an array of AnswerResult. */
export function completeSession(
  token: string,
  sessionToken: string,
  results: AnswerResult[]
): Promise<SessionReport> {
  return call("/api/session/complete", {
    method: "POST",
    token,
    body: { session_token: sessionToken, results },
  });
}

/** True when an error means the token must be re-pasted (expired/invalid/401). */
export function isAuthError(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.code === "token_expired" || err.code === "invalid_token" || err.status === 401)
  );
}
