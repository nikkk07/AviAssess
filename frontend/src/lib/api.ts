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
  // Post-interview reference answers, keyed by question_id (may be null per
  // question). Populated by the finalize endpoint once the interview is over.
  model_answers?: Record<string, string | null>;
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
  // Backoff schedule for TRANSIENT (network/timeout) failures only. One retry
  // per entry, waiting that many ms before each. Default [] = no retries.
  retryDelaysMs?: number[];
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * A failure is TRANSIENT (worth retrying) only when it never reached a real
 * response — i.e. our network/timeout path. A genuine API error (4xx/5xx with
 * the backend envelope, e.g. validation, auth, no_questions) is NOT transient
 * and must surface immediately rather than being retried.
 */
function isTransientError(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.code === "network_error" || err.code === "timeout")
  );
}

/**
 * One fetch attempt. Adds JSON + optional Bearer headers, parses the body, and
 * converts any non-2xx into an ApiError using the backend's envelope. A
 * network-level failure (offline/DNS/CORS/abort-timeout) throws an ApiError
 * whose code is "network_error"/"timeout" — the marker isTransientError uses.
 */
async function attemptCall(
  path: string,
  { method = "GET", token, body, timeoutMs = 65000 }: CallOpts,
) {
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

/**
 * Core fetch helper with TRANSIENT-only auto-retry. Real API errors are thrown
 * on the first attempt; only network/timeout blips are retried per
 * `retryDelaysMs` (silent backoff) before the failure is surfaced.
 */
async function call(path: string, opts: CallOpts = {}) {
  const { retryDelaysMs = [] } = opts;
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retryDelaysMs.length; attempt += 1) {
    try {
      return await attemptCall(path, opts);
    } catch (err) {
      lastErr = err;
      // Stop immediately on a real API error, or once retries are exhausted.
      if (!isTransientError(err) || attempt === retryDelaysMs.length) throw err;
      await sleep(retryDelaysMs[attempt]);
    }
  }
  throw lastErr; // unreachable (loop either returns or throws) — satisfies TS
}

// Transient-failure backoff for the user-blocking calls (~1.5s, then ~3s).
const TRANSIENT_RETRY_DELAYS_MS = [1500, 3000];
// Scoring/submit is the slowest call right after a cold start — give it longer.
const SUBMIT_TIMEOUT_MS = 90000;

// ── Endpoint wrappers ──────────────────────────────────────────────────────

/** Public health probe — used to pre-warm a cold-started instance. */
export function getHealth({ timeoutMs = 20000 } = {}): Promise<{ status?: string }> {
  return call("/api/health", { timeoutMs });
}

/**
 * DEV-ONLY fixed-code login. Trades a fixed code for a real, server-minted
 * access token (the JWT_SECRET_KEY never touches the browser). The route only
 * exists when DEV_LOGIN_ENABLED is set on the server — otherwise it 404s.
 */
export function devLogin(code: string): Promise<{ access_token: string }> {
  return call("/api/dev/login", { method: "POST", body: { code } });
}

/**
 * Configuration for a session start. Every field is optional — omit any and the
 * backend draws from everything (Phase A1 accepts these and treats unknown/absent
 * values leniently). `interview_type` / `difficulty` are backend param strings
 * (e.g. "technical", "standard"), already mapped from the UI labels.
 */
export interface SessionConfig {
  category?: string | null;
  difficulty?: string | null;
  interview_type?: string | null;
  airline?: string | null;
  aircraft_type?: string | null;
  experience?: string | null;
  question_count?: number | null;
}

/** Begin a session → { session_token, questions, issued_at }. */
export function startSession(
  token: string,
  config: SessionConfig = {}
): Promise<StartSessionResponse> {
  const {
    category,
    difficulty,
    interview_type,
    airline,
    aircraft_type,
    experience,
    question_count,
  } = config;
  return call("/api/session/start", {
    method: "POST",
    token,
    body: {
      category: category ?? null,
      difficulty: difficulty ?? null,
      interview_type: interview_type ?? null,
      airline: airline ?? null,
      aircraft_type: aircraft_type ?? null,
      experience: experience ?? null,
      question_count: question_count ?? null,
    },
    // A transient blip on start shouldn't dump the candidate back to an error.
    retryDelaysMs: TRANSIENT_RETRY_DELAYS_MS,
  });
}

/**
 * Score one answer → AnswerResult. Auto-retries network/timeout blips (silent
 * backoff) so a momentary connection drop doesn't surface as a scoring error;
 * real API errors (auth, validation) are NOT retried. Uses a longer timeout —
 * the first submit after a cold start is slow.
 */
export function submitAnswer(token: string, payload: AnswerPayload): Promise<AnswerResult> {
  return call("/api/answer/submit", {
    method: "POST",
    token,
    body: payload,
    timeoutMs: SUBMIT_TIMEOUT_MS,
    retryDelaysMs: TRANSIENT_RETRY_DELAYS_MS,
  });
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
