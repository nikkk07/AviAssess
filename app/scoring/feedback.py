"""
Feedback builder — turns raw dimension results into human-readable guidance.

WHY this is its own module:
    Scoring and explaining are different jobs. The dimension scorers
    (technical / behavioral / communication / confidence) produce NUMBERS and
    raw detail blocks. This module does NO scoring — it only reads those
    already-computed details and composes the structured feedback a candidate
    sees. Keeping it separate means we can reword feedback without touching any
    scoring logic, and the router (engine.py) stays focused on blending.

    Feedback is structured (a dict of named sections), not one paragraph, so the
    frontend can render each part — overall verdict, content, communication,
    delivery — in its own place.
"""

from app.scoring.communication import MIN_IDEAL_WORDS


# ─────────────────────────────────────────────────────────
# A sub-metric at or below this (on a 0-1 scale) is considered to have
# "dragged the score down" and earns a specific note.
# ─────────────────────────────────────────────────────────
LOW_SUBMETRIC_THRESHOLD = 0.60

# Overall verdict by band.
BAND_MESSAGES = {
    "excellent": "Excellent response — strong across the board.",
    "good":      "Good response. Solid overall, with a little room to refine.",
    "partial":   "Partial response. The essentials are only partly there.",
    "weak":      "Weak response. Several core areas need work.",
    "incorrect": "This response does not adequately address the question.",
}

SKIPPED_MESSAGE = "This question was skipped and scored 0."
CONFIDENCE_UNMEASURED_MESSAGE = (
    "Confidence not measured — enable camera and microphone for this feedback."
)


def build_feedback(
    question_type: str,
    band: str,
    dimension_scores: dict,
    technical_or_relevance_detail: dict | None,
    communication_detail: dict | None,
    confidence_detail: dict | None,
    was_skipped: bool,
) -> dict:
    """
    Compose structured feedback from already-computed dimension details.

    Convention for the detail arguments:
        * None        → that scorer was NOT run (e.g. skip/blank short-circuit),
                         so no note is produced for it.
        * a dict      → that scorer ran; its detail block drives the note.
                         (confidence_detail may itself carry score=None, which
                         produces the "not measured" note.)

    Returns a dict of named sections, e.g.:
        {
          "overall": "...",
          "technical" | "relevance": "...",
          "communication": "...",
          "confidence": "...",
        }
    """

    # ─────────────────────────────────────────────
    # Skipped: one clear line, nothing else to say.
    # ─────────────────────────────────────────────
    if was_skipped:
        return {"overall": SKIPPED_MESSAGE}

    feedback = {"overall": BAND_MESSAGES.get(band, "")}

    # ─────────────────────────────────────────────
    # Content dimension — technical (concepts) or relevance (themes).
    # ─────────────────────────────────────────────
    if technical_or_relevance_detail is not None:
        is_technical = question_type == "technical"
        key = "technical" if is_technical else "relevance"
        feedback[key] = _content_note(
            is_technical,
            technical_or_relevance_detail.get("keywords", {}),
        )

    # ─────────────────────────────────────────────
    # Communication dimension.
    # ─────────────────────────────────────────────
    if communication_detail is not None:
        feedback["communication"] = _communication_note(communication_detail)

    # ─────────────────────────────────────────────
    # Confidence dimension (may be "not measured").
    # ─────────────────────────────────────────────
    if confidence_detail is not None:
        feedback["confidence"] = _confidence_note(confidence_detail)

    return feedback


def _content_note(is_technical: bool, keywords: dict) -> str:
    """List the concepts/themes the candidate covered and missed."""
    hit  = keywords.get("essential_hit", [])
    miss = keywords.get("essential_miss", [])
    label = "concepts" if is_technical else "themes"

    parts = []
    if hit:
        parts.append(f"You covered: {', '.join(hit)}.")
    if miss:
        parts.append(f"Missing key {label}: {', '.join(miss)}.")
    if not hit and not miss:
        parts.append(f"No target {label} were configured for this question.")
    return " ".join(parts)


def _communication_note(detail: dict) -> str:
    """Call out the sub-metrics that dragged communication down."""
    breakdown = detail["breakdown"]
    stats     = detail["stats"]

    notes = []

    if stats["filler_count"] > 0 and breakdown["filler"] < LOW_SUBMETRIC_THRESHOLD:
        notes.append(f"Cut down on filler words ({stats['filler_count']} detected).")

    if breakdown["structure"] < LOW_SUBMETRIC_THRESHOLD:
        notes.append("Structure your answer into a few connected sentences.")

    if breakdown["length"] < LOW_SUBMETRIC_THRESHOLD:
        if stats["word_count"] < MIN_IDEAL_WORDS:
            notes.append("Your answer was too brief — develop your points further.")
        else:
            notes.append("Your answer ran long — aim to be more concise.")

    if breakdown["vocabulary"] < LOW_SUBMETRIC_THRESHOLD:
        notes.append("Vary your word choice to avoid repetition.")

    if breakdown["fluency"] < LOW_SUBMETRIC_THRESHOLD:
        notes.append("Aim for smoother, more even sentence lengths.")

    if not notes:
        notes.append("Clear, well-structured communication.")
    return " ".join(notes)


def _confidence_note(detail: dict) -> str:
    """Comment on delivery — but only on sub-metrics actually measured."""
    if detail.get("score") is None:
        return CONFIDENCE_UNMEASURED_MESSAGE

    breakdown = detail["breakdown"]
    measured  = detail["measured"]
    notes = []

    if "eye_contact" in measured and breakdown["eye_contact"] < LOW_SUBMETRIC_THRESHOLD:
        notes.append("Maintain more consistent eye contact.")

    if "facial_confidence" in measured and breakdown["facial_confidence"] < LOW_SUBMETRIC_THRESHOLD:
        notes.append("Project a calmer, more assured expression.")

    if "voice_steadiness" in measured and breakdown["voice_steadiness"] < LOW_SUBMETRIC_THRESHOLD:
        notes.append("Steady your voice — reduce nervous pitch swings.")

    if "speaking_rate" in measured and breakdown["speaking_rate"] < LOW_SUBMETRIC_THRESHOLD:
        notes.append("Adjust your pace toward a steady 110–150 words per minute.")

    if not notes:
        notes.append("Confident, composed delivery.")
    return " ".join(notes)


# ─────────────────────────────────────────────────────────
# Standalone Demo
# Run from the PROJECT ROOT:  python -m app.scoring.feedback
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":

    # Synthetic detail blocks (shaped exactly like the scorers' real output) —
    # this module does no scoring, so we feed it representative numbers.
    technical_detail = {
        "keywords": {
            "essential_hit":  ["aerodynamics", "air"],
            "essential_miss": ["lift", "drag"],
            "supporting_hit": ["airflow"],
        },
    }
    weak_comm_detail = {
        "breakdown": {"vocabulary": 1.0, "structure": 0.4, "length": 0.6,
                      "filler": 0.0, "fluency": 0.92},
        "stats": {"word_count": 24, "sentence_count": 1, "filler_count": 9},
    }
    strong_comm_detail = {
        "breakdown": {"vocabulary": 1.0, "structure": 1.0, "length": 1.0,
                      "filler": 1.0, "fluency": 1.0},
        "stats": {"word_count": 71, "sentence_count": 4, "filler_count": 0},
    }
    weak_conf_detail = {
        "score": 0.36,
        "breakdown": {"eye_contact": 0.28, "facial_confidence": 0.35,
                      "voice_steadiness": 0.38, "speaking_rate": 0.5},
        "measured": ["eye_contact", "facial_confidence", "voice_steadiness", "speaking_rate"],
    }
    unmeasured_conf_detail = {
        "score": None,
        "breakdown": {"eye_contact": None, "facial_confidence": None,
                      "voice_steadiness": None, "speaking_rate": None},
        "measured": [],
    }

    cases = [
        ("technical", "partial", technical_detail, weak_comm_detail, weak_conf_detail, False,
         "Technical, weak comms + nervous delivery"),
        ("behavioral", "good",
         {"keywords": {"essential_hit": ["passion for flying", "career goal"],
                       "essential_miss": ["the airline industry"], "supporting_hit": []}},
         strong_comm_detail, unmeasured_conf_detail, False,
         "Behavioral, strong comms, confidence NOT measured"),
        ("technical", "skipped", None, None, None, True,
         "Skipped"),
    ]

    print("\n" + "=" * 72)
    print("  FEEDBACK BUILDER")
    print("=" * 72)
    for qtype, band, content, comm, conf, skipped, label in cases:
        fb = build_feedback(qtype, band, {}, content, comm, conf, skipped)
        print(f"\n  [{label}]")
        for section, text in fb.items():
            print(f"    {section:14}: {text}")
        print("-" * 72)
