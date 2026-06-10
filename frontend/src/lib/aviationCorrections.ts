/**
 * Curated aviation speech-to-text correction layer.
 *
 * WHY this exists (and what it deliberately is NOT):
 *   Browser STT frequently mishears aviation jargon ("drag" → "drug",
 *   "yaw" → "yawn", "TCAS" → "tee cass"). This is a SMALL, HAND-PICKED list of
 *   high-confidence confusions — NOT a general spellchecker. A blanket corrector
 *   would corrupt valid everyday words, so every entry here must be a term that
 *   is almost never intended in its "wrong" form during an aviation interview.
 *
 *   The backend already does fuzzy keyword scoring, so this is mainly cosmetic:
 *   it gives the candidate a clean, readable transcript (and a clean submitted
 *   answer) without changing how answers are scored.
 *
 * HOW TO EXTEND:
 *   Add { wrong, right } pairs below. `wrong` may be a multi-word phrase
 *   ("v one" → "V1"); whitespace inside it is matched flexibly. Matching is
 *   whole-word and case-insensitive (see correctAviationTerms). Only add a pair
 *   when the `wrong` form is very unlikely to be a legitimate word in answers —
 *   e.g. we intentionally DO NOT map common words like "your" → "yaw".
 */

export interface AviationCorrection {
  wrong: string;
  right: string;
}

// ── Curated confusions. Grouped by theme; safe to reorder/extend. ──
export const CORRECTIONS: AviationCorrection[] = [
  // Aerodynamics core terms
  { wrong: 'drug', right: 'drag' },          // "reduce drug" → "reduce drag"
  { wrong: 'yawn', right: 'yaw' },           // NB: never map the common word "your"
  { wrong: 'stahl', right: 'stall' },
  { wrong: 'stoll', right: 'stall' },
  { wrong: 'th rust', right: 'thrust' },     // split mishearing; "trust" is left alone (valid word)

  // Flight controls
  { wrong: 'aleron', right: 'aileron' },
  { wrong: 'a lerons', right: 'ailerons' },
  { wrong: 'a leron', right: 'aileron' },
  { wrong: 'rutter', right: 'rudder' },
  { wrong: 'rudd er', right: 'rudder' },
  // Context-sensitive: singular "flap" is usually "flaps" in answers. Listed per
  // spec; remove this pair if your dataset expects the singular control surface.
  { wrong: 'flap', right: 'flaps' },

  // Speeds / callouts
  { wrong: 'v one', right: 'V1' },
  { wrong: 'v two', right: 'V2' },
  { wrong: 'may day', right: 'mayday' },
  { wrong: 'pan pan', right: 'pan-pan' },
  { wrong: 'go around', right: 'go-around' },

  // Systems / acronyms (canonicalise to uppercase)
  { wrong: 'tee cass', right: 'TCAS' },
  { wrong: 't cas', right: 'TCAS' },
  { wrong: 'vor', right: 'VOR' },
  { wrong: 'ils', right: 'ILS' },
  { wrong: 'metar', right: 'METAR' },
  { wrong: 'notam', right: 'NOTAM' },
  { wrong: 'qnh', right: 'QNH' },
];

/** Escape regex metacharacters in a literal string. */
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Build a whole-word, case-insensitive matcher for one `wrong` term. Internal
 * spaces become `\s+` so "v  one" / "v one" both match.
 */
function buildPattern(wrong: string): RegExp {
  const escaped = escapeRegExp(wrong.trim()).replace(/\s+/g, '\\s+');
  return new RegExp(`\\b${escaped}\\b`, 'gi');
}

// Precompile once — the list is static.
const COMPILED = CORRECTIONS.map((c) => ({ re: buildPattern(c.wrong), right: c.right }));

/**
 * Replace ONLY whole-word, case-insensitive matches of curated aviation
 * confusions, preserving all surrounding text. If the matched text started with
 * a capital (e.g. sentence start), the replacement's first letter is capitalised
 * too, so "Drug reduces lift" → "Drag reduces lift".
 */
export function correctAviationTerms(text: string): string {
  if (!text) return text;
  let out = text;
  for (const { re, right } of COMPILED) {
    out = out.replace(re, (match) => {
      const firstAlpha = match.match(/[a-z]/i)?.[0];
      if (firstAlpha && firstAlpha === firstAlpha.toUpperCase()) {
        return right.charAt(0).toUpperCase() + right.slice(1);
      }
      return right;
    });
  }
  return out;
}
