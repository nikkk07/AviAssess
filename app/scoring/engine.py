"""
AviAssess Scoring Engine — the ROUTER.

WHY this module exists:
    Different question types are scored differently, and every answer blends a
    content dimension with two shared dimensions (communication, confidence).
    Rather than letting any one scorer own the final number, this module stays
    thin: it DISPATCHES to the right content scorer, ALWAYS runs the shared
    scorers, BLENDS them with the per-type weighting scheme, applies the
    cross-cutting rules (skip / blank → 0), bands the FINAL score, and hands the
    raw details to feedback.py for the explanation.

The blend — and why the "general rule" matters:
    Base weights per question type:
        technical            → technical 0.50, communication 0.25, confidence 0.25
        behavioral/situational → relevance 0.35, communication 0.40, confidence 0.25

    Confidence is the one dimension that can be None (text-only answer, no
    camera/mic). We never treat "not measured" as zero. Instead the final score
    is a weighted average over ONLY the dimensions that have a score:

        final = Σ(score·weight  for present dims) / Σ(weight  for present dims)

    When confidence is None its weight drops out and is re-normalized
    proportionally across the dimensions we DO have. "weights_used" in the
    result reports the actual post-redistribution weights for transparency.
"""

from app.scoring.technical import score_technical
from app.scoring.behavioral import score_behavioral
from app.scoring.communication import score_communication
from app.scoring.confidence import score_confidence
from app.scoring.feedback import build_feedback


# ─────────────────────────────────────────────────────────
# Score bands — applied to the FINAL blended score (0–100).
# ─────────────────────────────────────────────────────────
BAND_EXCELLENT = 85
BAND_GOOD      = 70
BAND_PARTIAL   = 50
BAND_WEAK      = 30

# ─────────────────────────────────────────────────────────
# Base dimension weights (must sum to 1.0 within each mode).
# ─────────────────────────────────────────────────────────
# Technical mode: a known-answer question.
TECH_W_TECHNICAL     = 0.50
TECH_W_COMMUNICATION = 0.25
TECH_W_CONFIDENCE    = 0.25

# Relevance mode: behavioral / situational (no known answer).
REL_W_RELEVANCE      = 0.35
REL_W_COMMUNICATION  = 0.40
REL_W_CONFIDENCE     = 0.25

# Question types that have NO expected answer → relevance mode.
RELEVANCE_TYPES = ("behavioral", "situational")


def score_response(
    question: dict,
    student_answer_text: str,
    behavioral_features: dict | None,
    was_skipped: bool,
) -> dict:
    """
    Score one submitted answer end-to-end and assemble the full result.

    Args:
        question            : Dataset question dict (id, question_type, answer,
                              essential_keywords, supporting_keywords, ...).
        student_answer_text : The candidate's answer text.
        behavioral_features : Browser feature blob, or None for a text-only answer.
        was_skipped         : True if the candidate skipped this question.

    Returns:
        The full result dict (see module docstring / return shape below).
    """

    question_id   = question.get("id")
    question_type = question.get("question_type")

    # ─────────────────────────────────────────────
    # 1. SHORT-CIRCUIT: skipped, or blank/whitespace answer.
    #    No scorer runs — we never score features for a non-answer.
    #    Skip enforces band "skipped"; a blank-but-not-skipped answer is
    #    simply "incorrect".
    # ─────────────────────────────────────────────
    is_blank = not student_answer_text or not student_answer_text.strip()
    if was_skipped or is_blank:
        band = "skipped" if was_skipped else "incorrect"
        return _build_result(
            question_id=question_id,
            question_type=question_type,
            was_skipped=was_skipped,
            final_percentage=0.0,
            band=band,
            dimension_percentages={
                "technical": None, "relevance": None,
                "communication": None, "confidence": None,
            },
            weights_used={},
            feedback=build_feedback(
                question_type, band, {}, None, None, None, was_skipped,
            ),
        )

    text                = student_answer_text
    essential_keywords  = question.get("essential_keywords", [])
    supporting_keywords = question.get("supporting_keywords", [])

    # ─────────────────────────────────────────────
    # 2. DISPATCH the content dimension by question_type.
    #    `mode` decides BOTH the content scorer and the weight set.
    # ─────────────────────────────────────────────
    expected_answer = question.get("answer")

    if question_type == "technical" and expected_answer is not None:
        content_detail = score_technical(
            text, expected_answer, essential_keywords, supporting_keywords,
        )
        mode = "technical"

    elif question_type == "technical" and expected_answer is None:
        # DATA ERROR: a technical question must have an expected answer.
        # Degrade gracefully — score it on relevance (theme coverage) instead
        # of crashing. It reports under the "relevance" dimension.
        content_detail = score_behavioral(
            text, essential_keywords, supporting_keywords,
        )
        mode = "relevance"

    else:
        # behavioral / situational — and any unknown type defaults here, since
        # relevance scoring needs no expected answer and never crashes.
        content_detail = score_behavioral(
            text, essential_keywords, supporting_keywords,
        )
        mode = "relevance"

    # ─────────────────────────────────────────────
    # 3. ALWAYS run the shared dimensions.
    # ─────────────────────────────────────────────
    communication_detail = score_communication(text)
    confidence_detail    = score_confidence(behavioral_features)

    # ─────────────────────────────────────────────
    # 4. BLEND with the general (re-normalizing) rule.
    # ─────────────────────────────────────────────
    if mode == "technical":
        dims = [
            ("technical",     content_detail["score"],       TECH_W_TECHNICAL),
            ("communication", communication_detail["score"], TECH_W_COMMUNICATION),
            ("confidence",    confidence_detail["score"],     TECH_W_CONFIDENCE),
        ]
    else:
        dims = [
            ("relevance",     content_detail["score"],       REL_W_RELEVANCE),
            ("communication", communication_detail["score"], REL_W_COMMUNICATION),
            ("confidence",    confidence_detail["score"],     REL_W_CONFIDENCE),
        ]

    # Only dimensions with a real score participate; confidence=None drops out.
    present = [(name, score, weight) for name, score, weight in dims
               if score is not None]
    total_weight = sum(weight for _, _, weight in present)

    final_score = sum(score * weight for _, score, weight in present) / total_weight

    # ─────────────────────────────────────────────
    # 5. Convert to percentages (presentation only; math above stayed 0-1).
    # ─────────────────────────────────────────────
    final_percentage = round(final_score * 100, 1)

    dimension_percentages = {
        "technical": None, "relevance": None,
        "communication": None, "confidence": None,
    }
    for name, score, _ in dims:
        dimension_percentages[name] = (
            round(score * 100, 1) if score is not None else None
        )

    # Actual weights after redistribution (sum to 1.0 across present dims).
    weights_used = {
        name: round(weight / total_weight, 4) for name, _, weight in present
    }

    # ─────────────────────────────────────────────
    # 6. BAND the FINAL blended score.
    # ─────────────────────────────────────────────
    band = _get_band(final_percentage)

    # ─────────────────────────────────────────────
    # 7. FEEDBACK from the raw details (feedback.py does no scoring).
    # ─────────────────────────────────────────────
    feedback = build_feedback(
        question_type=question_type,
        band=band,
        dimension_scores=dimension_percentages,
        technical_or_relevance_detail=content_detail,
        communication_detail=communication_detail,
        confidence_detail=confidence_detail,
        was_skipped=False,
    )

    return _build_result(
        question_id=question_id,
        question_type=question_type,
        was_skipped=False,
        final_percentage=final_percentage,
        band=band,
        dimension_percentages=dimension_percentages,
        weights_used=weights_used,
        feedback=feedback,
    )


def _get_band(score: float) -> str:
    """Map a 0–100 score to a performance band."""
    if score >= BAND_EXCELLENT:
        return "excellent"
    if score >= BAND_GOOD:
        return "good"
    if score >= BAND_PARTIAL:
        return "partial"
    if score >= BAND_WEAK:
        return "weak"
    return "incorrect"


def _build_result(
    question_id,
    question_type,
    was_skipped: bool,
    final_percentage: float,
    band: str,
    dimension_percentages: dict,
    weights_used: dict,
    feedback: dict,
) -> dict:
    """Assemble the canonical result dict (single source of the return shape)."""
    return {
        "question_id":   question_id,
        "question_type": question_type,
        "was_skipped":   was_skipped,
        "final_score":   final_percentage,
        "band":          band,
        "dimensions":    dimension_percentages,
        "weights_used":  weights_used,
        "feedback":      feedback,
    }


# ─────────────────────────────────────────────────────────
# Full Demo — covers every path
# Run from the PROJECT ROOT:  python -m app.scoring.engine
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":

    technical_question = {
        "id": "q001",
        "question_type": "technical",
        "question": "What is aerodynamics?",
        "answer": (
            "Aerodynamics is the study of how air moves around objects and how "
            "forces like lift and drag affect motion. It is widely used in "
            "aircraft design to improve performance and efficiency."
        ),
        "essential_keywords": ["aerodynamics", "lift", "drag", "air"],
        "supporting_keywords": ["airflow", "pressure", "efficiency"],
    }

    behavioral_question = {
        "id": "q050",
        "question_type": "behavioral",
        "question": "Tell me about yourself — why aviation?",
        "answer": None,
        "essential_keywords": [
            "passion for flying", "the airline industry",
            "hands-on aviation experience", "career goal",
        ],
        "supporting_keywords": [
            "working with a crew", "commitment to safety", "travel", "career",
        ],
    }

    situational_question = {
        "id": "q075",
        "question_type": "situational",
        "question": "A passenger becomes aggressive during boarding. What do you do?",
        "answer": None,
        "essential_keywords": [
            "stay calm", "ensure safety", "follow procedure", "de-escalate",
        ],
        "supporting_keywords": ["communicate clearly", "involve the crew"],
    }

    strong_technical_answer = (
        "Aerodynamics is the study of how air moves around objects and how "
        "forces such as lift and drag influence their motion. Engineers apply "
        "it to aircraft design so that airflow stays smooth and efficient."
    )
    strong_behavioral_answer = (
        "Ever since I was a child I have been fascinated by flight and the "
        "science of how aircraft stay in the air. I spent two summers working "
        "as part of a ground crew, which taught me how a team keeps operations "
        "running safely. My ambition is to grow into a captain and build a long "
        "career in the airline industry."
    )
    situational_answer = (
        "First I would stay calm and speak to the passenger in a clear, "
        "respectful tone to de-escalate the situation. My priority is the "
        "safety of everyone on board, so I would follow the airline's procedure "
        "and involve the rest of the crew if the behaviour continued."
    )

    full_features = {
        "eye_contact_percent": 0.84,
        "facial_confidence_score": 0.78,
        "pitch_variance": 0.14,
        "speaking_rate_wpm": 128,
    }
    voice_only_features = {
        "pitch_variance": 0.22,
        "speaking_rate_wpm": 120,
    }

    cases = [
        ("1. Technical + full features",
         technical_question, strong_technical_answer, full_features, False),
        ("2. Technical + confidence None (text-only)",
         technical_question, strong_technical_answer, None, False),
        ("3. Behavioral + full features",
         behavioral_question, strong_behavioral_answer, full_features, False),
        ("4. Situational + partial features (voice only)",
         situational_question, situational_answer, voice_only_features, False),
        ("5. Skipped",
         technical_question, "", None, True),
        ("6. Empty answer text, not skipped",
         technical_question, "   ", full_features, False),
    ]

    print("\n" + "=" * 74)
    print("  FULL ROUTER — score_response()")
    print("=" * 74)

    for label, q, answer, features, skipped in cases:
        result = score_response(q, answer, features, skipped)

        print(f"\n  [{label}]")
        print(f"  question_id : {result['question_id']}  ({result['question_type']})")
        print(f"  final_score : {result['final_score']}%   band: {result['band'].upper()}")
        print(f"  dimensions  : {result['dimensions']}")
        print(f"  weights_used: {result['weights_used']}")
        print(f"  feedback    :")
        for section, text in result["feedback"].items():
            print(f"      {section:14}: {text}")
        print("-" * 74)
