"use client";

/**
 * Pre-interview screen: explains the flow and starts a session. The actual
 * /session/start call (and any cold-start wait) is handled by the parent.
 */
export default function StartScreen({ onStart, onSignOut, starting }) {
  return (
    <div className="card stack">
      <h2 style={{ marginTop: 0 }}>Ready to begin</h2>
      <p className="muted">
        You&apos;ll be shown a series of questions, one at a time, each with a
        countdown timer. Type your answer and submit — you&apos;ll get an instant
        score and feedback before moving to the next. You can skip a question if
        needed.
      </p>
      <div className="row">
        <button onClick={onStart} disabled={starting}>
          {starting ? (
            <>
              <span className="spinner" /> Starting…
            </>
          ) : (
            "Start interview"
          )}
        </button>
        <div className="spacer" />
        <button className="ghost" onClick={onSignOut} disabled={starting}>
          Change token
        </button>
      </div>
    </div>
  );
}
