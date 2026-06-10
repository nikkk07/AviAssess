"""
Stateless session management for the AviAssess scoring service.

WHY stateless:
    Render's free tier gives us a single small worker with no durable session
    store. So we keep NO server-side session state — instead, the signed token
    IS the session. When a session starts we pick the questions, embed their IDs
    in an HMAC-signed JWT, and hand it to the browser. On every answer submit we
    re-verify that token: a valid signature proves we issued exactly this set of
    question IDs to exactly this user, and that it hasn't expired.

    The token is signed with SESSION_SECRET — deliberately a DIFFERENT secret
    from the auth service's JWT_SECRET_KEY (see config.py), so a login token can
    never be replayed as a session token or vice-versa.
"""

import random
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError

from app.config import settings


# Session tokens are HMAC-signed JWTs.
SESSION_ALGORITHM = "HS256"


class SessionError(Exception):
    """Raised when a session token cannot be trusted (bad sig/expiry/user/shape)."""


# ─────────────────────────────────────────────────────────
# Phase A1 taxonomy — screen-facing labels → backend selection values.
#
# These are the ONLY place the frontend's vocabulary is translated to the
# question-bank's vocabulary. Keep all mapping here so the bank schema and the
# endpoint never need to know about screen labels.
# ─────────────────────────────────────────────────────────

# interview_type (screen) → backend question_type(s) to draw from.
INTERVIEW_TYPE_MAP: dict[str, list[str]] = {
    "hr_personal": ["behavioral", "situational"],
    "technical": ["technical"],
}

# Recognised interview types that are NOT wired yet. The endpoint answers these
# with a clean "not yet available" response — never questions, never a 500.
INTERVIEW_TYPES_NOT_AVAILABLE: frozenset[str] = frozenset(
    {"sim_check_debrief", "group_exercise"}
)

# difficulty (screen band) → backend difficulty value used in the question bank.
DIFFICULTY_MAP: dict[str, str] = {
    "friendly": "basic",       # easiest band
    "standard": "intermediate",  # middle band
    "tough": "advanced",       # hardest band
}

# Backend difficulty values that may be passed through as-is (legacy callers
# sent these directly, before the friendly/standard/tough labels existed).
_BACKEND_DIFFICULTIES: frozenset[str] = frozenset({"basic", "intermediate", "advanced"})


def resolve_interview_type(interview_type: str | None) -> tuple[str, list[str] | None]:
    """
    Translate a screen `interview_type` into backend question_types.

    Returns a (status, types) tuple:
        ("ok", [...])            → constrain selection to these question_types
        ("not_available", None)  → recognised but not wired yet (endpoint → 422)
        ("no_filter", None)      → absent OR unknown → do not constrain by type

    LENIENT by design: an unrecognised value yields "no_filter" rather than an
    error, so a stray label from an evolving frontend can never 500/422.
    """
    if not interview_type:
        return ("no_filter", None)
    key = interview_type.strip().lower()
    if key in INTERVIEW_TYPE_MAP:
        return ("ok", INTERVIEW_TYPE_MAP[key])
    if key in INTERVIEW_TYPES_NOT_AVAILABLE:
        return ("not_available", None)
    return ("no_filter", None)


def resolve_difficulty(difficulty: str | None) -> str | None:
    """
    Translate a screen difficulty band into a backend difficulty value.

    friendly/standard/tough → basic/intermediate/advanced. Legacy backend values
    (basic/intermediate/advanced) pass through unchanged for backward
    compatibility. Anything else (or None) → None, i.e. no difficulty filter.
    """
    if not difficulty:
        return None
    key = difficulty.strip().lower()
    if key in DIFFICULTY_MAP:
        return DIFFICULTY_MAP[key]
    if key in _BACKEND_DIFFICULTIES:
        return key
    return None  # unknown → no filter (lenient)


def _question_matches(
    q: dict,
    *,
    type_filter: set[str] | None,
    category_filter: set[str] | None,
    difficulty: str | None,
    airline: str | None,
    aircraft_type: str | None,
    experience: str | None,
) -> bool:
    """
    Decide whether a single question survives the active filters.

    GRACEFUL, NON-STRICT matching:
      * type/category are hard scope (the interview's core shape).
      * difficulty and the airline/aircraft_type/experience TAGS are optional:
        a question that LACKS the tag (key absent or None) matches ANY requested
        value. This keeps the current untagged fixture fully usable — we never
        exclude a question merely for not carrying a tag.
    """
    if type_filter is not None and q.get("question_type") not in type_filter:
        return False
    if category_filter is not None and q.get("category") not in category_filter:
        return False

    # difficulty: untagged question (None/absent) is a wildcard match.
    if difficulty is not None:
        qd = q.get("difficulty")
        if qd is not None and qd != difficulty:
            return False

    # Optional tags: untagged question is a wildcard match for that dimension.
    for value, key in (
        (airline, "airline"),
        (aircraft_type, "aircraft_type"),
        (experience, "experience"),
    ):
        if value is not None:
            qv = q.get(key)
            if qv is not None and qv != value:
                return False

    return True


# ─────────────────────────────────────────────────────────
# 1. Stratified question selection
# ─────────────────────────────────────────────────────────
def select_questions(
    pool: list[dict],
    num_questions: int,
    enabled_types: list[str] | None = None,
    enabled_categories: list[str] | None = None,
    difficulty: str | None = None,
    airline: str | None = None,
    aircraft_type: str | None = None,
    experience: str | None = None,
) -> list[dict]:
    """
    Pick `num_questions` from `pool`, spread as evenly as possible across the
    available question_types, randomly within each type.

    Args:
        pool                : Full question dicts (with answer/keywords).
        num_questions       : How many to select.
        enabled_types       : If given, only these question_types are eligible.
        enabled_categories  : If given, only these categories are eligible.
        difficulty          : Backend difficulty value (already mapped from any
                              screen band). Untagged questions match any value.
        airline             : Optional airline tag filter (graceful — see below).
        aircraft_type       : Optional aircraft-type tag filter (graceful).
        experience          : Optional experience tag filter (graceful).

    GRACEFUL RELAXATION (never error on a thin combo, never return zero where a
    broader pool exists): if the filtered pool is smaller than `num_questions`,
    progressively drop the MOST SPECIFIC filters in this order until enough
    questions exist —
        aircraft_type → experience → airline → difficulty
    enabled_types / enabled_categories are the interview's core scope and are
    NEVER relaxed. If even the fully-relaxed pool is short, return as many as are
    available.

    Returns:
        FULL question dicts (copies), each with an added "order" (1..N).
        These are for SERVER-SIDE use — the endpoint maps them to QuestionPublic
        (dropping answer/keywords) before sending anything to the client.

    Raises:
        ValueError: if the pool is empty, num_questions < 1, or NOTHING matches
                    even after full relaxation (the type/category scope itself is
                    empty — a zero-question session is useless).
    """
    if not pool:
        raise ValueError("Question pool is empty — cannot start a session.")
    if num_questions < 1:
        raise ValueError("num_questions must be at least 1.")

    type_filter = set(enabled_types) if enabled_types else None
    category_filter = set(enabled_categories) if enabled_categories else None

    # Per-call RNG seeded from OS entropy — varied selections on re-practice
    # WITHOUT touching global random state (no global seeding).
    rng = random.Random()

    # ── Filter, relaxing the most specific dimensions until we have enough ──
    # Active relaxable filters, most-specific first. enabled_types/categories are
    # deliberately absent here: they are scope, not relaxable preferences.
    active = {
        "aircraft_type": aircraft_type,
        "experience": experience,
        "airline": airline,
        "difficulty": difficulty,
    }
    relax_order = ["aircraft_type", "experience", "airline", "difficulty"]

    while True:
        eligible = [
            q for q in pool
            if _question_matches(
                q,
                type_filter=type_filter,
                category_filter=category_filter,
                difficulty=active["difficulty"],
                airline=active["airline"],
                aircraft_type=active["aircraft_type"],
                experience=active["experience"],
            )
        ]
        if len(eligible) >= num_questions:
            break
        # Not enough — relax the next still-active specific filter, if any.
        for dim in relax_order:
            if active[dim] is not None:
                active[dim] = None
                break
        else:
            break  # nothing left to relax; take what we have

    if not eligible:
        raise ValueError("No questions match the requested type/category filters.")

    # ── Group by type and shuffle within each group ──
    by_type: dict[str, list[dict]] = defaultdict(list)
    for q in eligible:
        by_type[q.get("question_type")].append(q)
    for group in by_type.values():
        rng.shuffle(group)

    # Shuffle the type ORDER too, so the "remainder" questions (when num_questions
    # doesn't divide evenly) don't always favor the same alphabetical type.
    types = list(by_type.keys())
    rng.shuffle(types)

    total_available = len(eligible)
    target = min(num_questions, total_available)  # never crash on > available

    # ── Round-robin allocation: hand out one slot at a time to each type that
    # still has capacity. This yields the evenest possible spread and naturally
    # skips types that run out. ──
    counts = {t: 0 for t in types}
    remaining = target
    while remaining > 0:
        progressed = False
        for t in types:
            if remaining == 0:
                break
            if counts[t] < len(by_type[t]):
                counts[t] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break  # safety: target <= total_available, so this shouldn't trigger

    # ── Take the allocated count from each (already-shuffled) group ──
    selected: list[dict] = []
    for t in types:
        selected.extend(by_type[t][: counts[t]])

    # ── Shuffle final order, then assign 1..N. Copy each dict so we never
    # mutate the caller's pool with our "order" field. ──
    rng.shuffle(selected)
    return [{**q, "order": i} for i, q in enumerate(selected, start=1)]


# ─────────────────────────────────────────────────────────
# 2. Create a signed session token
# ─────────────────────────────────────────────────────────
def create_session_token(
    question_ids: list[str],
    user_id: uuid.UUID,
    ttl_seconds: int | None = None,
) -> str:
    """
    Sign the issued question IDs + owning user into a session JWT.

    Payload: {"qids": [...], "sub": str(user_id), "iat": ..., "exp": ...}
    Signed with SESSION_SECRET / HS256.
    """
    ttl = ttl_seconds if ttl_seconds is not None else settings.SESSION_TTL_SECONDS
    now = datetime.now(timezone.utc)

    payload = {
        "qids": list(question_ids),
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, settings.SESSION_SECRET, algorithm=SESSION_ALGORITHM)


# ─────────────────────────────────────────────────────────
# 3. Verify a session token
# ─────────────────────────────────────────────────────────
def verify_session_token(token: str, user_id: uuid.UUID) -> list[str]:
    """
    Verify a session token belongs to `user_id` and return its question IDs.

    Validates signature + expiry (via jwt.decode) and that the token was issued
    to THIS user — a token minted for user A must never work for user B.

    Raises:
        SessionError on any failure (bad signature, expired, user mismatch,
        malformed payload). One exception type, consistently.
    """
    try:
        payload = jwt.decode(
            token, settings.SESSION_SECRET, algorithms=[SESSION_ALGORITHM]
        )
    except JWTError:
        raise SessionError("Invalid or expired session token.")

    if payload.get("sub") != str(user_id):
        raise SessionError("Session token does not belong to this user.")

    qids = payload.get("qids")
    if not isinstance(qids, list):
        raise SessionError("Malformed session token (missing question IDs).")

    return qids


# ─────────────────────────────────────────────────────────
# 4. Membership check (used by /answer/submit)
# ─────────────────────────────────────────────────────────
def question_in_session(token: str, user_id: uuid.UUID, question_id: str) -> bool:
    """
    Verify the token for this user, then report whether `question_id` was part of
    the issued set.

    Propagates SessionError if the token itself is untrustworthy, so the endpoint
    can map that to a 401. A trusted token whose set simply doesn't contain the
    question returns False (the endpoint maps that to a 403).
    """
    qids = verify_session_token(token, user_id)  # raises SessionError on bad token
    return question_id in qids


# ─────────────────────────────────────────────────────────
# Standalone Test
# Run from the PROJECT ROOT (secrets MUST differ — see config.py validator):
#   SESSION_SECRET=dummy-session JWT_SECRET_KEY=dummy-jwt python -m app.session
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":

    from collections import Counter

    def _make_pool() -> list[dict]:
        """12 questions across all 3 types and a few categories."""
        rows = [
            ("q01", "technical",  "aerodynamics"),
            ("q02", "technical",  "aerodynamics"),
            ("q03", "technical",  "navigation"),
            ("q04", "technical",  "systems"),
            ("q05", "behavioral", "motivation"),
            ("q06", "behavioral", "teamwork"),
            ("q07", "behavioral", "motivation"),
            ("q08", "behavioral", "conflict"),
            ("q09", "situational","safety"),
            ("q10", "situational","safety"),
            ("q11", "situational","service"),
            ("q12", "situational","service"),
        ]
        return [
            {
                "id": qid,
                "question": f"Question {qid}?",
                "question_type": qtype,
                "answer": None if qtype != "technical" else f"Answer for {qid}",
                "essential_keywords": ["kw1", "kw2"],
                "supporting_keywords": ["kw3"],
                "category": cat,
                "difficulty": "intermediate",
                "time_limit_seconds": 90,
            }
            for qid, qtype, cat in rows
        ]

    USER_A = uuid.uuid4()
    USER_B = uuid.uuid4()
    pool = _make_pool()

    print("\n" + "=" * 66)
    print("  SESSION — SELECTION + TOKEN TESTS")
    print(f"  user A: {USER_A}")
    print("=" * 66)

    # ── select_questions ──
    selected = select_questions(pool, 6)
    orders = sorted(q["order"] for q in selected)
    dist = Counter(q["question_type"] for q in selected)

    print(f"\n  select_questions(pool, 6):")
    print(f"    count            : {len(selected)}  (expected 6)")
    print(f"    orders           : {orders}  (expected [1..6])")
    print(f"    type spread      : {dict(dist)}")
    print(f"    pool unmutated   : {'order' not in pool[0]}  (no 'order' leaked into pool)")
    assert len(selected) == 6
    assert orders == [1, 2, 3, 4, 5, 6]
    assert "order" not in pool[0]
    # Stratified: 6 across 3 types → 2 each.
    assert all(c == 2 for c in dist.values()), f"uneven spread: {dist}"
    print("    [PASS] count, order, and even stratification verified")

    # ── edge cases ──
    assert len(select_questions(pool, 100)) == len(pool)  # > available → all
    print("    [PASS] num_questions > available returns all available")
    try:
        select_questions([], 5)
        print("    [FAIL] empty pool did not raise")
    except ValueError:
        print("    [PASS] empty pool raises ValueError")

    # ── round trip ──
    qids = [q["id"] for q in selected]
    token = create_session_token(qids, USER_A)
    returned = verify_session_token(token, USER_A)
    print(f"\n  round trip:")
    print(f"    qids match       : {returned == qids}")
    assert returned == qids
    print("    [PASS] verify returns the issued qids")

    # ── reject cases ──
    print(f"\n  reject cases:")

    def expect_reject(label, fn):
        try:
            fn()
            print(f"    [FAIL] {label} -> unexpectedly accepted")
        except SessionError as exc:
            print(f"    [PASS] {label} -> rejected ({exc})")

    expect_reject("tampered token", lambda: verify_session_token(token + "x", USER_A))
    expect_reject(
        "expired token",
        lambda: verify_session_token(create_session_token(qids, USER_A, ttl_seconds=-1), USER_A),
    )
    expect_reject("wrong user", lambda: verify_session_token(token, USER_B))

    # ── membership ──
    in_set = question_in_session(token, USER_A, qids[0])
    not_in_set = question_in_session(token, USER_A, "q999")
    print(f"\n  question_in_session:")
    print(f"    present id ({qids[0]}) : {in_set}  (expected True)")
    print(f"    absent id  (q999)     : {not_in_set}  (expected False)")
    assert in_set is True and not_in_set is False
    print("    [PASS] membership True for issued id, False for non-issued id")

    print("\n" + "=" * 66)
    print("  ALL SESSION TESTS PASSED")
    print("=" * 66)
