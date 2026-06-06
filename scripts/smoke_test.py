"""
End-to-end smoke test for the AviAssess scoring API.

Walks the full candidate flow against the real app via FastAPI's TestClient
(in-process — no separate server needed). Endpoints require a valid access JWT,
so we mint a dev token here with the SAME JWT_SECRET_KEY / HS256 the auth service
uses, carrying {sub: <uuid>, type: "access", exp: future}.

Run from the PROJECT ROOT with DISTINCT secrets set:
    SESSION_SECRET=dummy-session JWT_SECRET_KEY=dummy-jwt python scripts/smoke_test.py
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Allow `python scripts/smoke_test.py` from the project root to import `app`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from jose import jwt

from app.main import app


def mint_access_token(user_id: uuid.UUID, expires_in_min: int = 15) -> str:
    """Mirror how the auth service issues an access token."""
    secret = os.environ["JWT_SECRET_KEY"]
    claims = {
        "sub": str(user_id),
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in_min),
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def show(label: str, response) -> dict:
    print(f"\n── {label}  [HTTP {response.status_code}] ──")
    body = response.json()
    print(json.dumps(body, indent=2))
    return body


def main() -> None:
    user_id = uuid.uuid4()
    token = mint_access_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    # `with` runs lifespan startup (loads model + data) and shutdown.
    with TestClient(app) as client:
        print("=" * 70)
        print(f"  SMOKE TEST — user {user_id}")
        print("=" * 70)

        # 1. Health (public).
        r = client.get("/api/health")
        body = show("GET /api/health", r)
        assert r.status_code == 200 and body["status"] == "ok"
        assert body["model_loaded"] is True

        # 2. Start a session.
        r = client.post("/api/session/start", json={}, headers=headers)
        body = show("POST /api/session/start", r)
        assert r.status_code == 200
        questions = body["questions"]
        assert len(questions) >= 1

        # ── ANTI-CHEAT ASSERTION: no secrets leaked to the client ──
        leaky_keys = {"answer", "essential_keywords", "supporting_keywords"}
        for q in questions:
            leaked = leaky_keys & set(q.keys())
            assert not leaked, f"LEAK! question {q['id']} exposed {leaked}"
        print("\n  [PASS] no answer/keywords leaked in returned questions")

        session_token = body["session_token"]
        first_q = questions[0]

        # 3a. Submit a real answer to the first question.
        submit_real = {
            "session_token": session_token,
            "question_id": first_q["id"],
            "student_answer_text": (
                "Aerodynamics is the study of how air moves around objects and how "
                "forces such as lift and drag affect their motion. Engineers apply it "
                "to aircraft design so airflow stays smooth and efficient."
            ),
            "time_taken_seconds": 72,
            "was_skipped": False,
            "behavioral_features": {
                "eye_contact_percent": 0.82,
                "facial_confidence_score": 0.76,
                "pitch_variance": 0.16,
                "speaking_rate_wpm": 128,
            },
        }
        r = client.post("/api/answer/submit", json=submit_real, headers=headers)
        body_real = show("POST /api/answer/submit  (real answer)", r)
        assert r.status_code == 200

        # 3b. Submit a skipped answer to the second question (or first if only one).
        skip_q = questions[1] if len(questions) > 1 else questions[0]
        submit_skip = {
            "session_token": session_token,
            "question_id": skip_q["id"],
            "student_answer_text": "",
            "time_taken_seconds": 0,
            "was_skipped": True,
            "behavioral_features": None,
        }
        r = client.post("/api/answer/submit", json=submit_skip, headers=headers)
        body_skip = show("POST /api/answer/submit  (skipped)", r)
        assert r.status_code == 200
        assert body_skip["final_score"] == 0.0 and body_skip["band"] == "skipped"

        # 4. Complete the session.
        complete_body = {
            "session_token": session_token,
            "results": [body_real, body_skip],
        }
        r = client.post("/api/session/complete", json=complete_body, headers=headers)
        body_complete = show("POST /api/session/complete", r)
        assert r.status_code == 200
        assert body_complete["num_questions"] == 2
        assert body_complete["num_skipped"] == 1

        # 5a. Invalid token → 401 invalid_token (frontend forces re-login).
        r = client.post(
            "/api/answer/submit", json=submit_real,
            headers={"Authorization": "Bearer not.a.valid.token"},
        )
        body_invalid = show("POST /api/answer/submit  (bad JWT → expect 401 invalid_token)", r)
        assert r.status_code == 401
        assert set(body_invalid.keys()) >= {"error", "message"}
        assert body_invalid["error"] == "invalid_token"

        # 5b. Expired token → 401 token_expired (frontend silently refreshes + retries).
        expired_token = mint_access_token(user_id, expires_in_min=-1)
        r = client.post(
            "/api/answer/submit", json=submit_real,
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        body_expired = show("POST /api/answer/submit  (expired JWT → expect 401 token_expired)", r)
        assert r.status_code == 401
        assert body_expired["error"] == "token_expired"

        # The two codes MUST differ so the frontend can branch.
        assert body_invalid["error"] != body_expired["error"]
        print(f"\n  [PASS] auth error codes differ: "
              f"{body_expired['error']} (refresh) vs {body_invalid['error']} (re-login)")

    print("\n" + "=" * 70)
    print("  ALL SMOKE-TEST STEPS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
