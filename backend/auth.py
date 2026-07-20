"""
auth.py
───────────────────────────────────────────────────────────────
Role-based authentication for Anderson Trackings.

Ownership split
  • IT owns accounts + the whole OTP flow (verify password, send SMS code,
    check code). This app relays to IT's API via it_auth.py and never stores
    or sees passwords or OTP codes.
  • This app owns only the role mapping (mobile → role) via role_store.py.

Flow
  1. POST /auth/login   {mobile, password}
       → looks up the mobile number's role locally (DENY if none),
         asks IT to verify the password + send the OTP by message,
         returns a `challenge`.
  2. POST /auth/verify  {challenge, code}
       → asks IT to check the OTP; on success issues an HttpOnly signed
         session cookie and returns the role-specific landing URL.
  3. POST /auth/resend  {challenge}      → asks IT to re-send the code.
  4. POST /auth/logout  (or GET)         → clears the session cookie.
  5. GET  /auth/me                       → { authenticated, role }.

Roles & landing pages
  admin    → "/"          (the suite-picker landing, admin only)
  cmc      → "/cmc/"      (CMC trackers)
  anderson → "/anderson/" (Anderson trackers)

No external crypto dependencies — session-token signing (HMAC-SHA256) uses the
Python standard library. Password checking and OTP delivery live in IT's API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Cookie, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

# ── Config ────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
SECRET_FILE   = BASE_DIR / ".auth_secret"
COOKIE_NAME   = "anderson_session"
SESSION_HOURS = int(os.getenv("AUTH_SESSION_HOURS", "8"))
# Set AUTH_COOKIE_SECURE=true when served over real HTTPS. Default false so it
# works on http://127.0.0.1 during local use.
COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() == "true"

OTP_TTL_SECS  = int(os.getenv("OTP_TTL_SECONDS", "300"))   # login/OTP window (5 min)

ROLE_HOME = {
    "admin":    "/",
    "cmc":      "/cmc/",
    "anderson": "/anderson/",
}

# Accounts + OTP belong to IT (it_auth); roles belong to us (role_store).
import it_auth
import role_store


# ── Session-signing secret (persisted so restarts don't log everyone out) ──

def _load_secret() -> str:
    env_secret = os.getenv("AUTH_SECRET", "").strip()
    if env_secret:
        return env_secret
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    secret = secrets.token_hex(32)
    try:
        SECRET_FILE.write_text(secret, encoding="utf-8")
    except Exception:
        pass
    return secret


SECRET = _load_secret()


# ── Pending login challenges ──────────────────────────────────
# challenge_id -> {mobile, role, reference, exp, tries}
# `reference` is IT's opaque handle for the OTP; we carry it to /verify + /resend.
_pending: dict[str, dict] = {}
_OTP_MAX_TRIES = 5


def _prune_pending() -> None:
    now = time.time()
    for cid in [c for c, v in _pending.items() if v["exp"] < now]:
        _pending.pop(cid, None)


# ── Session token helpers ─────────────────────────────────────

def _sign_session(username: str, role: str) -> str:
    payload = {"sub": username, "role": role, "exp": int(time.time()) + SESSION_HOURS * 3600}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=")
    return f"{body.decode()}.{sig_b64.decode()}"


def read_session(token: str | None) -> dict | None:
    """Return {sub, role} for a valid, unexpired session cookie, else None."""
    if not token or "." not in token:
        return None
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()
        got = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        if not hmac.compare_digest(expected, got):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def _set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=SESSION_HOURS * 3600,
        path="/",
    )


# ── Simple per-IP brute-force limiter ─────────────────────────
_fail_counts: dict[str, int] = {}
_fail_times: dict[str, float] = {}
_MAX_FAILS = 8
_LOCKOUT = 300


def _locked(ip: str) -> bool:
    if _fail_counts.get(ip, 0) >= _MAX_FAILS:
        if time.time() - _fail_times.get(ip, 0) < _LOCKOUT:
            return True
        _fail_counts[ip] = 0
    return False


def _record_fail(ip: str) -> None:
    _fail_counts[ip] = _fail_counts.get(ip, 0) + 1
    _fail_times[ip] = time.time()


# ── Router ────────────────────────────────────────────────────
router = APIRouter(prefix="/auth")


class LoginBody(BaseModel):
    mobile: str
    password: str


class VerifyBody(BaseModel):
    challenge: str
    code: str


class ChallengeBody(BaseModel):
    challenge: str


@router.post("/login")
def login(body: LoginBody, request: Request):
    ip = request.client.host if request.client else "unknown"
    if _locked(ip):
        return JSONResponse(
            {"error": "Too many attempts. Please wait a few minutes and try again."},
            status_code=429,
        )

    mobile = role_store.normalize_mobile(body.mobile)
    if not mobile:
        _record_fail(ip)
        return JSONResponse({"error": "Enter a valid mobile number."}, status_code=400)

    # We own authorization: no role mapping → no access, and we don't even bother
    # IT (or send an OTP) for someone who couldn't get in anyway.
    mapping = role_store.get(mobile)
    if not mapping:
        _record_fail(ip)
        return JSONResponse(
            {"error": "No access has been assigned to this number. Contact your administrator."},
            status_code=403,
        )

    # IT owns credentials + OTP: verify the password and send the code.
    result = it_auth.login(mobile, body.password)
    if not result.get("ok"):
        status = int(result.get("status", 401))
        if status < 500:                       # count only credential failures
            _record_fail(ip)
        return JSONResponse(
            {"error": result.get("error", "Sign-in failed. Please try again.")},
            status_code=status,
        )

    _fail_counts[ip] = 0
    _prune_pending()

    challenge = secrets.token_urlsafe(24)
    _pending[challenge] = {
        "mobile": mapping["mobile"],
        "role": mapping["role"],
        "reference": result.get("reference", ""),
        "exp": time.time() + OTP_TTL_SECS,
        "tries": 0,
    }

    return JSONResponse({
        "challenge": challenge,
        "sent_to": result.get("sent_to", "your registered number"),
        "expires_in": OTP_TTL_SECS,
    })


@router.post("/verify")
def verify(body: VerifyBody):
    _prune_pending()
    pending = _pending.get(body.challenge)
    if not pending:
        return JSONResponse(
            {"error": "This code has expired. Please sign in again."}, status_code=400
        )

    pending["tries"] += 1
    if pending["tries"] > _OTP_MAX_TRIES:
        _pending.pop(body.challenge, None)
        return JSONResponse(
            {"error": "Too many incorrect codes. Please sign in again."}, status_code=429
        )

    result = it_auth.verify(pending["reference"], body.code, pending["mobile"])
    if not result.get("ok"):
        status = int(result.get("status", 401))
        # A dead/expired reference means the whole attempt must restart.
        if status == 400:
            _pending.pop(body.challenge, None)
        return JSONResponse(
            {"error": result.get("error", "Incorrect code. Please try again.")},
            status_code=status,
        )

    _pending.pop(body.challenge, None)
    token = _sign_session(pending["mobile"], pending["role"])
    redirect = ROLE_HOME.get(pending["role"], "/")
    resp = JSONResponse({"ok": True, "redirect": redirect, "role": pending["role"]})
    _set_session_cookie(resp, token)
    return resp


@router.post("/resend")
def resend(body: ChallengeBody):
    _prune_pending()
    pending = _pending.get(body.challenge)
    if not pending:
        return JSONResponse(
            {"error": "Session expired. Please sign in again."}, status_code=400
        )
    result = it_auth.resend(pending["reference"], pending["mobile"])
    if not result.get("ok"):
        return JSONResponse(
            {"error": result.get("error", "Could not resend the code.")},
            status_code=int(result.get("status", 502)),
        )
    pending["exp"] = time.time() + OTP_TTL_SECS
    pending["tries"] = 0
    return JSONResponse({"ok": True, "sent_to": result.get("sent_to", "your registered number")})


@router.get("/me")
def me(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return JSONResponse({"authenticated": False})
    return JSONResponse({"authenticated": True, "role": sess["role"], "mobile": sess["sub"]})


def _clear_and_redirect():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.post("/logout")
def logout_post():
    return _clear_and_redirect()


@router.get("/logout")
def logout_get():
    return _clear_and_redirect()
