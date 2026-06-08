"use client";

import { fmtScore, bandClass } from "@/lib/format";

/**
 * End-of-session report from /api/session/complete: overall score + band,
 * a one-line summary, and the per-question breakdown.
 *
 * A full history view (/api/interviews) and richer polish land in 6.5.
 */
export default function ResultsScreen({ report, onRestart }) {
  const perQ = report.per_question || [];
  return (
    <div className="stack">
      <div className="card stack">
        <div className="row">
          <div>
            <div className="qmeta">Overall score</div>
            <div className="score-big">{fmtScore(report.total_score)}</div>
          </div>
          <div className="spacer" />
          <span className={bandClass(report.overall_band)}>
            {report.overall_band}
          </span>
        </div>

        {report.summary && <p>{report.summary}</p>}

        <p className="small muted">
          {report.num_questions} question
          {report.num_questions === 1 ? "" : "s"} · {report.num_skipped} skipped
        </p>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Per-question breakdown</h3>
        <table className="rows">
          <tbody>
            {perQ.map((q, i) => (
              <tr key={q.question_id || i}>
                <td>
                  <span className="muted">#{i + 1}</span>{" "}
                  <code>{q.question_id}</code>
                </td>
                <td>
                  <span className={bandClass(q.band)} style={{ marginRight: 10 }}>
                    {q.band}
                  </span>
                  <strong>{fmtScore(q.final_score)}</strong>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="row">
        <button onClick={onRestart}>Start new interview</button>
      </div>
    </div>
  );
}
