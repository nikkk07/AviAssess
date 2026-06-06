"""
Behavioral / situational scorer (the "relevance" dimension).

WHY this module exists:
    Behavioral and situational questions have `answer: null` in the dataset —
    there is NO reference answer to compare against. "Tell me about yourself"
    has no single correct response, so semantic similarity to a model answer is
    meaningless here.

    What we CAN measure is RELEVANCE: did the candidate actually talk about the
    themes the question is probing? We express those themes as essential and
    supporting keywords, and check whether their MEANING shows up in the answer
    (via semantic_keyword_coverage), not their exact wording — a candidate who
    says "fascinated by flight" should get credit for the theme "passion".

    Like technical.py, this module owns exactly ONE dimension. It returns a
    normalized relevance score plus the keyword hit/miss lists. It does NOT
    assign a band, write feedback, or convert to a percentage — the router
    (engine.py) does that once it has blended relevance with communication and
    confidence:

        relevance * 0.35 + communication * 0.40 + confidence * 0.25
"""

from app.scoring.keywords import semantic_keyword_coverage


def score_behavioral(
    student_answer: str,
    essential_keywords: list[str],
    supporting_keywords: list[str],
) -> dict:
    """
    Score the RELEVANCE dimension of a behavioral/situational answer.

    Args:
        student_answer      : Raw text from the candidate.
        essential_keywords  : Core themes the question is probing.
        supporting_keywords : Bonus themes that add depth.

    Returns:
        A dimension result dict (NOT a final answer result):
            {
              "score": float in [0.0, 1.0],   # the relevance dimension only
              "keywords": {
                  "essential_hit":  list[str],
                  "essential_miss": list[str],
                  "supporting_hit": list[str],
              },
              "similarities": {keyword: raw_max_similarity},  # for calibration
            }
    """

    # ─────────────────────────────────────────────
    # Guard: empty / whitespace-only answer → zero relevance.
    # Skips the model entirely.
    # ─────────────────────────────────────────────
    if not student_answer or not student_answer.strip():
        return _empty_dimension(essential_keywords, supporting_keywords)

    # ─────────────────────────────────────────────
    # Relevance = thematic coverage by meaning.
    # All the heavy lifting (sentence split, batch encode, cosine matrix,
    # graded credit) lives in semantic_keyword_coverage — we just adapt
    # its result into the standard dimension shape.
    # ─────────────────────────────────────────────
    coverage = semantic_keyword_coverage(
        student_answer,
        essential_keywords,
        supporting_keywords,
    )

    return {
        "score": coverage["score"],
        "keywords": {
            "essential_hit":  coverage["essential_hit"],
            "essential_miss": coverage["essential_miss"],
            "supporting_hit": coverage["supporting_hit"],
        },
        "similarities": coverage["similarities"],
    }


def _empty_dimension(
    essential_keywords: list[str],
    supporting_keywords: list[str],
) -> dict:
    """Zero-score relevance dimension for an empty answer."""
    return {
        "score": 0.0,
        "keywords": {
            "essential_hit":  [],
            "essential_miss": list(essential_keywords),
            "supporting_hit": [],
        },
        "similarities": {
            kw: 0.0 for kw in list(essential_keywords) + list(supporting_keywords)
        },
    }


# ─────────────────────────────────────────────────────────
# Standalone Demo
# Run from the PROJECT ROOT:  python -m app.scoring.behavioral
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":

    question = "Tell me about yourself — why aviation?"

    # Themes the question is really probing (not words we expect verbatim).
    # NOTE: short evocative PHRASES embed far better against full sentences
    # than bare abstract nouns ("passion" alone barely matched "fascinated by
    # flight"; "passion for flying" matches it cleanly). Thresholds are kept
    # fixed (STRONG=0.50, WEAK=0.35) — the dataset wording carries the fix.
    essential  = [
        "passion for flying",
        "the airline industry",
        "hands-on aviation experience",
        "career goal",
    ]
    supporting = [
        "working with a crew",
        "commitment to safety",
        "travel",
        "career",
    ]

    test_answers = [
        (
            "Ever since I was a child I have been fascinated by flight and "
            "the science of how aircraft stay in the air. I spent two summers "
            "working as part of a ground crew, which taught me how a team keeps "
            "operations running safely. My ambition is to grow into a captain "
            "and build a long career in the airline industry.",
            "STRONG — synonyms, not exact keywords",
        ),
        (
            "I like planes and I want this job. Flying seems cool to me.",
            "On-topic but thin",
        ),
        (
            "On weekends I mostly cook pasta and play video games with my "
            "friends. I also follow a couple of football teams quite closely.",
            "Completely off-topic",
        ),
        (
            "",
            "Empty answer (guard clause)",
        ),
    ]

    print("\n" + "=" * 70)
    print(f"  RELEVANCE DIMENSION — QUESTION: {question}")
    print("=" * 70)

    for student_ans, label in test_answers:
        result = score_behavioral(student_ans, essential, supporting)

        print(f"\n  [{label}]")
        print(f"  Answer       : {student_ans[:66] or '(empty)'}")
        print(f"  Score        : {round(result['score'] * 100, 1)}%  (dimension, 0–100)")
        print(f"  Essential Hit : {result['keywords']['essential_hit']}")
        print(f"  Essential Miss: {result['keywords']['essential_miss']}")
        print(f"  Supporting Hit: {result['keywords']['supporting_hit']}")
        print(f"  Similarities  : {result['similarities']}")
        print("-" * 70)
