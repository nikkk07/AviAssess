"""
Communication scorer (the shared "text quality" dimension).

WHY this module exists:
    Every answer — technical, behavioral, or situational — is also a piece of
    communication. Two candidates can both be "correct" or both "relevant" yet
    differ hugely in how clearly they express themselves. This dimension scores
    HOW WELL the answer is written, independent of WHAT it says.

    Because it is content-agnostic, the SAME communication score feeds into all
    question types (it carries 25% of a technical answer's blend and 40% of a
    behavioral one). So this module takes only the answer text — no expected
    answer, no keywords, no behavioral features.

    Like the other dimension modules, it returns a normalized 0-1 score plus a
    breakdown. It does NOT assign a band, write feedback, or convert to a
    percentage — the router (engine.py) owns presentation.

Five sub-metrics (weights must sum to 1.0):
    Vocabulary richness  → 30%  (varied wording, not repetitive)
    Structure            → 25%  (multiple sentences + logical connectives)
    Length appropriateness → 20%  (enough said, but not rambling)
    Filler penalty       → 15%  ("um", "like", "basically" drag this down)
    Fluency              → 10%  (readable sentence length, not choppy/run-on)
"""

import re

from app.scoring.normalize import normalize, tokenize


# ─────────────────────────────────────────────────────────
# Sub-metric weights — must sum to 1.0
# ─────────────────────────────────────────────────────────
WEIGHT_VOCABULARY = 0.30
WEIGHT_STRUCTURE  = 0.25
WEIGHT_LENGTH     = 0.20
WEIGHT_FILLER     = 0.15
WEIGHT_FLUENCY    = 0.10

# ─────────────────────────────────────────────────────────
# Vocabulary: type-token ratio (unique words / total words).
# Raw TTR falls as answers get longer (natural repetition), which would
# unfairly punish detailed answers. So we score against a TARGET: any answer
# whose TTR reaches the target earns full credit, and only genuinely
# repetitive answers (TTR below target) lose points.
# ─────────────────────────────────────────────────────────
TARGET_TTR = 0.50

# ─────────────────────────────────────────────────────────
# Structure: a well-built answer has several sentences AND ties them together
# with discourse markers. We combine a sentence-count component and a
# connective component.
# ─────────────────────────────────────────────────────────
TARGET_SENTENCES            = 3      # ~3 sentences reads as a structured answer
TARGET_CONNECTIVES          = 2      # a couple of logical links is plenty
STRUCTURE_SENTENCE_WEIGHT   = 0.60
STRUCTURE_CONNECTIVE_WEIGHT = 0.40

# Curated discourse markers — words that signal logical flow. Deliberately
# excludes ultra-common glue like "and"/"that" that would inflate every answer.
CONNECTIVE_WORDS = {
    "because", "since", "therefore", "thus", "so", "however", "although",
    "though", "while", "whereas", "meanwhile", "then", "also", "additionally",
    "moreover", "furthermore", "consequently", "first", "firstly", "second",
    "secondly", "finally", "next", "after", "before", "when", "if", "but",
}

# ─────────────────────────────────────────────────────────
# Length appropriateness: an ideal word-count band for a timed interview
# answer. Below the band scales linearly up; above it decays gently toward a
# floor (rambling is a soft fault, not a disqualifier).
# ─────────────────────────────────────────────────────────
MIN_IDEAL_WORDS     = 40
MAX_IDEAL_WORDS     = 150
LONG_OVERFLOW_WORDS = 150    # words beyond MAX over which the score decays to floor
LONG_FLOOR          = 0.50   # the lowest a long-but-on-topic answer can score here

# ─────────────────────────────────────────────────────────
# Filler penalty: spoken-style crutches. Score starts at 1.0 and drops in
# proportion to the filler-to-total-word ratio, so one "um" in a long answer
# barely registers but constant filler tanks it.
# ─────────────────────────────────────────────────────────
FILLER_PENALTY_SCALE = 5.0   # a ~20% filler ratio drives this sub-metric to 0

FILLER_WORDS = {
    "um", "umm", "uh", "uhh", "er", "erm", "ah", "like", "basically",
    "actually", "literally", "honestly", "anyway",
}
FILLER_PHRASES = [
    "you know", "i mean", "sort of", "kind of", "kinda", "sorta",
    "or whatever", "and stuff",
]

# ─────────────────────────────────────────────────────────
# Fluency: average words per sentence. Too few = choppy/abrupt; too many =
# run-on. Full credit inside the band, decaying outside it.
# ─────────────────────────────────────────────────────────
IDEAL_WORDS_PER_SENTENCE_MIN = 8
IDEAL_WORDS_PER_SENTENCE_MAX = 22


def score_communication(student_answer: str) -> dict:
    """
    Score the COMMUNICATION dimension of an answer (text only).

    Args:
        student_answer : Raw text from the candidate.

    Returns:
        A dimension result dict (NOT a final answer result):
            {
              "score": float in [0.0, 1.0],   # the communication dimension only
              "breakdown": {                  # sub-metrics as 0-1 floats
                  "vocabulary": float,
                  "structure":  float,
                  "length":     float,
                  "filler":     float,
                  "fluency":    float,
              },
              "stats": {                      # raw counts, for calibration
                  "word_count":     int,
                  "sentence_count": int,
                  "filler_count":   int,
              },
            }
    """

    # ─────────────────────────────────────────────
    # Guard: empty / whitespace-only answer → zero.
    # ─────────────────────────────────────────────
    if not student_answer or not student_answer.strip():
        return _empty_dimension()

    sentences  = _split_sentences(student_answer)
    tokens     = tokenize(student_answer)        # normalized word list
    normalized = normalize(student_answer)        # normalized full string
    word_count = len(tokens)

    # Each sub-metric returns a clean 0-1 float.
    vocabulary = _vocabulary_score(tokens)
    structure  = _structure_score(sentences, tokens)
    length     = _length_score(word_count)
    filler, filler_count = _filler_score(normalized, tokens)
    fluency    = _fluency_score(sentences, word_count)

    score = (
        (WEIGHT_VOCABULARY * vocabulary) +
        (WEIGHT_STRUCTURE  * structure)  +
        (WEIGHT_LENGTH     * length)     +
        (WEIGHT_FILLER     * filler)     +
        (WEIGHT_FLUENCY    * fluency)
    )

    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "breakdown": {
            "vocabulary": round(vocabulary, 4),
            "structure":  round(structure, 4),
            "length":     round(length, 4),
            "filler":     round(filler, 4),
            "fluency":    round(fluency, 4),
        },
        "stats": {
            "word_count":     word_count,
            "sentence_count": len(sentences),
            "filler_count":   filler_count,
        },
    }


# ─────────────────────────────────────────────────────────
# Sub-metric helpers — each returns a 0-1 float
# ─────────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """Split raw text into sentences on . ! ? before normalization strips them."""
    if not text or not text.strip():
        return []
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p.strip()]


def _vocabulary_score(tokens: list[str]) -> float:
    """Type-token ratio scored against TARGET_TTR (repetition is the fault)."""
    if not tokens:
        return 0.0
    ttr = len(set(tokens)) / len(tokens)
    return min(1.0, ttr / TARGET_TTR)


def _structure_score(sentences: list[str], tokens: list[str]) -> float:
    """Blend of sentence count and logical-connective presence."""
    sentence_component = min(1.0, len(sentences) / TARGET_SENTENCES)

    connective_count = sum(1 for t in tokens if t in CONNECTIVE_WORDS)
    connective_component = min(1.0, connective_count / TARGET_CONNECTIVES)

    return (
        (STRUCTURE_SENTENCE_WEIGHT   * sentence_component) +
        (STRUCTURE_CONNECTIVE_WEIGHT * connective_component)
    )


def _length_score(word_count: int) -> float:
    """Full credit inside the ideal band; scaled below, decaying above."""
    if word_count <= 0:
        return 0.0
    if word_count < MIN_IDEAL_WORDS:
        return word_count / MIN_IDEAL_WORDS
    if word_count <= MAX_IDEAL_WORDS:
        return 1.0
    # Above the band: decay linearly from 1.0 toward LONG_FLOOR.
    overflow = word_count - MAX_IDEAL_WORDS
    decayed = 1.0 - (overflow / LONG_OVERFLOW_WORDS) * (1.0 - LONG_FLOOR)
    return max(LONG_FLOOR, decayed)


def _filler_score(normalized_text: str, tokens: list[str]) -> tuple[float, int]:
    """Penalize filler crutches in proportion to their share of the answer."""
    if not tokens:
        return 0.0, 0

    # Single-word fillers from the token list.
    filler_count = sum(1 for t in tokens if t in FILLER_WORDS)

    # Multi-word filler phrases via padded substring search (avoids matching
    # inside larger words).
    padded = f" {normalized_text} "
    for phrase in FILLER_PHRASES:
        filler_count += padded.count(f" {phrase} ")

    ratio = filler_count / len(tokens)
    score = 1.0 - (ratio * FILLER_PENALTY_SCALE)
    return max(0.0, score), filler_count


def _fluency_score(sentences: list[str], word_count: int) -> float:
    """Average words per sentence scored against a readable band."""
    if not sentences or word_count == 0:
        return 0.0

    avg_words_per_sentence = word_count / len(sentences)

    if avg_words_per_sentence < IDEAL_WORDS_PER_SENTENCE_MIN:
        return avg_words_per_sentence / IDEAL_WORDS_PER_SENTENCE_MIN
    if avg_words_per_sentence > IDEAL_WORDS_PER_SENTENCE_MAX:
        return IDEAL_WORDS_PER_SENTENCE_MAX / avg_words_per_sentence
    return 1.0


def _empty_dimension() -> dict:
    """Zero-score communication dimension for an empty answer."""
    return {
        "score": 0.0,
        "breakdown": {
            "vocabulary": 0.0, "structure": 0.0, "length": 0.0,
            "filler": 0.0, "fluency": 0.0,
        },
        "stats": {"word_count": 0, "sentence_count": 0, "filler_count": 0},
    }


# ─────────────────────────────────────────────────────────
# Standalone Demo
# Run from the PROJECT ROOT:  python -m app.scoring.communication
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":

    test_answers = [
        (
            "I have always been drawn to aviation because it blends precision "
            "engineering with real responsibility for people's safety. During my "
            "diploma I completed a workshop on aircraft systems, and afterwards I "
            "volunteered with a ground-handling team at a regional airport. That "
            "experience taught me how disciplined coordination keeps every "
            "departure on schedule. My goal is to build a long career as a first "
            "officer and eventually command a fleet.",
            "Strong — rich, structured, well-paced",
        ),
        (
            "I really like planes and I think working in aviation would be a good "
            "job for me. I am hardworking and I learn fast. I want to grow in this "
            "field over time.",
            "Decent but plain",
        ),
        (
            "Um, like, basically I just, you know, really wanted to do this, um, "
            "because planes are, like, kind of cool and stuff, you know.",
            "Filler-heavy spoken style",
        ),
        (
            "I like planes.",
            "Too short",
        ),
        (
            "I want this job because I have always loved aviation since I was a "
            "kid and I worked at an airport and I learned a lot about safety and "
            "teamwork and I am confident I can handle the pressure and I really "
            "want to grow and become a captain one day and serve passengers well.",
            "Run-on — one giant sentence",
        ),
        (
            "",
            "Empty answer (guard clause)",
        ),
    ]

    print("\n" + "=" * 72)
    print("  COMMUNICATION DIMENSION")
    print("=" * 72)

    for answer, label in test_answers:
        result = score_communication(answer)
        b = result["breakdown"]
        s = result["stats"]

        print(f"\n  [{label}]")
        print(f"  Answer   : {answer[:64] or '(empty)'}")
        print(f"  Score    : {round(result['score'] * 100, 1)}%  (dimension, 0–100)")
        print(f"  Breakdown: vocab={b['vocabulary']}  struct={b['structure']}  "
              f"length={b['length']}  filler={b['filler']}  fluency={b['fluency']}")
        print(f"  Stats    : words={s['word_count']}  sentences={s['sentence_count']}  "
              f"fillers={s['filler_count']}")
        print("-" * 72)
