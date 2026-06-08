"use client";

import { fmtScore, bandClass } from "@/lib/format";

/**
 * Shows the scored result for the answer just submitted: headline score + band,
 * per-dimension breakdown, and the structured feedback the engine returns.
 * The "next" action (Next question / See results) is supplied by the parent.
 */
export default function FeedbackCard({ result, isLast, onNext }) {
  const dims = result.dimensions || {};
  const fb = result.feedback || {};

  // Only render dimensions the engine actually populated (others are null).
  const dimEntries = ["technical", "relevance", "communication", "confidence"]
    .filter((k) => dims[k] !== null && dims[k] !== undefined)
    .map((k) => [k, dims[k]]);

  const notes = ["technical", "relevance", "communication", "confidence"]
    .filter((k) => fb[k])
    .map((k) => [k, fb[k]]);

  return (
    <div className="card stack">
      <div className="row">
        <div>
          <div className="qmeta">Result</div>
          <div className="score-big">{fmtScore(result.final_score)}</div>
        </div>
        <div className="spacer" />
        <span className={bandClass(result.band)}>{result.band}</span>
      </div>

      {dimEntries.length > 0 && (
        <div className="dims">
          {dimEntries.map(([k, v]) => (
            <div className="dim" key={k}>
              <div className="k">{k}</div>
              <div className="v">{fmtScore(v)}</div>
            </div>
          ))}
        </div>
      )}

      <div className="fb stack">
        {fb.overall && <p className="lead">{fb.overall}</p>}
        {notes.map(([k, v]) => (
          <p key={k} className="small muted">
            <strong style={{ textTransform: "capitalize", color: "var(--text)" }}>
              {k}:
            </strong>{" "}
            {v}
          </p>
        ))}

        {(fb.keywords_hit?.length || fb.keywords_missed?.length) ? (
          <div>
            <div className="chips">
              {(fb.keywords_hit || []).map((w) => (
                <span className="chip hit" key={`h-${w}`}>✓ {w}</span>
              ))}
              {(fb.keywords_missed || []).map((w) => (
                <span className="chip miss" key={`m-${w}`}>✗ {w}</span>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <div className="row">
        <button onClick={onNext}>
          {isLast ? "See results" : "Next question"}
        </button>
      </div>
    </div>
  );
}
