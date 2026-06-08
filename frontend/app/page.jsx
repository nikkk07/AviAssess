"use client";

import { useEffect, useState } from "react";

import TokenGate from "@/components/TokenGate";
import StartScreen from "@/components/StartScreen";
import QuestionScreen from "@/components/QuestionScreen";
import FeedbackCard from "@/components/FeedbackCard";
import ResultsScreen from "@/components/ResultsScreen";

import { getToken, setToken } from "@/lib/token";
import {
  API_BASE_URL,
  ApiError,
  getHealth,
  startSession,
  submitAnswer,
  completeSession,
} from "@/lib/api";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isAuthError = (err) =>
  err instanceof ApiError &&
  (err.code === "token_expired" || err.code === "invalid_token" || err.status === 401);

/**
 * Phase 6.1 interview flow — one orchestrating state machine.
 *
 *   token ──► ready ──► question ⇄ feedback ──► completing ──► results
 *               ▲                                                 │
 *               └───────────────── restart ───────────────────────┘
 *
 * Auth: a rejected token (401) bounces back to the token gate. Real refresh is
 * deferred to 6.5; here we just ask for a fresh paste.
 */
export default function Home() {
  const [token, setTok] = useState("");
  const [phase, setPhase] = useState("token"); // token|ready|question|feedback|completing|results

  const [sessionToken, setSessionToken] = useState("");
  const [questions, setQuestions] = useState([]);
  const [index, setIndex] = useState(0);
  const [results, setResults] = useState([]);
  const [lastResult, setLastResult] = useState(null);
  const [report, setReport] = useState(null);

  const [starting, setStarting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [warming, setWarming] = useState("");
  const [error, setError] = useState("");

  // Restore a dev token pasted earlier in this tab.
  useEffect(() => {
    const t = getToken();
    if (t) {
      setTok(t);
      setPhase("ready");
    }
  }, []);

  // ── token handling ──
  function acceptToken(t) {
    setToken(t);
    setTok(t);
    setError("");
    setPhase("ready");
  }

  function changeToken() {
    setToken("");
    setTok("");
    resetSession();
    setPhase("token");
  }

  function handleAuthError() {
    setToken("");
    setTok("");
    resetSession();
    setError("Your token was rejected (expired or invalid). Paste a fresh one.");
    setPhase("token");
  }

  function resetSession() {
    setSessionToken("");
    setQuestions([]);
    setIndex(0);
    setResults([]);
    setLastResult(null);
    setReport(null);
    setError("");
  }

  // ── start (with cold-start warm-up) ──
  async function warmUp() {
    const deadline = Date.now() + 90000;
    let attempt = 0;
    while (Date.now() < deadline) {
      attempt += 1;
      try {
        const h = await getHealth();
        if (h?.status === "ok") return true;
      } catch {
        /* still waking — fall through to retry */
      }
      setWarming(`Waking the scoring service (cold start, up to ~60s)… attempt ${attempt}`);
      await sleep(3000);
    }
    return false;
  }

  async function handleStart() {
    setStarting(true);
    setError("");
    setWarming("");
    try {
      await warmUp(); // best-effort; we still try to start even if it times out
      setWarming("");
      const data = await startSession(token);
      const qs = data.questions || [];
      if (qs.length === 0) {
        setError("No questions were returned for this session.");
        return;
      }
      setSessionToken(data.session_token);
      setQuestions(qs);
      setIndex(0);
      setResults([]);
      setLastResult(null);
      setPhase("question");
    } catch (err) {
      if (isAuthError(err)) return handleAuthError();
      setError(err?.message || "Could not start the interview.");
    } finally {
      setStarting(false);
      setWarming("");
    }
  }

  // ── submit one answer ──
  async function handleAnswerSubmit({ text, wasSkipped, timeTakenSeconds }) {
    const q = questions[index];
    setSubmitting(true);
    setError("");
    try {
      const result = await submitAnswer(token, {
        session_token: sessionToken,
        question_id: q.id,
        student_answer_text: text,
        time_taken_seconds: timeTakenSeconds,
        was_skipped: wasSkipped,
        behavioral_features: null, // 6.1 is text-only; voice/camera/tone come later
      });
      setResults((prev) => [...prev, result]);
      setLastResult(result);
      setPhase("feedback");
    } catch (err) {
      if (isAuthError(err)) return handleAuthError();
      // Stay on the question; QuestionScreen shows this and allows a retry.
      setError(err?.message || "Scoring failed. Try submitting again.");
    } finally {
      setSubmitting(false);
    }
  }

  // ── advance / complete ──
  const isLast = index >= questions.length - 1;

  async function handleNext() {
    if (!isLast) {
      setIndex((i) => i + 1);
      setLastResult(null);
      setError("");
      setPhase("question");
      return;
    }
    await runComplete();
  }

  async function runComplete() {
    setPhase("completing");
    setError("");
    try {
      const rep = await completeSession(token, sessionToken, results);
      setReport(rep);
      setPhase("results");
    } catch (err) {
      if (isAuthError(err)) return handleAuthError();
      setError(err?.message || "Could not finalize the interview.");
      // Stay on "completing" so the Retry button is shown.
    }
  }

  function handleRestart() {
    resetSession();
    setPhase("ready");
  }

  // ── render ──
  return (
    <main className="page">
      <div className="brand">
        <h1>AviAssess</h1>
        <span className="tag">Interview · Phase 6.1</span>
      </div>

      {phase === "token" && (
        <>
          {error && <div className="banner error" style={{ marginBottom: 16 }}>{error}</div>}
          <TokenGate onSubmit={acceptToken} />
        </>
      )}

      {phase === "ready" && (
        <>
          {warming && <div className="banner info" style={{ marginBottom: 16 }}>
            <span className="spinner" /> {warming}
          </div>}
          {error && <div className="banner error" style={{ marginBottom: 16 }}>{error}</div>}
          <StartScreen onStart={handleStart} onSignOut={changeToken} starting={starting} />
        </>
      )}

      {phase === "question" && questions[index] && (
        <QuestionScreen
          question={questions[index]}
          index={index}
          total={questions.length}
          onSubmit={handleAnswerSubmit}
          submitting={submitting}
          error={error}
        />
      )}

      {phase === "feedback" && lastResult && (
        <FeedbackCard result={lastResult} isLast={isLast} onNext={handleNext} />
      )}

      {phase === "completing" && (
        <div className="card stack">
          {error ? (
            <>
              <div className="banner error">{error}</div>
              <div className="row">
                <button onClick={runComplete}>Retry</button>
                <button className="secondary" onClick={handleRestart}>Start over</button>
              </div>
            </>
          ) : (
            <p><span className="spinner" /> Compiling your results…</p>
          )}
        </div>
      )}

      {phase === "results" && report && (
        <ResultsScreen report={report} onRestart={handleRestart} />
      )}

      <p className="small muted" style={{ marginTop: 24 }}>
        API: <code>{API_BASE_URL}</code>
      </p>
    </main>
  );
}
