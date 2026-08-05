from __future__ import annotations
import access
import role_store
import genetics_auth_client as genetics_auth

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

BASE_DIR = Path(__file__).parent
SECRET_FILE = BASE_DIR / ".auth_secret"
COOKIE_NAME = "anderson_session"
IDLE_SECS = int(os.getenv("AUTH_IDLE_HOURS", "5")) * 3600
COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE",
                          "false").strip().lower() == "true"

OTP_TTL_SECS = int(os.getenv("OTP_TTL_SECONDS", "300"))

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


_pending: dict[str, dict] = {}
_OTP_MAX_TRIES = 5


def _prune_pending() -> None:
    now = time.time()
    for cid in [c for c, v in _pending.items() if v["exp"] < now]:
        _pending.pop(cid, None)


def _sign_session(username: str, role: str) -> str:
    payload = {"sub": username, "role": role,
               "acc": access.normalize(role),
               "exp": int(time.time()) + IDLE_SECS}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=")
    return f"{body.decode()}.{sig_b64.decode()}"


def read_session(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(SECRET.encode(), body.encode(),
                            hashlib.sha256).digest()
        got = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        if not hmac.compare_digest(expected, got):
            return None
        payload = json.loads(base64.urlsafe_b64decode(
            body + "=" * (-len(body) % 4)))
        if payload.get("exp", 0) < int(time.time()):
            return None
        payload["acc"] = access.normalize(payload.get("acc") or payload.get("role"))
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
        max_age=IDLE_SECS,
        path="/",
    )


def renew_session_cookie(response, sess: dict) -> None:
    token = _sign_session(sess["sub"], sess["role"])
    _set_session_cookie(response, token)


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

    mapping = role_store.get(mobile)
    if not mapping:
        _record_fail(ip)
        return JSONResponse(
            {"error": "No access has been assigned to this number. Contact your administrator."},
            status_code=403,
        )

    if mapping.get("password_hash"):
        if not role_store.verify_local_password(mobile, body.password):
            _record_fail(ip)
            return JSONResponse(
                {"error": "Invalid mobile number or password."}, status_code=401)
        _fail_counts[ip] = 0
        token = _sign_session(mapping["mobile"], mapping["role"])
        redirect = access.home_for(mapping["role"])
        resp = JSONResponse(
            {"ok": True, "skip_otp": True, "redirect": redirect, "role": mapping["role"]})
        _set_session_cookie(resp, token)
        return resp

    result = genetics_auth.login(mobile, body.password)
    if not result.get("ok"):
        status = int(result.get("status", 401))
        if status < 500:
            _record_fail(ip)
        return JSONResponse(
            {"error": result.get(
                "error", "Sign-in failed. Please try again.")},
            status_code=status,
        )

    _fail_counts[ip] = 0

    if result.get("skip_otp"):
        token = _sign_session(mapping["mobile"], mapping["role"])
        redirect = access.home_for(mapping["role"])
        resp = JSONResponse(
            {"ok": True, "skip_otp": True, "redirect": redirect, "role": mapping["role"]})
        _set_session_cookie(resp, token)
        return resp

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

    result = genetics_auth.verify(pending["reference"], body.code, pending["mobile"])
    if not result.get("ok"):
        status = int(result.get("status", 401))
        if status == 400:
            _pending.pop(body.challenge, None)
        return JSONResponse(
            {"error": result.get(
                "error", "Incorrect code. Please try again.")},
            status_code=status,
        )

    _pending.pop(body.challenge, None)
    token = _sign_session(pending["mobile"], pending["role"])
    redirect = access.home_for(pending["role"])
    resp = JSONResponse(
        {"ok": True, "redirect": redirect, "role": pending["role"]})
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
    result = genetics_auth.resend(pending["reference"], pending["mobile"])
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
    return JSONResponse({"authenticated": True, "role": sess["role"],
                         "accesses": sess["acc"],
                         "is_admin": access.is_admin(sess["acc"]),
                         "sections": access.visible_sections(sess["acc"], parent=None),
                         "trackers": access.tracker_keys(sess["acc"]),
                         "mobile": sess["sub"]})


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
