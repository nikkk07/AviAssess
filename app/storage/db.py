"""
Results persistence (Phase 5) — Supabase Postgres via raw asyncpg.

WHY this module exists:
    When a candidate finishes an interview we want to KEEP the result, linked to
    their user_id (the "sub" UUID from the login JWT), so they can see their
    history later. We store it in the SAME Supabase Postgres the auth service
    already uses — no new datastore, no new service.

DELIBERATE constraints (this service runs in 512MB and the fit was just
validated — do NOT regress it):
    * asyncpg + raw, PARAMETERIZED SQL ONLY. No SQLAlchemy, no supabase-py, no
      ORM. Every value goes through a $N placeholder — never string interpolation
      — so SQL injection is structurally impossible here.
    * OPTIONAL. If DATABASE_URL is unset, is_configured() is False and callers
      skip persistence entirely; the service still runs DB-less.

CONNECTION model:
    A tiny, lazily-created pool (min 0 → nothing is opened until the first save).
    Two notes that matter for the Supabase POOLER (port 6543, PgBouncer):
      * statement_cache_size=0 — PgBouncer transaction pooling does NOT support
        the server-side prepared statements asyncpg caches by default; caching
        them would raise "prepared statement does not exist" on reuse.
      * The pool is closed on app shutdown (see app.main lifespan); on a free
        instance that spins down when idle, that just means the next cold start
        lazily builds a fresh pool.
"""

import json
import uuid
from typing import Optional

import asyncpg

from app.config import settings


# Lazily-initialized shared pool. Stays None until the first DB call needs it,
# so a DB-less deployment never opens a socket.
_pool: Optional[asyncpg.Pool] = None


def is_configured() -> bool:
    """True only when a DATABASE_URL is set — the on/off switch for persistence."""
    return bool(settings.DATABASE_URL)


async def _get_pool() -> asyncpg.Pool:
    """
    Return the shared pool, creating it on first use.

    min_size=0 keeps idle memory/connection-slot usage at zero until something
    actually persists. statement_cache_size=0 makes us safe behind the Supabase
    PgBouncer pooler (transaction mode). Caller must have checked is_configured().
    """
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=0,
            max_size=5,
            statement_cache_size=0,  # required for PgBouncer transaction pooling
        )
    return _pool


async def close_pool() -> None:
    """Tear down the pool on app shutdown. No-op if it was never created."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ─────────────────────────────────────────────────────────
# Writes
# ─────────────────────────────────────────────────────────
async def save_interview(
    user_id: uuid.UUID,
    results: list[dict],
    total_score: float,
    overall_band: str,
    num_questions: int,
    num_skipped: int,
) -> uuid.UUID:
    """
    Persist one completed interview + its per-answer rows, all in one transaction
    (so we never end up with a header row and no answers, or vice-versa).

    Args:
        user_id:       the candidate's UUID (JWT "sub"); stored as-is, no FK.
        results:       per-answer result dicts (AnswerScoreResponse.model_dump()
                       shape): question_id, question_type, final_score, band,
                       dimensions, feedback, was_skipped.
        total_score, overall_band, num_questions, num_skipped: the rolled-up
                       report figures from aggregate_report().

    Returns:
        The new interview's UUID (the parent row's primary key).
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Parent row — RETURNING hands us the generated id without a 2nd query.
            interview_id = await conn.fetchval(
                """
                INSERT INTO interviews
                    (user_id, total_score, overall_band, num_questions, num_skipped)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                user_id, total_score, overall_band, num_questions, num_skipped,
            )

            # Child rows — one per answer. dimensions/feedback are dicts, so we
            # json.dumps them and cast text → jsonb in SQL ($5::jsonb, $6::jsonb).
            if results:
                rows = [
                    (
                        interview_id,
                        r.get("question_id"),
                        r.get("question_type"),
                        r.get("final_score"),
                        r.get("band"),
                        json.dumps(r.get("dimensions")),
                        json.dumps(r.get("feedback")),
                        bool(r.get("was_skipped", False)),
                    )
                    for r in results
                ]
                await conn.executemany(
                    """
                    INSERT INTO interview_answers
                        (interview_id, question_id, question_type, final_score,
                         band, dimensions, feedback, was_skipped)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)
                    """,
                    rows,
                )

    return interview_id


# ─────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────
async def get_user_interviews(user_id: uuid.UUID) -> list[dict]:
    """
    Return this user's interviews, most recent first, for their history view.

    Header rows only (no per-answer detail) — that keeps the payload small and is
    all a history list needs. A detail endpoint can join interview_answers later.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        records = await conn.fetch(
            """
            SELECT id, created_at, total_score, overall_band,
                   num_questions, num_skipped
            FROM interviews
            WHERE user_id = $1
            ORDER BY created_at DESC
            """,
            user_id,
        )

    # asyncpg Records aren't JSON-serializable as-is; map to plain dicts and
    # stringify the UUID/timestamp so FastAPI can serialize them cleanly.
    return [
        {
            "id": str(rec["id"]),
            "created_at": rec["created_at"].isoformat(),
            "total_score": rec["total_score"],
            "overall_band": rec["overall_band"],
            "num_questions": rec["num_questions"],
            "num_skipped": rec["num_skipped"],
        }
        for rec in records
    ]
