"""
AviAssess scoring service — FastAPI application.

This ties the whole service together:
    auth.py     → verifies the caller's login JWT (get_current_user_id)
    session.py  → stateless session tokens + stratified question selection
    data/       → loads the question pool and admin config
    scoring/    → score_response() does the per-answer scoring
    reports/    → aggregates the final session report
    data/models → the request/response contract (with anti-cheat QuestionPublic)

Free-tier note: a SINGLE gunicorn/uvicorn worker. The sentence-transformer is
loaded ONCE at startup (lifespan) so the first real request doesn't pay the
cold-start cost, and the question pool / config are held in memory.
"""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, status
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import jwt
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import get_current_user_id
from app.config import settings
from app.data.loader import load_config, load_questions, save_config
from app.data.models import (
    AdminConfigRequest,
    AdminConfigResponse,
    AnswerScoreResponse,
    AnswerSubmitRequest,
    HealthResponse,
    QuestionPublic,
    SessionCompleteRequest,
    SessionCompleteResponse,
    SessionStartRequest,
    SessionStartResponse,
)
from app.reports.generator import aggregate_report
from app.scoring.engine import score_response
from app.scoring.semantic import get_model
from app.storage import db
from app.session import (
    SessionError,
    create_session_token,
    question_in_session,
    select_questions,
    verify_session_token,
)


# ─────────────────────────────────────────────────────────
# Startup / shutdown: load the model + data ONCE.
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the sentence-transformer so the first request is fast.
    get_model()
    app.state.model_loaded = True

    # Hold the question pool, config, and an id→question index in memory.
    app.state.questions = load_questions()
    app.state.config = load_config()
    app.state.question_index = {q["id"]: q for q in app.state.questions}

    yield

    # Close the DB pool if persistence ever opened one (no-op when DB-less).
    await db.close_pool()


logger = logging.getLogger("aviassess")

app = FastAPI(title="AviAssess Scoring Service", lifespan=lifespan)


# ─────────────────────────────────────────────────────────
# CORS — explicit origins only, never "*".
# ─────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────
# Uniform error bodies — every HTTPException is reshaped to ErrorResponse
# ({error, message, details}) so clients get one consistent envelope.
# ─────────────────────────────────────────────────────────
def api_error(status_code: int, error: str, message: str, details: dict | None = None) -> HTTPException:
    """Build an HTTPException whose detail is an ErrorResponse-shaped dict."""
    return HTTPException(
        status_code=status_code,
        detail={"error": error, "message": message, "details": details},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        content = detail
    else:
        # FastAPI/Starlette built-ins (e.g. missing auth header) carry a string.
        content = {"error": "http_error", "message": str(detail), "details": None}
    return JSONResponse(status_code=exc.status_code, content=content)


# ─────────────────────────────────────────────────────────
# 1. Health — public, no auth.
# ─────────────────────────────────────────────────────────
@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        model_loaded=getattr(app.state, "model_loaded", False),
    )


# ─────────────────────────────────────────────────────────
# 1b. DEV-ONLY fixed-code login (OFF by default — see config.py).
# Swaps a fixed 6-digit code for a real, server-minted access token so devs
# don't hand-mint JWTs. The JWT_SECRET_KEY never leaves the server. When
# disabled the route 404s, so prod looks like it doesn't exist.
# ─────────────────────────────────────────────────────────
class DevLoginRequest(BaseModel):
    code: str


@app.post("/api/dev/login")
async def dev_login(body: DevLoginRequest):
    # When disabled, 404 so prod looks like the route doesn't exist.
    if not settings.DEV_LOGIN_ENABLED:
        raise api_error(status.HTTP_404_NOT_FOUND, "not_found", "Not found")
    if not settings.DEV_LOGIN_CODE or body.code != settings.DEV_LOGIN_CODE:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "invalid_code", "Incorrect dev code")
    token = jwt.encode(
        {"sub": settings.DEV_LOGIN_USER_ID, "type": "access",
         "exp": datetime.now(timezone.utc) + timedelta(hours=24)},
        settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}


# ─────────────────────────────────────────────────────────
# 2. Start a session.
# ─────────────────────────────────────────────────────────
@app.post("/api/session/start", response_model=SessionStartResponse)
async def session_start(
    body: SessionStartRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> SessionStartResponse:
    cfg = app.state.config

    # Request filters override config filters when provided.
    enabled_types = cfg.get("enabled_question_types") or None
    enabled_categories = cfg.get("enabled_categories") or None
    if body.category:
        enabled_categories = [body.category]

    try:
        questions = select_questions(
            app.state.questions,
            cfg["num_questions"],
            enabled_types=enabled_types,
            enabled_categories=enabled_categories,
        )
    except ValueError as exc:
        raise api_error(status.HTTP_400_BAD_REQUEST, "no_questions", str(exc))

    token = create_session_token([q["id"] for q in questions], user_id)

    # ANTI-CHEAT: map FULL questions → QuestionPublic, which structurally cannot
    # carry answer/keywords. The full dicts never leave this function.
    public_questions = [
        QuestionPublic(
            id=q["id"],
            question=q["question"],
            question_type=q["question_type"],
            category=q["category"],
            time_limit_seconds=q.get("time_limit_seconds", cfg["default_time_limit_seconds"]),
            order=q["order"],
        )
        for q in questions
    ]

    return SessionStartResponse(
        session_token=token,
        questions=public_questions,
        issued_at=datetime.now(timezone.utc),
    )


# ─────────────────────────────────────────────────────────
# 3. Submit one answer for scoring.
# ─────────────────────────────────────────────────────────
@app.post("/api/answer/submit", response_model=AnswerScoreResponse)
async def answer_submit(
    body: AnswerSubmitRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> AnswerScoreResponse:
    # Verify the token belongs to this user AND that the question was issued.
    try:
        belongs = question_in_session(body.session_token, user_id, body.question_id)
    except SessionError as exc:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "invalid_session", str(exc))

    if not belongs:
        raise api_error(
            status.HTTP_403_FORBIDDEN, "question_not_in_session",
            "This question was not part of your session.",
        )

    # Need the FULL question (answer + keywords) — never exposed to the client.
    full_question = app.state.question_index.get(body.question_id)
    if full_question is None:
        # Token said it was issued but the pool no longer has it (e.g. dataset
        # changed mid-session). Treat as gone.
        raise api_error(
            status.HTTP_404_NOT_FOUND, "question_not_found",
            "The question could not be found.",
        )

    features = (
        body.behavioral_features.model_dump()
        if body.behavioral_features is not None else None
    )

    result = score_response(
        question=full_question,
        student_answer_text=body.student_answer_text,
        behavioral_features=features,
        was_skipped=body.was_skipped,
    )

    return AnswerScoreResponse(**result)


# ─────────────────────────────────────────────────────────
# 4. Complete a session → final report.
# ─────────────────────────────────────────────────────────
@app.post("/api/session/complete", response_model=SessionCompleteResponse)
async def session_complete(
    body: SessionCompleteRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> SessionCompleteResponse:
    # Confirm the token is the caller's (we don't trust client-sent results blindly,
    # but at minimum the session token must be valid for this user).
    try:
        verify_session_token(body.session_token, user_id)
    except SessionError as exc:
        raise api_error(status.HTTP_401_UNAUTHORIZED, "invalid_session", str(exc))

    results = [r.model_dump() for r in body.results]
    report = aggregate_report(results)

    # Persist the finished interview — but ONLY if a DATABASE_URL is configured.
    # When it's unset we skip silently and the service stays fully DB-less.
    # A DB hiccup must NOT cost the candidate their already-computed report, so a
    # save failure is logged and swallowed rather than turned into a 500.
    if db.is_configured():
        try:
            await db.save_interview(
                user_id=user_id,
                results=results,
                total_score=report["total_score"],
                overall_band=report["overall_band"],
                num_questions=report["num_questions"],
                num_skipped=report["num_skipped"],
            )
        except Exception:  # noqa: BLE001 — best-effort persistence, never fatal
            logger.exception("Failed to persist interview for user %s", user_id)

    return SessionCompleteResponse(**report)


# ─────────────────────────────────────────────────────────
# 5. Interview history — the caller's own past interviews.
# ─────────────────────────────────────────────────────────
@app.get("/api/interviews")
async def list_interviews(
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> list[dict]:
    # DB-less deployment: no persistence, so the history is simply empty.
    if not db.is_configured():
        return []
    return await db.get_user_interviews(user_id)


# ─────────────────────────────────────────────────────────
# 6. Admin config — read (any authed user) / write (admins only).
# ─────────────────────────────────────────────────────────
@app.get("/api/admin/config", response_model=AdminConfigResponse)
async def admin_config_get(
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> AdminConfigResponse:
    return AdminConfigResponse(**app.state.config)


@app.post("/api/admin/config", response_model=AdminConfigResponse)
async def admin_config_set(
    body: AdminConfigRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> AdminConfigResponse:
    if str(user_id) not in settings.admin_user_ids_set:
        raise api_error(
            status.HTTP_403_FORBIDDEN, "not_admin",
            "You are not authorized to change configuration.",
        )

    cfg = body.model_dump()
    if cfg.get("enabled_categories") is None:
        cfg["enabled_categories"] = []  # normalize None → [] for storage

    save_config(cfg)            # local-dev persistence (R2 in Phase 5)
    app.state.config = cfg      # update in-memory immediately
    return AdminConfigResponse(**cfg)
