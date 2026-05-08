"""
AeroEval Hybrid Scoring Engine.

Combines all three scoring signals into one final score.

Signal weights:
    Semantic similarity  → 60%  (meaning comprehension)
    Keyword coverage     → 25%  (critical concept coverage)
    Fuzzy similarity     → 15%  (typo tolerance, completeness)

Why these weights?
    Semantic is the strongest signal — it captures actual understanding.
    Keyword ensures critical terms are present — semantic alone can be fooled.
    Fuzzy is a supporting signal — catches edge cases, handles typos.

These weights are a starting point. After real student testing,
you'll tune them based on observed scoring quality.
"""

from semantic import semantic_similarity
from keywords import keyword_coverage
from fuzzy import fuzzy_similarity


# ─────────────────────────────────────────────────────────
# Signal weights — must sum to 1.0
# Change these to tune scoring behavior
# ─────────────────────────────────────────────────────────
WEIGHT_SEMANTIC = 0.60
WEIGHT_KEYWORD  = 0.25
WEIGHT_FUZZY    = 0.15


def score_answer(
    student_answer: str,
    expected_answer: str,
    essential_keywords: list[str],
    supporting_keywords: list[str],
) -> dict:
    """
    Score a student's answer against the expected answer.

    Args:
        student_answer      : Raw text from student
        expected_answer     : Reference answer from dataset
        essential_keywords  : Must-have concepts
        supporting_keywords : Nice-to-have concepts

    Returns:
        Full scoring result dict with score, band,
        breakdown, feedback, and keyword details.
    """

    # ─────────────────────────────────────────────
    # Guard: empty answer
    # ─────────────────────────────────────────────
    if not student_answer or not student_answer.strip():
        return _empty_result()

    # ─────────────────────────────────────────────
    # Run all three scorers independently
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
    # Weighted combination
    # ─────────────────────────────────────────────
    raw_score = (
        (WEIGHT_SEMANTIC * semantic_score) +
        (WEIGHT_KEYWORD  * keyword_score)  +
        (WEIGHT_FUZZY    * fuzzy_score)
    )

    # ─────────────────────────────────────────────
    # Length penalty
    # Penalize one-word or very short answers
    # to detailed questions.
    #
    # If the expected answer is 15+ words
    # but student wrote fewer than 4 words,
    # they definitely didn't explain properly.
    # ─────────────────────────────────────────────
    student_word_count = len(student_answer.strip().split())
    expected_word_count = len(expected_answer.strip().split())

    if student_word_count < 4 and expected_word_count >= 15:
        raw_score *= 0.5  # 50% penalty for too-short answers

    # Clamp final score to [0, 1]
    final_score = max(0.0, min(1.0, raw_score))

    # Convert to percentage
    final_percentage = round(final_score * 100, 1)

    # ─────────────────────────────────────────────
    # Score band
    # ─────────────────────────────────────────────
    band = _get_band(final_percentage)

    # ─────────────────────────────────────────────
    # Feedback message
    # ─────────────────────────────────────────────
    feedback = _generate_feedback(
        score=final_percentage,
        band=band,
        essential_hit=keyword_result["essential_hit"],
        essential_miss=keyword_result["essential_miss"],
        supporting_hit=keyword_result["supporting_hit"],
    )

    return {
        # Main result
        "score": final_percentage,
        "band": band,
        "feedback": feedback,

        # Score breakdown (useful for frontend display)
        "breakdown": {
            "semantic": round(semantic_score * 100, 1),
            "keyword":  round(keyword_score  * 100, 1),
            "fuzzy":    round(fuzzy_score    * 100, 1),
        },

        # Keyword details (useful for feedback)
        "keywords": {
            "essential_hit":  keyword_result["essential_hit"],
            "essential_miss": keyword_result["essential_miss"],
            "supporting_hit": keyword_result["supporting_hit"],
        },
    }


def _get_band(score: float) -> str:
    """Map numeric score to performance band."""
    if score >= 85:
        return "excellent"
    elif score >= 70:
        return "good"
    elif score >= 50:
        return "partial"
    elif score >= 30:
        return "weak"
    else:
        return "incorrect"


def _generate_feedback(
    score: float,
    band: str,
    essential_hit: list[str],
    essential_miss: list[str],
    supporting_hit: list[str],
) -> str:
    """
    Generate a human-readable feedback message.

    Good feedback tells students:
    1. Overall how they did
    2. What they got right
    3. What they missed
    4. What to study
    """

    # Base message by band
    base_messages = {
        "excellent": "Excellent answer! You demonstrated strong understanding.",
        "good":      "Good answer. You covered the core concept well.",
        "partial":   "Partial understanding shown. Some key concepts were missed.",
        "weak":      "Your answer needs improvement. Review the core concepts.",
        "incorrect": "This answer does not address the question correctly.",
    }

    feedback = base_messages[band]

    # Add what they got right
    if essential_hit:
        hits = ", ".join(essential_hit)
        feedback += f" You correctly mentioned: {hits}."

    # Add what they missed — most valuable feedback
    if essential_miss:
        misses = ", ".join(essential_miss)
        feedback += f" Key concepts to review: {misses}."

    # Encourage depth if they got essentials but not supporting
    if essential_hit and not essential_miss and not supporting_hit:
        feedback += " Try to elaborate with more specific details."

    return feedback


def _empty_result() -> dict:
    """Return a zero-score result for empty answers."""
    return {
        "score": 0.0,
        "band": "incorrect",
        "feedback": "No answer was provided.",
        "breakdown": {"semantic": 0.0, "keyword": 0.0, "fuzzy": 0.0},
        "keywords": {
            "essential_hit": [],
            "essential_miss": [],
            "supporting_hit": [],
        },
    }


# ─────────────────────────────────────────────────────────
# Full Demo Test
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":

    question = "What is Aerodynamics?"

    expected = (
        "Aerodynamics is the study of how air moves around objects "
        "and how forces like lift and drag affect motion. It is widely "
        "used in aircraft, cars, and engineering design to improve "
        "performance and efficiency."
    )

    essential   = ["aerodynamics", "lift", "drag", "air"]
    supporting  = ["fluid", "pressure", "efficiency", "aircraft", "airflow"]

    test_answers = [
        (
            "Aerodynamics is the study of how air moves around objects "
            "and how forces like lift and drag affect motion.",
            "Near perfect answer"
        ),
        (
            "Aerodynamics is basically the reason some things cut through "
            "air smoothly while others struggle against it. The better the "
            "airflow, the faster and more efficient the movement feels.",
            "Your example — different words, same concept"
        ),
        (
            "Aerodynamics is about airflow and how planes fly.",
            "Partially correct"
        ),
        (
            "It is used in aircraft design.",
            "Too vague"
        ),
        (
            "I don't know.",
            "Wrong answer"
        ),
    ]

    print("\n" + "=" * 65)
    print(f"  QUESTION: {question}")
    print("=" * 65)

    for student_ans, label in test_answers:
        result = score_answer(student_ans, expected, essential, supporting)

        print(f"\n  [{label}]")
        print(f"  Student  : {student_ans[:70]}")
        print(f"  Score    : {result['score']}%  ({result['band'].upper()})")
        print(f"  Breakdown: Semantic={result['breakdown']['semantic']}%  "
              f"Keyword={result['breakdown']['keyword']}%  "
              f"Fuzzy={result['breakdown']['fuzzy']}%")
        print(f"  Feedback : {result['feedback']}")
        print(f"  Missed   : {result['keywords']['essential_miss']}")
        print("-" * 65)