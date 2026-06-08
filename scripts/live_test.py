"""
End-to-end test against the LIVE deployed AviAssess scoring service.

Unlike scripts/smoke_test.py (in-process TestClient), this hits the real HTTPS
endpoint on Render and proves the full candidate flow + Supabase persistence work
in PRODUCTION.

What it needs from the environment:
    JWT_SECRET_KEY  (REQUIRED) — the SAME secret the live service verifies with,
                    so a token we mint here passes its auth. Never hardcoded.
    BASE_URL        (optional) — defaults to https://aviassess.onrender.com.

No new dependencies: uses httpx or requests if installed, else falls back to the
stdlib urllib. Tokens are minted with python-jose (already a project dep).

Run from the project root:
    JWT_SECRET_KEY='<live-secret>' python scripts/live_test.py
    # or against a different host:
    BASE_URL='https://staging.example.com' JWT_SECRET_KEY='<secret>' \
        python scripts/live_test.py
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt


# ─────────────────────────────────────────────────────────
# Config (all from env — never hardcode secrets).
# ─────────────────────────────────────────────────────────
BASE_URL = os.environ.get("BASE_URL", "https://aviassess.onrender.com").rstrip("/")

# A FIXED test-user UUID so repeated runs land under one identity (and so the
# persisted history is easy to reason about). Not a secret — just a label.
TEST_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

# Cold-start budget: a spun-down free instance can take 30-60s to wake, during
# which the router returns 502s / the request stalls. Retry health up to ~90s.
HEALTH_DEADLINE_SECONDS = 90
HEALTH_ATTEMPT_TIMEOUT = 30
HEALTH_RETRY_SLEEP = 4

# Normal per-request timeout once the service is awake (scoring loads a model
# per request path but it's warm by now; still allow generous headroom).
REQUEST_TIMEOUT = 60


# ─────────────────────────────────────────────────────────
# HTTP layer — pick whatever client is already installed.
# ─────────────────────────────────────────────────────────
class Resp:
    """Tiny uniform response wrapper across the three possible backends."""

    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self._text = text

    def json(self) -> dict:
        return json.loads(self._text)


def _select_client() -> str:
    try:
        import httpx  # noqa: F401
        return "httpx"
    except ImportError:
        pass
    try:
        import requests  # noqa: F401
        return "requests"
    except ImportError:
        pass
    return "urllib"


_CLIENT = _select_client()


def request(method: str, path: str, *, headers: dict | None = None,
            json_body: dict | None = None, timeout: float = REQUEST_TIMEOUT) -> Resp:
    """
    Issue one HTTP request and return a Resp. Connection-level failures (service
    asleep, DNS, refused) propagate as exceptions so callers can retry; HTTP
    error STATUSES (4xx/5xx) come back as a normal Resp so they can be asserted.
    """
    url = f"{BASE_URL}{path}"
    headers = headers or {}

    if _CLIENT == "httpx":
        import httpx
        with httpx.Client(timeout=timeout) as client:
            r = client.request(method, url, headers=headers, json=json_body)
        return Resp(r.status_code, r.text)

    if _CLIENT == "requests":
        import requests
        r = requests.request(method, url, headers=headers, json=json_body, timeout=timeout)
        return Resp(r.status_code, r.text)

    # urllib fallback (stdlib only).
    import urllib.error
    import urllib.request

    data = None
    req_headers = dict(headers)
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return Resp(resp.status, resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # A real HTTP response with a non-2xx status — surface it, don't raise.
        return Resp(exc.code, exc.read().decode("utf-8"))


# ─────────────────────────────────────────────────────────
# Auth token (mirror how the auth service mints access tokens).
# ─────────────────────────────────────────────────────────
def mint_access_token(secret: str, user_id: uuid.UUID, hours: int = 1) -> str:
    claims = {
        "sub": str(user_id),
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
    }
    return jwt.encode(claims, secret, algorithm="HS256")


# ─────────────────────────────────────────────────────────
# Pretty PASS/FAIL bookkeeping.
# ─────────────────────────────────────────────────────────
class StepError(Exception):
    """Raised to fail a step with a clear message."""


_results: list[tuple[str, str, str]] = []  # (step, status, detail)


def record(step: str, status: str, detail: str = "") -> None:
    _results.append((step, status, detail))
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ "}.get(status, "  ")
    line = f"  {icon} [{status}] {step}"
    if detail:
        line += f" — {detail}"
    print(line)


def need(condition: bool, message: str) -> None:
    if not condition:
        raise StepError(message)


# ─────────────────────────────────────────────────────────
# The flow.
# ─────────────────────────────────────────────────────────
LEAKY_KEYS = {"answer", "essential_keywords", "supporting_keywords"}

REAL_ANSWER = (
    "Aerodynamics is the study of how air moves around objects and how forces "
    "such as lift, drag, thrust, and weight affect an aircraft's motion. Pilots "
    "and engineers apply it to keep airflow smooth and the aircraft efficient "
    "and controllable throughout the flight envelope."
)


def step_health() -> None:
    """1. Health — retry through cold start, then assert ok + model loaded."""
    deadline = time.time() + HEALTH_DEADLINE_SECONDS
    attempt = 0
    last = ""
    while time.time() < deadline:
        attempt += 1
        try:
            r = request("GET", "/api/health", timeout=HEALTH_ATTEMPT_TIMEOUT)
            if r.status_code == 200:
                body = r.json()
                if body.get("status") == "ok" and body.get("model_loaded") is True:
                    record("1. GET /api/health",
                           "PASS", f"ok, model_loaded after {attempt} attempt(s)")
                    return
                last = f"unexpected body: {body}"
            else:
                last = f"HTTP {r.status_code}"
        except Exception as exc:  # connection refused / timeout while waking
            last = f"{type(exc).__name__}: {exc}"
        print(f"     …waking (attempt {attempt}, {last}); retrying…")
        time.sleep(HEALTH_RETRY_SLEEP)

    raise StepError(f"health never became ready within "
                    f"{HEALTH_DEADLINE_SECONDS}s (last: {last})")


def step_start(headers: dict) -> tuple[str, list[dict]]:
    """2. Start a session; assert questions + anti-cheat (no leaked secrets)."""
    r = request("POST", "/api/session/start", headers=headers, json_body={})
    need(r.status_code == 200, f"expected 200, got {r.status_code}: {r._text[:300]}")
    body = r.json()

    questions = body.get("questions", [])
    need(len(questions) >= 1, "no questions returned")

    for q in questions:
        leaked = LEAKY_KEYS & set(q.keys())
        need(not leaked, f"question {q.get('id')} leaked secret field(s): {leaked}")

    session_token = body.get("session_token")
    need(bool(session_token), "no session_token returned")

    record("2. POST /api/session/start",
           "PASS", f"{len(questions)} question(s), no answer/keywords leaked")
    return session_token, questions


def step_submit_real(headers: dict, session_token: str, question: dict) -> dict:
    """3. Submit a realistic answer (behavioral_features=null)."""
    payload = {
        "session_token": session_token,
        "question_id": question["id"],
        "student_answer_text": REAL_ANSWER,
        "time_taken_seconds": 72,
        "was_skipped": False,
        "behavioral_features": None,
    }
    r = request("POST", "/api/answer/submit", headers=headers, json_body=payload)
    need(r.status_code == 200, f"expected 200, got {r.status_code}: {r._text[:300]}")
    body = r.json()

    need("final_score" in body, "no final_score in scored response")
    need(bool(body.get("band")), "no band in scored response")
    need(body.get("was_skipped") is False, "real answer marked skipped")

    record("3. POST /api/answer/submit (real)",
           "PASS", f"score={body['final_score']} band={body['band']}")
    return body


def step_submit_skip(headers: dict, session_token: str, question: dict) -> dict:
    """4. Submit a skipped answer; assert 0 / 'skipped'."""
    payload = {
        "session_token": session_token,
        "question_id": question["id"],
        "student_answer_text": "",
        "time_taken_seconds": 0,
        "was_skipped": True,
        "behavioral_features": None,
    }
    r = request("POST", "/api/answer/submit", headers=headers, json_body=payload)
    need(r.status_code == 200, f"expected 200, got {r.status_code}: {r._text[:300]}")
    body = r.json()

    need(body.get("final_score") == 0.0, f"skip score not 0.0: {body.get('final_score')}")
    need(body.get("band") == "skipped", f"skip band not 'skipped': {body.get('band')}")

    record("4. POST /api/answer/submit (skip)",
           "PASS", "score=0.0 band=skipped")
    return body


def step_complete(headers: dict, session_token: str, results: list[dict]) -> dict:
    """5. Complete the session; assert an aggregated report."""
    payload = {"session_token": session_token, "results": results}
    r = request("POST", "/api/session/complete", headers=headers, json_body=payload)
    need(r.status_code == 200, f"expected 200, got {r.status_code}: {r._text[:300]}")
    body = r.json()

    need(body.get("num_questions") == 2, f"num_questions != 2: {body.get('num_questions')}")
    need(body.get("num_skipped") == 1, f"num_skipped != 1: {body.get('num_skipped')}")
    need("total_score" in body, "no total_score in report")
    need(bool(body.get("overall_band")), "no overall_band in report")

    record("5. POST /api/session/complete",
           "PASS", f"total={body['total_score']} band={body['overall_band']}")
    return body


def step_history(headers: dict, report: dict) -> None:
    """
    6. Fetch the caller's interview history and confirm the interview we just
       completed is there — this is the PROD proof that Supabase persistence ran.

    NOTE: this only passes once DATABASE_URL is set on Render AND the service has
    been redeployed. Before that the endpoint returns [] (the DB-less path), so
    we WARN ("persistence not active yet") instead of hard-failing.
    """
    r = request("GET", "/api/interviews", headers=headers)
    need(r.status_code == 200, f"expected 200, got {r.status_code}: {r._text[:300]}")
    history = r.json()
    need(isinstance(history, list), f"history not a list: {type(history)}")

    if not history:
        record("6. GET /api/interviews", "WARN",
                "returned [] — persistence not active yet "
                "(set DATABASE_URL on Render + redeploy, then re-run)")
        return

    # History is newest-first; the interview we just saved should be at/near the
    # top. Match on the report's figures rather than an id (complete doesn't
    # return the saved id).
    def matches(row: dict) -> bool:
        return (
            row.get("num_questions") == report["num_questions"]
            and row.get("num_skipped") == report["num_skipped"]
            and row.get("overall_band") == report["overall_band"]
            and abs((row.get("total_score") or -1) - report["total_score"]) < 0.05
        )

    found = next((row for row in history[:5] if matches(row)), None)
    need(found is not None,
         f"just-completed interview not found in latest history rows; "
         f"newest={history[0] if history else None}")

    record("6. GET /api/interviews", "PASS",
           f"persisted interview found (id={found['id']}, "
           f"{len(history)} total in history)")


# ─────────────────────────────────────────────────────────
# Entry point.
# ─────────────────────────────────────────────────────────
def main() -> int:
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        print("ERROR: JWT_SECRET_KEY is required (the live service's verify secret).",
              file=sys.stderr)
        print("       Run: JWT_SECRET_KEY='<live-secret>' python scripts/live_test.py",
              file=sys.stderr)
        return 2

    print("=" * 72)
    print(f"  LIVE E2E TEST  →  {BASE_URL}")
    print(f"  http client: {_CLIENT}   test user: {TEST_USER_ID}")
    print("=" * 72)

    token = mint_access_token(secret, TEST_USER_ID)
    headers = {"Authorization": f"Bearer {token}"}

    try:
        step_health()  # public — no auth needed
        session_token, questions = step_start(headers)

        first_q = questions[0]
        skip_q = questions[1] if len(questions) > 1 else questions[0]

        real = step_submit_real(headers, session_token, first_q)
        skipped = step_submit_skip(headers, session_token, skip_q)
        report = step_complete(headers, session_token, [real, skipped])
        step_history(headers, report)
    except StepError as exc:
        record("flow aborted", "FAIL", str(exc))
    except Exception as exc:  # unexpected — still summarize
        record("flow aborted", "FAIL", f"{type(exc).__name__}: {exc}")

    # ── Summary ──
    print("\n" + "=" * 72)
    passed = sum(1 for _, s, _ in _results if s == "PASS")
    warned = sum(1 for _, s, _ in _results if s == "WARN")
    failed = sum(1 for _, s, _ in _results if s == "FAIL")
    print(f"  SUMMARY: {passed} passed, {warned} warning(s), {failed} failed")
    print("=" * 72)

    if failed:
        print("  RESULT: FAIL")
        return 1
    if warned:
        print("  RESULT: PASS (with warnings — see above)")
        return 0
    print("  RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
