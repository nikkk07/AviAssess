"""
Confidence scorer (the shared "delivery" dimension).

WHY this module exists:
    The other dimensions read the TEXT of an answer. This one reads HOW the
    answer was delivered — eye contact, facial composure, vocal steadiness, and
    pace. All of that is measured CLIENT-SIDE in the browser (face/eye tracking,
    audio analysis) and arrives as a lightweight `behavioral_features` JSON blob.
    The backend never sees raw video or audio — only these numbers — which is
    what keeps us inside the free-tier memory budget.

    This module aggregates those features into a single 0-1 confidence score. It
    does NOT assign a band, write feedback, or convert to a percentage — the
    router (engine.py) owns presentation.

CRITICAL — graceful degradation:
    Confidence is the only dimension that can be UNMEASURABLE. A candidate may
    answer in text only (no camera, no mic), or the camera may be off while the
    mic is on. We never fabricate a confidence number from missing data:

      * No features at all        → score is None (not 0). "Not measured" is not
                                     the same as "scored zero". The router
                                     redistributes confidence's weight to the
                                     dimensions it actually has.
      * Some sub-features missing  → score from only the sub-metrics present,
                                     RE-NORMALIZING their weights among those
                                     available, and report which ones counted.

Sub-metric weights (named constants; sum to 1.0 when ALL are present):
    Eye contact        → 0.35  (eye_contact_percent, already 0-1)
    Facial confidence  → 0.25  (facial_confidence_score, already 0-1)
    Voice steadiness   → 0.25  (derived from pitch_variance)
    Speaking rate      → 0.15  (derived from speaking_rate_wpm)
"""


# ─────────────────────────────────────────────────────────
# Sub-metric weights — sum to 1.0 when every sub-metric is present.
# When some are missing, the present ones are re-normalized to sum to 1.0.
# ─────────────────────────────────────────────────────────
EYE_CONTACT_WEIGHT       = 0.35
FACIAL_CONFIDENCE_WEIGHT = 0.25
VOICE_STEADINESS_WEIGHT  = 0.25
SPEAKING_RATE_WEIGHT     = 0.15

# Source feature keys in the behavioral_features blob.
KEY_EYE_CONTACT   = "eye_contact_percent"
KEY_FACIAL        = "facial_confidence_score"
KEY_PITCH_VAR     = "pitch_variance"
KEY_SPEAKING_RATE = "speaking_rate_wpm"

# ─────────────────────────────────────────────────────────
# Voice steadiness: lower pitch variance = steadier voice = more confident.
# Map steadiness = 1 - pitch_variance, clamped to [0, 1]. The variance the
# browser sends is already a small normalized number; the clamp guards against
# noisy values outside the expected range. (Real cutoffs: Phase 8.)
# ─────────────────────────────────────────────────────────
STEADINESS_MIN = 0.0
STEADINESS_MAX = 1.0

# ─────────────────────────────────────────────────────────
# Speaking rate: full credit inside the ideal band, falling off linearly on
# either side (too slow reads as hesitant; too fast reads as nervous/rushed).
# ─────────────────────────────────────────────────────────
IDEAL_WPM_LOW    = 110
IDEAL_WPM_HIGH   = 150
WPM_FALLOFF_RANGE = 60   # WPM beyond the band over which the score decays to 0


def score_confidence(behavioral_features: dict | None) -> dict:
    """
    Aggregate browser behavioral features into one confidence score.

    Args:
        behavioral_features : The client-side feature blob, or None when the
                              answer was text-only.

    Returns:
        {
          "score": float in [0.0, 1.0] OR None when nothing was measurable,
          "breakdown": {                 # each sub-metric: 0-1, or None if absent
              "eye_contact":      float | None,
              "facial_confidence":float | None,
              "voice_steadiness": float | None,
              "speaking_rate":    float | None,
          },
          "measured": list[str],         # which sub-metrics actually contributed
        }
    """

    # ─────────────────────────────────────────────
    # Guard: no features at all → confidence is unmeasurable, not zero.
    # ─────────────────────────────────────────────
    if not behavioral_features:
        return _unmeasured()

    # ─────────────────────────────────────────────
    # Compute each sub-metric ONLY if its source feature is present.
    # A value of None (key present but explicitly null) also counts as absent.
    # ─────────────────────────────────────────────
    eye_contact       = _eye_contact_score(behavioral_features)
    facial_confidence = _facial_confidence_score(behavioral_features)
    voice_steadiness  = _voice_steadiness_score(behavioral_features)
    speaking_rate     = _speaking_rate_score(behavioral_features)

    breakdown = {
        "eye_contact":       eye_contact,
        "facial_confidence": facial_confidence,
        "voice_steadiness":  voice_steadiness,
        "speaking_rate":     speaking_rate,
    }

    # ─────────────────────────────────────────────
    # Collect present sub-metrics with their nominal weights.
    # ─────────────────────────────────────────────
    components = [
        ("eye_contact",       eye_contact,       EYE_CONTACT_WEIGHT),
        ("facial_confidence", facial_confidence, FACIAL_CONFIDENCE_WEIGHT),
        ("voice_steadiness",  voice_steadiness,  VOICE_STEADINESS_WEIGHT),
        ("speaking_rate",     speaking_rate,     SPEAKING_RATE_WEIGHT),
    ]
    present = [(name, value, weight) for name, value, weight in components
               if value is not None]

    # ─────────────────────────────────────────────
    # Guard: features blob existed but held none of the keys we use.
    # Still unmeasurable.
    # ─────────────────────────────────────────────
    if not present:
        return _unmeasured()

    # ─────────────────────────────────────────────
    # Weighted average, RE-NORMALIZED across only the present sub-metrics so
    # their weights sum to 1.0. This is the graceful-degradation core: a
    # voice-only answer is scored purely on voice, not penalized for the
    # missing camera.
    # ─────────────────────────────────────────────
    total_weight   = sum(weight for _, _, weight in present)
    weighted_value = sum(value * weight for _, value, weight in present)
    score = weighted_value / total_weight

    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "breakdown": breakdown,
        "measured": [name for name, _, _ in present],
    }


# ─────────────────────────────────────────────────────────
# Sub-metric helpers — each returns a 0-1 float, or None if its
# source feature is absent / null.
# ─────────────────────────────────────────────────────────

def _eye_contact_score(features: dict) -> float | None:
    """eye_contact_percent is already a 0-1 confidence proxy; just clamp it."""
    value = features.get(KEY_EYE_CONTACT)
    if value is None:
        return None
    return _clamp01(float(value))


def _facial_confidence_score(features: dict) -> float | None:
    """facial_confidence_score is already a 0-1 score; just clamp it."""
    value = features.get(KEY_FACIAL)
    if value is None:
        return None
    return _clamp01(float(value))


def _voice_steadiness_score(features: dict) -> float | None:
    """Lower pitch variance → steadier voice → higher confidence."""
    variance = features.get(KEY_PITCH_VAR)
    if variance is None:
        return None
    steadiness = 1.0 - float(variance)
    return max(STEADINESS_MIN, min(STEADINESS_MAX, steadiness))


def _speaking_rate_score(features: dict) -> float | None:
    """Full credit inside the ideal WPM band, decaying linearly outside it."""
    wpm = features.get(KEY_SPEAKING_RATE)
    if wpm is None:
        return None

    wpm = float(wpm)
    if IDEAL_WPM_LOW <= wpm <= IDEAL_WPM_HIGH:
        return 1.0
    if wpm < IDEAL_WPM_LOW:
        deficit = IDEAL_WPM_LOW - wpm
        return max(0.0, 1.0 - deficit / WPM_FALLOFF_RANGE)
    # wpm > IDEAL_WPM_HIGH
    excess = wpm - IDEAL_WPM_HIGH
    return max(0.0, 1.0 - excess / WPM_FALLOFF_RANGE)


def _clamp01(value: float) -> float:
    """Clamp a float to [0, 1] — guards against noisy out-of-range inputs."""
    return max(0.0, min(1.0, value))


def _unmeasured() -> dict:
    """Confidence could not be measured — score is None, not 0."""
    return {
        "score": None,
        "breakdown": {
            "eye_contact":       None,
            "facial_confidence": None,
            "voice_steadiness":  None,
            "speaking_rate":     None,
        },
        "measured": [],
    }


# ─────────────────────────────────────────────────────────
# Standalone Demo
# Run from the PROJECT ROOT:  python -m app.scoring.confidence
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":

    test_cases = [
        (
            {
                "eye_contact_percent": 0.86,
                "facial_confidence_score": 0.80,
                "pitch_variance": 0.12,
                "speaking_rate_wpm": 132,
            },
            "Full features — strong, composed delivery",
        ),
        (
            {
                "eye_contact_percent": 0.28,
                "facial_confidence_score": 0.35,
                "pitch_variance": 0.62,
                "speaking_rate_wpm": 180,
            },
            "Full features — weak/nervous (shaky voice, too fast)",
        ),
        (
            {
                "pitch_variance": 0.20,
                "speaking_rate_wpm": 125,
            },
            "Partial — voice only, camera off (no face)",
        ),
        (
            None,
            "None — text-only answer (unmeasurable)",
        ),
    ]

    print("\n" + "=" * 72)
    print("  CONFIDENCE DIMENSION")
    print("=" * 72)

    for features, label in test_cases:
        result = score_confidence(features)
        b = result["breakdown"]

        score_display = (
            "None (not measured)" if result["score"] is None
            else f"{round(result['score'] * 100, 1)}%  (dimension, 0–100)"
        )

        print(f"\n  [{label}]")
        print(f"  Score    : {score_display}")
        print(f"  Breakdown: eye={b['eye_contact']}  face={b['facial_confidence']}  "
              f"voice={b['voice_steadiness']}  rate={b['speaking_rate']}")
        print(f"  Measured : {result['measured']}")
        print("-" * 72)
