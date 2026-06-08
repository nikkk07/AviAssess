/** Small presentation helpers shared across screens. */

/** Round a 0–100 score to one decimal for display; "—" when missing. */
export function fmtScore(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

/** CSS class for a band badge (matches globals.css .band-* rules). */
export function bandClass(band) {
  return `badge band-${band || "incorrect"}`;
}

/** mm:ss for the question timer. */
export function fmtClock(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}
