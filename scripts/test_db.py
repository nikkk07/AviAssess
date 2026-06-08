"""
Round-trip check for the Phase 5 results persistence (app/storage/db.py).

Behaviour:
    * DATABASE_URL set   → save a fake interview, read the user's history back,
      print it, and assert the just-saved interview shows up.
    * DATABASE_URL unset → print "DB not configured — skipping" and exit 0
      (so this is safe to run in a DB-less environment / CI).

config.py still requires JWT_SECRET_KEY and SESSION_SECRET to import (they have
no defaults), so set those too. Run from the PROJECT ROOT:

    SESSION_SECRET=dummy-session JWT_SECRET_KEY=dummy-jwt \
    DATABASE_URL='postgresql://...pooler...:6543/postgres' \
    python scripts/test_db.py
"""

import asyncio
import json
import os
import sys
import uuid

# Allow `python scripts/test_db.py` from the project root to import `app`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.storage import db


# A fake per-answer result in the AnswerScoreResponse.model_dump() shape that
# save_interview expects (one scored answer + one skipped).
FAKE_RESULTS = [
    {
        "question_id": "q025",
        "question_type": "technical",
        "was_skipped": False,
        "final_score": 86.8,
        "band": "excellent",
        "dimensions": {"technical": 87.4, "communication": 87.0, "confidence": 85.4},
        "weights_used": {"technical": 0.5, "communication": 0.25, "confidence": 0.25},
        "feedback": {
            "overall": "Excellent response — strong across the board.",
            "keywords_hit": ["lift", "drag"],
            "keywords_missed": [],
        },
    },
    {
        "question_id": "q031",
        "question_type": "behavioral",
        "was_skipped": True,
        "final_score": 0.0,
        "band": "skipped",
        "dimensions": {"relevance": None, "communication": None, "confidence": None},
        "weights_used": {},
        "feedback": {"overall": "Skipped — no answer provided."},
    },
]


async def run() -> None:
    user_id = uuid.uuid4()
    print(f"  Using fake user_id: {user_id}")

    interview_id = await db.save_interview(
        user_id=user_id,
        results=FAKE_RESULTS,
        total_score=43.4,
        overall_band="partial",
        num_questions=2,
        num_skipped=1,
    )
    print(f"  [OK] saved interview: {interview_id}")

    history = await db.get_user_interviews(user_id)
    print("\n  get_user_interviews() returned:")
    print(json.dumps(history, indent=2))

    saved_ids = {row["id"] for row in history}
    assert str(interview_id) in saved_ids, "saved interview not found in history!"
    print("\n  [PASS] round-trip OK — saved interview read back successfully.")

    await db.close_pool()


def main() -> None:
    if not db.is_configured():
        print("DB not configured — skipping")
        sys.exit(0)

    print("=" * 70)
    print("  DB ROUND-TRIP TEST")
    print("=" * 70)
    asyncio.run(run())
    print("=" * 70)


if __name__ == "__main__":
    main()
