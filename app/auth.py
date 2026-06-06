"""
JWT verification for the AviAssess scoring service.

WHY this module exists:
    This is a SEPARATE Render service from the one that handles login. It NEVER
    issues tokens — it only VERIFIES the access tokens minted by the existing
    auth service. Verification works because this service is configured with the
    SAME JWT_SECRET_KEY and the same HS256 algorithm, so signatures match.

Token contract (must mirror the issuing auth service exactly):
    * Library   : python-jose (HS256)
    * "sub"     : the user's UUID, as a string
    * "type"    : must equal "access"
    * "exp"     : standard expiry — python-jose validates it during decode

Security choices:
    * All failure paths raise the SAME generic 401 ("Invalid or expired token")
      so we never leak which check failed (signature vs expiry vs claim shape).
    * No token blacklist check: access tokens are short-lived, so revocation is
      out of scope here (deliberately skipped for now).
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError

from app.config import settings


# The "type" claim a valid access token must carry.
ACCESS_TOKEN_TYPE = "access"

# Extracts and requires an "Authorization: Bearer <token>" header. With the
# default auto_error=True, a missing/malformed header is rejected by FastAPI
# before our code runs.
bearer_scheme = HTTPBearer()

# Two distinct 401s. The CODES differ so the frontend can react differently:
#   * token_expired → silently call the auth service's /refresh and retry.
#   * invalid_token → force a full re-login.
# The MESSAGES stay generic — they never reveal which specific check failed
# (signature vs claim shape vs bad sub all collapse to "invalid_token").
def _expired_token_exc() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "token_expired",
                "message": "Access token expired", "details": None},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _invalid_token_exc() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "invalid_token",
                "message": "Invalid authentication token", "details": None},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _verify_token(token: str, secret: str, algorithm: str) -> uuid.UUID:
    """
    Pure verification core: decode + validate claims → user UUID.

    Kept separate from the FastAPI dependency (and from `settings`) so it can be
    unit-tested in isolation with any secret.

    Raises:
        HTTPException(401, token_expired) — ONLY when the signature is valid but
            the token has expired (so the client knows a refresh will help).
        HTTPException(401, invalid_token) — for every other failure (bad
            signature, malformed, wrong type, missing/bad sub).
    """
    # jwt.decode validates the signature AND expiry. ExpiredSignatureError is a
    # subclass of JWTError, so catch it FIRST to keep the two paths distinct.
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except ExpiredSignatureError:
        raise _expired_token_exc()
    except JWTError:
        raise _invalid_token_exc()

    # Must be an ACCESS token (not a refresh token or anything else).
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise _invalid_token_exc()

    # "sub" must be present and parse as a UUID.
    subject = payload.get("sub")
    if not subject:
        raise _invalid_token_exc()

    try:
        return uuid.UUID(str(subject))
    except (ValueError, AttributeError, TypeError):
        raise _invalid_token_exc()


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> uuid.UUID:
    """
    FastAPI dependency: resolve the caller's verified user UUID from the
    Bearer access token. Use as `Depends(get_current_user_id)` on protected
    endpoints.
    """
    return _verify_token(
        credentials.credentials,
        settings.JWT_SECRET_KEY,
        settings.JWT_ALGORITHM,
    )


# ─────────────────────────────────────────────────────────
# Standalone Test
# Run from the PROJECT ROOT (config requires the env var to import):
#   JWT_SECRET_KEY=dummy python -m app.auth
#
# The tests below use their OWN dummy secret via _verify_token, so the value of
# the env var above doesn't matter — it only needs to exist so app.config imports.
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":

    from datetime import datetime, timedelta, timezone

    DUMMY_SECRET = "test-secret-do-not-use-in-prod"
    ALGO = "HS256"
    USER_ID = uuid.uuid4()

    def make_token(secret=DUMMY_SECRET, *, sub=str(USER_ID),
                   token_type="access", expires_in_min=15):
        """Mint a token with python-jose — mirrors how the auth service issues."""
        claims = {
            "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in_min),
        }
        if sub is not None:
            claims["sub"] = sub
        if token_type is not None:
            claims["type"] = token_type
        return jwt.encode(claims, secret, algorithm=ALGO)

    def expect_ok(label, token):
        try:
            result = _verify_token(token, DUMMY_SECRET, ALGO)
            ok = result == USER_ID
            print(f"  [{'PASS' if ok else 'FAIL'}] {label} -> {result}")
        except HTTPException as exc:
            print(f"  [FAIL] {label} -> unexpectedly rejected ({exc.detail})")

    def expect_reject(label, token, expected_code):
        try:
            result = _verify_token(token, DUMMY_SECRET, ALGO)
            print(f"  [FAIL] {label} -> unexpectedly ACCEPTED ({result})")
        except HTTPException as exc:
            code = exc.detail.get("error")
            ok = code == expected_code
            tag = "PASS" if ok else "FAIL"
            print(f"  [{tag}] {label} -> {exc.status_code} {code} "
                  f"(expected {expected_code})")

    print("\n" + "=" * 66)
    print("  JWT VERIFICATION TESTS")
    print(f"  user id: {USER_ID}")
    print("=" * 66)

    # Happy path.
    expect_ok("valid access token", make_token())

    # Expired is its OWN code (frontend refreshes on this one).
    expect_reject("expired token", make_token(expires_in_min=-1), "token_expired")

    # Everything else collapses to invalid_token (frontend re-logins).
    expect_reject("wrong type (refresh)", make_token(token_type="refresh"), "invalid_token")
    expect_reject("missing type claim", make_token(token_type=None), "invalid_token")
    expect_reject("tampered signature", make_token() + "x", "invalid_token")
    expect_reject("wrong secret", make_token(secret="some-other-secret"), "invalid_token")
    expect_reject("missing sub", make_token(sub=None), "invalid_token")
    expect_reject("sub is not a uuid", make_token(sub="not-a-uuid"), "invalid_token")
    expect_reject("garbage token", "this.is.not.a.jwt", "invalid_token")

    # The two codes MUST differ.
    expired = make_token(expires_in_min=-1)
    invalid = make_token() + "x"
    try:
        _verify_token(expired, DUMMY_SECRET, ALGO)
    except HTTPException as e_exp:
        try:
            _verify_token(invalid, DUMMY_SECRET, ALGO)
        except HTTPException as e_inv:
            differ = e_exp.detail["error"] != e_inv.detail["error"]
            print(f"\n  [{'PASS' if differ else 'FAIL'}] codes differ: "
                  f"{e_exp.detail['error']} != {e_inv.detail['error']}")

    print("=" * 66)
