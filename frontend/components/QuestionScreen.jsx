"use client";

import { useEffect, useRef, useState } from "react";
import { fmtClock } from "@/lib/format";

/**
 * One question: metadata, a countdown timer, an answer box, and submit/skip.
 *
 * Timer: counts down from the question's time_limit_seconds. When it hits 0 we
 * AUTO-submit whatever is typed (empty → treated as a skip), so a stalled
 * candidate still advances.
 *
 * Double-submit guard: inFlightRef blocks a second send until the current one
 * settles. The parent flips `submitting` back to false on FAILURE (it navigates
 * away on success), and the effect below clears the ref then — so a failed
 * submit can be retried.
 *
 * This component is intentionally "dumb" about the API — it calls
 * onSubmit({ text, wasSkipped, timeTakenSeconds }) and the parent does the rest.
 */
export default function QuestionScreen({ question, index, total, onSubmit, submitting, error }) {
  const limit = question.time_limit_seconds || 90;
  const [text, setText] = useState("");
  const [remaining, setRemaining] = useState(limit);
  const inFlightRef = useRef(false);

  // Reset everything whenever we move to a new question.
  useEffect(() => {
    setText("");
    setRemaining(limit);
    inFlightRef.current = false;
  }, [question.id, limit]);

  // Clear the in-flight guard once a submit settles without navigating away
  // (i.e. it errored and the parent set submitting back to false) → retry OK.
  useEffect(() => {
    if (!submitting) inFlightRef.current = false;
  }, [submitting]);

  // 1-second countdown.
  useEffect(() => {
    if (submitting) return; // freeze the clock while the score is in flight
    const t = setInterval(() => {
      setRemaining((r) => (r > 0 ? r - 1 : 0));
    }, 1000);
    return () => clearInterval(t);
  }, [submitting]);

  const send = (wasSkipped) => {
    if (inFlightRef.current || submitting) return;
    inFlightRef.current = true;
    onSubmit({
      text: wasSkipped ? "" : text.trim(),
      wasSkipped,
      timeTakenSeconds: Math.max(0, limit - remaining),
    });
  };

  // Auto-submit on expiry: empty answer counts as a skip.
  useEffect(() => {
    if (remaining === 0 && !inFlightRef.current && !submitting) {
      send(text.trim().length === 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remaining]);

  const timerClass =
    remaining <= 10 ? "timer danger" : remaining <= 30 ? "timer warn" : "timer";

  return (
    <div className="card stack">
      <div className="row">
        <span className="progress">
          Question {index + 1} of {total}
        </span>
        <div className="spacer" />
        <span className={timerClass}>{fmtClock(remaining)}</span>
      </div>

      <div>
        <div className="qmeta">
          {question.question_type} · {question.category}
        </div>
        <div className="qtext">{question.question}</div>
      </div>

      <div>
        <label className="field" htmlFor="ans">Your answer</label>
        <textarea
          id="ans"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type your answer here…"
          disabled={submitting}
          autoFocus
        />
      </div>

      {error && <div className="banner error">{error}</div>}

      <div className="row">
        <button onClick={() => send(false)} disabled={submitting || !text.trim()}>
          {submitting ? (
            <>
              <span className="spinner" /> Scoring…
            </>
          ) : (
            "Submit answer"
          )}
        </button>
        <button className="secondary" onClick={() => send(true)} disabled={submitting}>
          Skip
        </button>
        <div className="spacer" />
        <span className="small muted">{text.trim().length} chars</span>
      </div>
    </div>
  );
}
