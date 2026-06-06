"""
Technical-question scorer (the "correctness" dimension).

WHY this module exists:
    Technical questions HAVE a known correct answer in the dataset, so we can
    measure how well a student's answer matches it. This module owns exactly
    that one job — producing a single "technical" dimension score.

    It deliberately does NOT decide the final answer band or write the final
    feedback paragraph. In the new architecture a technical question's final
    score is a BLEND:

        technical * 0.50 + communication * 0.25 + confidence * 0.25

    The band must reflect that blended number, not technical alone. So band
    assignment, percentage conversion, and feedback assembly all live in the
    router (engine.py). This module returns a clean, reusable dimension result.

Signal weights (must sum to 1.0):
    Semantic similarity  → 60%  (meaning comprehension — the strongest signal)
    Keyword coverage     → 25%  (critical concept coverage — semantic alone
                                  can be fooled, keywords keep it honest)
    Fuzzy similarity     → 15%  (supporting signal — typo tolerance, overlap)
"""

from app.scoring.semantic import semantic_similarity
from app.scoring.keywords import keyword_coverage
from app.scoring.fuzzy import fuzzy_similarity


# ─────────────────────────────────────────────────────────
# Signal weights — must sum to 1.0
# Change these to tune technical scoring behavior
# ─────────────────────────────────────────────────────────
WEIGHT_SEMANTIC = 0.60
WEIGHT_KEYWORD  = 0.25
WEIGHT_FUZZY    = 0.15

# ─────────────────────────────────────────────────────────
# Short-answer penalty
# A detailed question deserves a real explanation. If the
# reference answer is long but the student wrote almost
# nothing, they clearly did not explain — so we halve the
# score. Named here so there are no magic numbers below.
# ─────────────────────────────────────────────────────────
SHORT_ANSWER_MIN_WORDS   = 4    # student answers shorter than this are "too short"
DETAILED_EXPECTED_WORDS  = 15   # only penalize when the expected answer is this long
SHORT_ANSWER_PENALTY     = 0.5  # multiply the raw score by this when penalized


def score_technical(
    student_answer: str,
    expected_answer: str,
    essential_keywords: list[str],
    supporting_keywords: list[str],
) -> dict:
    """
    Score the TECHNICAL dimension of a student's answer.

    Args:
        student_answer      : Raw text from the student.
        expected_answer     : Reference answer from the dataset.
        essential_keywords  : Must-have concepts.
        supporting_keywords : Nice-to-have concepts.

    Returns:
        A dimension result dict (NOT a final answer result):
            {
              "score": float in [0.0, 1.0],   # the technical dimension only
              "breakdown": {                  # sub-signals, as percentages
                  "semantic": float,
                  "keyword":  float,
                  "fuzzy":    float,
              },
              "keywords": {                   # used later to build feedback
                  "essential_hit":  list[str],
                  "essential_miss": list[str],
                  "supporting_hit": list[str],
              },
            }

    Note:
        The router (engine.py) consumes "score" for the weighted blend, and
        "breakdown"/"keywords" for display and feedback. This function never
        returns a band or a feedback string by design.
    """

    # ─────────────────────────────────────────────
    # Guard: empty / whitespace-only answer
    # Downstream scorers can technically handle it, but
    # returning early keeps the contract explicit and cheap.
    # ─────────────────────────────────────────────
    if not student_answer or not student_answer.strip():
        return _empty_dimension()

    # ─────────────────────────────────────────────
    # Run all three signals independently
    # ─────────────────────────────────────────────
    semantic_score = semantic_similarity(student_answer, expected_answer)

    keyword_result = keyword_coverage(
        student_answer,
        essential_keywords,
        supporting_keywords,
    )
    keyword_score = keyword_result["score"]

    fuzzy_score = fuzzy_similarity(student_answer, expected_answer)

    # ─────────────────────────────────────────────
    # Weighted combination → raw technical score [0, 1]
    # ─────────────────────────────────────────────
    raw_score = (
        (WEIGHT_SEMANTIC * semantic_score) +
        (WEIGHT_KEYWORD  * keyword_score)  +
        (WEIGHT_FUZZY    * fuzzy_score)
    )

    # ─────────────────────────────────────────────
    # Short-answer penalty
    # Only bites when the reference answer is genuinely
    # detailed but the student answered in a few words.
    # ─────────────────────────────────────────────
    student_word_count  = len(student_answer.strip().split())
    expected_word_count = len(expected_answer.strip().split())

    if (
        student_word_count < SHORT_ANSWER_MIN_WORDS
        and expected_word_count >= DETAILED_EXPECTED_WORDS
    ):
        raw_score *= SHORT_ANSWER_PENALTY

    # Clamp to [0, 1] — the dimension is always a normalized float.
    final_score = max(0.0, min(1.0, raw_score))

    return {
        "score": final_score,
        "breakdown": {
            "semantic": round(semantic_score * 100, 1),
            "keyword":  round(keyword_score  * 100, 1),
            "fuzzy":    round(fuzzy_score    * 100, 1),
        },
        "keywords": {
            "essential_hit":  keyword_result["essential_hit"],
            "essential_miss": keyword_result["essential_miss"],
            "supporting_hit": keyword_result["supporting_hit"],
        },
    }


def _empty_dimension() -> dict:
    """Zero-score technical dimension for an empty answer."""
    return {
        "score": 0.0,
        "breakdown": {"semantic": 0.0, "keyword": 0.0, "fuzzy": 0.0},
        "keywords": {
            "essential_hit":  [],
            "essential_miss": [],
            "supporting_hit": [],
        },
    }


# ─────────────────────────────────────────────────────────
# Standalone Demo
# Run from the PROJECT ROOT:  python -m app.scoring.technical
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":

    question = "What is Aerodynamics?"

    expected = (
        "Aerodynamics is the study of how air moves around objects "
        "and how forces like lift and drag affect motion. It is widely "
        "used in aircraft, cars, and engineering design to improve "
        "performance and efficiency."
    )

    essential  = ["aerodynamics", "lift", "drag", "air"]
    supporting = ["fluid", "pressure", "efficiency", "aircraft", "airflow"]

    test_answers = [
        (
            "Aerodynamics is the study of how air moves around objects "
            "and how forces like lift and drag affect motion.",
            "Near perfect answer",
        ),
        (
            "Aerodynamics is basically the reason some things cut through "
            "air smoothly while others struggle against it. The better the "
            "airflow, the faster and more efficient the movement feels.",
            "Different words, same concept",
        ),
        (
            "Aerodynamics is about airflow and how planes fly.",
            "Partially correct",
        ),
        (
            "It is used in aircraft design.",
            "Too vague",
        ),
        (
            "I don't know.",
            "Wrong answer",
        ),
        (
            "",
            "Empty answer (guard clause)",
        ),
    ]

    print("\n" + "=" * 65)
    print(f"  TECHNICAL DIMENSION — QUESTION: {question}")
    print("=" * 65)

    for student_ans, label in test_answers:
        result = score_technical(student_ans, expected, essential, supporting)

        print(f"\n  [{label}]")
        print(f"  Student  : {student_ans[:70] or '(empty)'}")
        print(f"  Score    : {round(result['score'] * 100, 1)}%  (dimension, 0–100)")
        print(f"  Breakdown: Semantic={result['breakdown']['semantic']}%  "
              f"Keyword={result['breakdown']['keyword']}%  "
              f"Fuzzy={result['breakdown']['fuzzy']}%")
        print(f"  Missed   : {result['keywords']['essential_miss']}")
        print("-" * 65)
