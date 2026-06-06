"""
Pydantic v2 request/response schemas — the browser <-> backend contract.

These models are the single source of truth for every payload the scoring API
accepts or returns. FastAPI uses them to validate input, serialize output, and
generate the OpenAPI docs.

ANTI-CHEAT (read before editing QuestionPublic):
    The question objects sent to the browser must NEVER carry the expected
    answer or the scoring keywords. If they did, a candidate could read them
    straight out of the network response and "answer" perfectly. We enforce this
    STRUCTURALLY: QuestionPublic simply has no field for those secrets, so there
    is no code path that can serialize them to the client by accident. The full
    question (with answer + keywords) lives only server-side / in storage and is
    never wrapped in QuestionPublic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Shared literal — the three scoring modes.
QuestionType = Literal["technical", "behavioral", "situational"]


# ─────────────────────────────────────────────────────────
# 1. Behavioral features (client-side measured, sent per answer)
# ─────────────────────────────────────────────────────────
class BehavioralFeatures(BaseModel):
    """
    Lightweight delivery signals measured IN THE BROWSER (face/eye tracking,
    audio analysis). The backend never sees raw video/audio — only these numbers.

    EVERY field is Optional on purpose: cameras and mics may be off, and browser
    estimates are noisy. confidence.py degrades gracefully on None/partial data,
    so we keep bounds light (ge=0 where it makes physical sense) and add NO upper
    bounds — out-of-range values are clamped downstream, not rejected here.
    """

    eye_contact_percent: Optional[float] = Field(
        default=None, ge=0, examples=[0.78],
        description="Fraction of time looking at camera (≈0-1).",
    )
    facial_confidence_score: Optional[float] = Field(
        default=None, ge=0, examples=[0.71],
        description="Browser-estimated facial composure (≈0-1).",
    )
    avg_pitch_hz: Optional[float] = Field(
        default=None, ge=0, examples=[142.5],
        description="Average vocal pitch in Hz.",
    )
    pitch_variance: Optional[float] = Field(
        default=None, ge=0, examples=[0.18],
        description="Normalized pitch variance; lower = steadier voice.",
    )
    speaking_rate_wpm: Optional[float] = Field(
        default=None, ge=0, examples=[124],
        description="Speaking rate in words per minute.",
    )
    total_pause_seconds: Optional[float] = Field(
        default=None, ge=0, examples=[4.2],
        description="Total silent pause time during the answer.",
    )
    filler_word_count: Optional[int] = Field(
        default=None, ge=0, examples=[3],
        description="Count of filler words detected.",
    )
    filler_words_detected: Optional[list[str]] = Field(
        default=None, examples=[["basically", "um"]],
        description="The filler words/phrases actually detected.",
    )


# ─────────────────────────────────────────────────────────
# 2. Question as exposed to the browser (SAFE fields ONLY)
# ─────────────────────────────────────────────────────────
class QuestionPublic(BaseModel):
    """
    The ONLY shape a question takes when leaving the backend toward the client.

    Deliberately has NO `answer`, NO `essential_keywords`, NO `supporting_keywords`.
    See the ANTI-CHEAT note at the top of this module — the omission is the
    enforcement.
    """

    id: str = Field(examples=["q025"])
    question: str = Field(examples=["What is aerodynamics?"])
    question_type: QuestionType = Field(examples=["technical"])
    category: str = Field(examples=["aerodynamics"])
    time_limit_seconds: int = Field(examples=[90])
    order: int = Field(examples=[1], description="1-based position in the session.")


# ─────────────────────────────────────────────────────────
# 3-4. Session start
# ─────────────────────────────────────────────────────────
class SessionStartRequest(BaseModel):
    """Begin a session. All filters optional — omit to draw from everything."""

    category: Optional[str] = Field(default=None, examples=["aerodynamics"])
    difficulty: Optional[str] = Field(default=None, examples=["intermediate"])


class SessionStartResponse(BaseModel):
    """The questions to ask + the signed token binding this question set."""

    session_token: str = Field(
        description="HMAC-signed token encoding the issued question_ids + expiry.",
        examples=["eyJxX2lkcyI6Wy4uLl0sImV4cCI6MTcwMH0.<sig>"],
    )
    questions: list[QuestionPublic]
    issued_at: datetime


# ─────────────────────────────────────────────────────────
# 5. Answer submission
# ─────────────────────────────────────────────────────────
class AnswerSubmitRequest(BaseModel):
    """One answer submitted for scoring."""

    session_token: str
    question_id: str = Field(examples=["q025"])
    student_answer_text: str = Field(examples=["Aerodynamics is the study of..."])
    time_taken_seconds: int = Field(ge=0, examples=[87])
    was_skipped: bool = Field(default=False)
    behavioral_features: Optional[BehavioralFeatures] = Field(default=None)


# ─────────────────────────────────────────────────────────
# 6-8. Answer scoring result (mirrors engine.score_response() exactly)
# ─────────────────────────────────────────────────────────
class DimensionScores(BaseModel):
    """
    Per-dimension scores as percentages. Each is Optional because:
      * technical XOR relevance is populated (depends on question_type),
      * confidence is None when there were no behavioral features to measure.
    """

    technical: Optional[float] = Field(default=None, examples=[87.4])
    relevance: Optional[float] = Field(default=None, examples=[None])
    communication: Optional[float] = Field(default=None, examples=[87.0])
    confidence: Optional[float] = Field(default=None, examples=[85.4])


class FeedbackDetail(BaseModel):
    """
    Structured feedback — mirrors what feedback.build_feedback() emits: an
    `overall` verdict plus whichever per-dimension notes apply. keywords_hit /
    keywords_missed are optional structured extras for the frontend to render.
    """

    overall: str = Field(examples=["Excellent response — strong across the board."])
    technical: Optional[str] = Field(default=None)
    relevance: Optional[str] = Field(default=None)
    communication: Optional[str] = Field(default=None)
    confidence: Optional[str] = Field(default=None)
    keywords_hit: Optional[list[str]] = Field(default=None, examples=[["lift", "drag"]])
    keywords_missed: Optional[list[str]] = Field(default=None, examples=[["thrust"]])


class AnswerScoreResponse(BaseModel):
    """
    The scored result for one answer. This MUST mirror the dict returned by
    engine.score_response() field-for-field.
    """

    question_id: Optional[str] = Field(examples=["q025"])
    question_type: Optional[QuestionType] = Field(examples=["technical"])
    was_skipped: bool
    final_score: float = Field(examples=[86.8])
    band: str = Field(examples=["excellent"])
    dimensions: DimensionScores
    weights_used: dict[str, float] = Field(
        examples=[{"technical": 0.5, "communication": 0.25, "confidence": 0.25}],
        description="Actual per-dimension weights after any redistribution.",
    )
    feedback: FeedbackDetail


# ─────────────────────────────────────────────────────────
# 9-10. Session completion / final report
# ─────────────────────────────────────────────────────────
class PerQuestionSummary(BaseModel):
    """A slim per-question row for the final report."""

    question_id: Optional[str] = Field(examples=["q025"])
    final_score: float = Field(examples=[86.8])
    band: str = Field(examples=["excellent"])


class SessionCompleteRequest(BaseModel):
    """
    Finalize a session. The frontend accumulates each answer's score result and
    sends them all back here to aggregate the final report.
    """

    session_token: str
    results: list[AnswerScoreResponse]


class SessionCompleteResponse(BaseModel):
    """The aggregated end-of-session report."""

    total_score: float = Field(examples=[81.5])
    overall_band: str = Field(examples=["good"])
    num_questions: int = Field(ge=0, examples=[10])
    num_skipped: int = Field(ge=0, examples=[1])
    per_question: list[PerQuestionSummary]
    summary: str = Field(examples=["Strong overall, with room to sharpen technical depth."])


# ─────────────────────────────────────────────────────────
# 11. Admin configuration
# ─────────────────────────────────────────────────────────
class AdminConfigRequest(BaseModel):
    """Admin-set session configuration (persisted in R2)."""

    num_questions: int = Field(ge=1, examples=[10])
    default_time_limit_seconds: int = Field(ge=1, examples=[90])
    enabled_question_types: list[str] = Field(
        examples=[["technical", "behavioral", "situational"]],
    )
    enabled_categories: Optional[list[str]] = Field(
        default=None, examples=[["aerodynamics", "navigation"]],
    )


class AdminConfigResponse(AdminConfigRequest):
    """Echoes the stored config back after a successful update."""
    # Inherits every field from the request — the response IS the saved config.


# ─────────────────────────────────────────────────────────
# 12. Error envelope (MATCHES the auth service's error shape exactly)
# ─────────────────────────────────────────────────────────
class ErrorResponse(BaseModel):
    """Uniform error body shared with the auth service."""

    error: str = Field(examples=["invalid_token"])
    message: str = Field(examples=["Invalid or expired token"])
    details: Optional[dict] = Field(default=None)


# ─────────────────────────────────────────────────────────
# 13. Health check
# ─────────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    """Public uptime probe."""

    status: str = Field(examples=["ok"])
    model_loaded: bool = Field(examples=[True])

    # The field name "model_loaded" starts with "model_", which collides with
    # Pydantic's protected namespace; silence that warning explicitly.
    model_config = ConfigDict(protected_namespaces=())


# ─────────────────────────────────────────────────────────
# Standalone validation demo
# Run from the PROJECT ROOT:  python -m app.data.models
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":

    features = BehavioralFeatures(
        eye_contact_percent=0.78, facial_confidence_score=0.71,
        avg_pitch_hz=142.5, pitch_variance=0.18, speaking_rate_wpm=124,
        total_pause_seconds=4.2, filler_word_count=3,
        filler_words_detected=["basically", "um"],
    )

    question = QuestionPublic(
        id="q025", question="What is aerodynamics?", question_type="technical",
        category="aerodynamics", time_limit_seconds=90, order=1,
    )

    start_resp = SessionStartResponse(
        session_token="signed.token.here",
        questions=[question],
        issued_at=datetime.now(timezone.utc),
    )

    submit = AnswerSubmitRequest(
        session_token="signed.token.here", question_id="q025",
        student_answer_text="Aerodynamics is the study of how air moves...",
        time_taken_seconds=87, was_skipped=False, behavioral_features=features,
    )

    score = AnswerScoreResponse(
        question_id="q025", question_type="technical", was_skipped=False,
        final_score=86.8, band="excellent",
        dimensions=DimensionScores(technical=87.4, communication=87.0, confidence=85.4),
        weights_used={"technical": 0.5, "communication": 0.25, "confidence": 0.25},
        feedback=FeedbackDetail(
            overall="Excellent response — strong across the board.",
            technical="You covered: aerodynamics, lift, drag, air.",
            communication="Clear, well-structured communication.",
            confidence="Confident, composed delivery.",
            keywords_hit=["aerodynamics", "lift", "drag", "air"],
            keywords_missed=[],
        ),
    )

    complete = SessionCompleteResponse(
        total_score=81.5, overall_band="good", num_questions=2, num_skipped=1,
        per_question=[PerQuestionSummary(question_id="q025", final_score=86.8, band="excellent")],
        summary="Strong overall, with room to sharpen technical depth.",
    )

    admin = AdminConfigResponse(
        num_questions=10, default_time_limit_seconds=90,
        enabled_question_types=["technical", "behavioral", "situational"],
        enabled_categories=["aerodynamics", "navigation"],
    )

    error = ErrorResponse(error="invalid_token", message="Invalid or expired token")
    health = HealthResponse(status="ok", model_loaded=True)

    samples = {
        "BehavioralFeatures": features,
        "QuestionPublic": question,
        "SessionStartRequest": SessionStartRequest(category="aerodynamics"),
        "SessionStartResponse": start_resp,
        "AnswerSubmitRequest": submit,
        "AnswerScoreResponse": score,
        "SessionCompleteRequest": SessionCompleteRequest(
            session_token="signed.token.here", results=[score]),
        "SessionCompleteResponse": complete,
        "AdminConfigResponse": admin,
        "ErrorResponse": error,
        "HealthResponse": health,
    }

    print("\n" + "=" * 70)
    print("  MODEL VALIDATION — all instances constructed successfully")
    print("=" * 70)
    for name, model in samples.items():
        print(f"\n  {name}:")
        print(f"    {model.model_dump()}")

    # ── Anti-cheat structural check ──
    print("\n" + "=" * 70)
    leaky = {"answer", "essential_keywords", "supporting_keywords"}
    exposed = set(QuestionPublic.model_fields) & leaky
    if exposed:
        print(f"  [FAIL] QuestionPublic LEAKS secret fields: {exposed}")
    else:
        print("  [PASS] QuestionPublic exposes no answer/keyword fields (anti-cheat).")
    print("=" * 70)
