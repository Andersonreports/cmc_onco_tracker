"""
it_auth.py — adapter for IT's authentication + OTP service (integration.andrsn.in).

IT owns the accounts (mobile numbers, passwords) and the ENTIRE OTP flow. This
app never sees or stores a password or an OTP code beyond relaying it once.

── IT's API (two tiers) ───────────────────────────────────────────────────────
1. SERVICE auth — this app authenticates ITSELF with a machine account and gets
   a short-lived Bearer JWT (~15 min), refreshed automatically / on 401:
       POST {IT_BASE_URL}/auth/login   {username, password}   (no auth header)
         → {"success": true, "token": "<JWT>", "expiresIn": "15m"}
           (response shape confirmed live 2026-07-20)

2. USER auth — carried out with the service Bearer token in the header:
       POST {IT_BASE_URL}/genetics/login       {mobile_number, password}
         → IT verifies the password, sends the OTP by SMS, returns a `hash`
           (top-level, or nested under "data"); success flagged by 2xx or
           {"message": "success"}
       POST {IT_BASE_URL}/genetics/verify_otp  {otp, hash, mobile}
         → IT checks the code (same success convention)
   (payload keys + success convention verified against the working
    Report-Automation client, not just the Postman collection.)

We expose three calls to auth.py, hiding both tiers:
    login(mobile, password)          → {ok, reference(=hash), sent_to} | {ok:False,…}
    verify(reference, code, mobile)  → {ok} | {ok:False,…}
    resend(reference, mobile)        → {ok, sent_to} | {ok:False,…}

NOTE: the collection has no resend endpoint, so in real mode resend asks the
user to sign in again (see resend()). Response field names are best-effort with
fallbacks — adjust _extract() keys once a real response body is confirmed.

── Demo mode (no GENETICS_API_USERNAME / GENETICS_API_PASSWORD) ────────────────
For localhost testing: any mobile logs in with IT_DEMO_PASSWORD (default "demo");
a 6-digit code is generated, verified locally, and shown on the login screen.

No external deps — stdlib only.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

# ── Config ────────────────────────────────────────────────────
# Env var names match the Report-Automation project (the proven client), so the
# same GENETICS_API_* credentials block works for both apps.
IT_BASE_URL = os.getenv("GENETICS_API_BASE", "https://integration.andrsn.in").strip().rstrip("/")
IT_SERVICE_USERNAME = os.getenv("GENETICS_API_USERNAME", "").strip()
IT_SERVICE_PASSWORD = os.getenv("GENETICS_API_PASSWORD", "")
IT_TOKEN_PATH = os.getenv("GENETICS_TOKEN_PATH", "/auth/login").strip()
IT_LOGIN_PATH = os.getenv("GENETICS_LOGIN_PATH", "/genetics/login").strip()
IT_VERIFY_PATH = os.getenv("GENETICS_VERIFY_PATH", "/genetics/verify_otp").strip()
IT_TIMEOUT = int(os.getenv("GENETICS_API_TIMEOUT", "15"))

OTP_TTL_SECS = int(os.getenv("OTP_TTL_SECONDS", "300"))   # demo mode only
_DEMO_PASSWORD = os.getenv("IT_DEMO_PASSWORD", "demo")
_DEMO_MAX_TRIES = 5


def is_configured() -> bool:
    """True when IT's real API is wired up (otherwise demo mode)."""
    return bool(IT_BASE_URL and IT_SERVICE_USERNAME and IT_SERVICE_PASSWORD)


# ── small helpers ─────────────────────────────────────────────

def _extract(data: dict | None, *keys: str):
    """First non-empty value among keys, checking top level then a nested `data`."""
    for src in (data, (data or {}).get("data") if isinstance(data, dict) else None):
        if isinstance(src, dict):
            for k in keys:
                if src.get(k) not in (None, ""):
                    return src[k]
    return None


def _jwt_exp(token: str) -> int:
    """Unix exp claim from a JWT, or 0 if it can't be read."""
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return int(json.loads(base64.urlsafe_b64decode(seg)).get("exp", 0))
    except Exception:
        return 0


def _mask_mobile(mobile: str) -> str:
    digits = "".join(c for c in mobile if c.isdigit())
    return ("••••••" + digits[-4:]) if len(digits) >= 4 else "your registered number"


# ── HTTP ──────────────────────────────────────────────────────

def _request(path: str, payload: dict, with_auth: bool = True, _retry: bool = True):
    """POST JSON to IT. Returns (status:int, data:dict|None, error:str|None)."""
    url = f"{IT_BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if with_auth:
        token = _service_token()
        if not token:
            return 502, None, "Could not authenticate to the sign-in service."
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=IT_TIMEOUT, context=ctx) as resp:
            body = resp.read().decode() or "{}"
            return resp.status, json.loads(body), None
    except urllib.error.HTTPError as e:
        if e.code == 401 and with_auth and _retry:
            _service_token(force=True)              # token likely expired — refresh once
            return _request(path, payload, with_auth, _retry=False)
        try:
            data = json.loads(e.read().decode() or "{}")
        except Exception:
            data = {}
        return e.code, data, _extract(data, "message", "error") or "Request failed."
    except Exception as e:
        print(f"[it_auth][error] {url}: {e}")
        return 502, None, "Sign-in service unreachable."


# ── Service token (cached, auto-refreshed) ────────────────────
_svc_token: str | None = None
_svc_exp: float = 0.0


def _service_token(force: bool = False) -> str | None:
    global _svc_token, _svc_exp
    if not force and _svc_token and time.time() < _svc_exp - 30:
        return _svc_token
    status, data, err = _request(
        IT_TOKEN_PATH,
        {"username": IT_SERVICE_USERNAME, "password": IT_SERVICE_PASSWORD},
        with_auth=False,
    )
    if status != 200 or not data:
        print(f"[it_auth] service login failed ({status}): {err}")
        return None
    token = _extract(data, "token", "access_token", "jwt", "accessToken", "bearer")
    if not token:
        print(f"[it_auth] service login: no token in response keys {list(data)}")
        return None
    _svc_token = token
    _svc_exp = _jwt_exp(token) or (time.time() + 600)
    return _svc_token


# ── Demo mode state (self-contained; not used when IT is configured) ─
# reference -> {code, exp, tries}
_demo: dict[str, dict] = {}


def _prune_demo() -> None:
    now = time.time()
    for ref in [r for r, v in _demo.items() if v["exp"] < now]:
        _demo.pop(ref, None)


def _demo_issue() -> tuple[str, str]:
    _prune_demo()
    reference = secrets.token_urlsafe(18)
    code = f"{secrets.randbelow(1_000_000):06d}"
    _demo[reference] = {"code": code, "exp": time.time() + OTP_TTL_SECS, "tries": 0}
    print(f"[it_auth][demo] code {code} (ref {reference[:8]}…, valid {OTP_TTL_SECS//60} min)")
    return reference, code


# ── Public flow ───────────────────────────────────────────────

def login(mobile: str, password: str) -> dict:
    """Verify the password with IT and trigger the OTP send.

    Success: {ok: True, reference, sent_to} (+ dev_code in demo mode).
    Failure: {ok: False, status, error}.
    """
    if not is_configured():
        if password != _DEMO_PASSWORD:
            return {"ok": False, "status": 401, "error": "Invalid mobile number or password."}
        reference, code = _demo_issue()
        return {"ok": True, "reference": reference, "sent_to": _mask_mobile(mobile), "dev_code": code}

    # NOTE: /genetics/login expects the mobile under "mobile_number" (verified
    # against the working Report-Automation client). Success is 2xx OR
    # message=="success"; the OTP handle "hash" may be top-level or under "data".
    status, data, err = _request(IT_LOGIN_PATH, {"mobile_number": mobile, "password": password})
    data = data or {}
    if 200 <= status < 300 or data.get("message") == "success":
        reference = data.get("hash")
        if not reference:
            nested = data.get("data")
            reference = nested if isinstance(nested, str) else (nested or {}).get("hash")
        if reference:
            return {"ok": True, "reference": reference, "sent_to": _mask_mobile(mobile)}
        return {"ok": False, "status": 502,
                "error": "Login succeeded but the sign-in service returned no OTP hash."}
    if status >= 500:
        return {"ok": False, "status": 502, "error": "Could not reach the sign-in service. Please try again."}
    return {"ok": False, "status": status,
            "error": data.get("message") or data.get("error") or err or "Invalid mobile number or password."}


def verify(reference: str, code: str, mobile: str = "") -> dict:
    """Ask IT to check the OTP. Returns {ok} or {ok: False, status, error}."""
    if not is_configured():
        _prune_demo()
        pending = _demo.get(reference)
        if not pending:
            return {"ok": False, "status": 400, "error": "This code has expired. Please sign in again."}
        pending["tries"] += 1
        if pending["tries"] > _DEMO_MAX_TRIES:
            _demo.pop(reference, None)
            return {"ok": False, "status": 429, "error": "Too many incorrect codes. Please sign in again."}
        if not secrets.compare_digest(code.strip(), pending["code"]):
            return {"ok": False, "status": 401, "error": "Incorrect code. Please try again."}
        _demo.pop(reference, None)
        return {"ok": True}

    # verify_otp expects the mobile under "mobile" (not "mobile_number").
    # Success is 2xx OR message=="success", matching the Report-Automation client.
    status, data, err = _request(
        IT_VERIFY_PATH, {"otp": code, "hash": reference, "mobile": mobile}
    )
    data = data or {}
    if 200 <= status < 300 or data.get("message") == "success":
        return {"ok": True}
    if status >= 500:
        return {"ok": False, "status": 502, "error": "Could not reach the sign-in service. Please try again."}
    return {"ok": False, "status": status,
            "error": data.get("message") or data.get("error") or err or "Incorrect code. Please try again."}


def resend(reference: str, mobile: str = "") -> dict:
    """Re-send the OTP. Returns {ok, sent_to} or {ok: False, status, error}."""
    if not is_configured():
        _prune_demo()
        if reference not in _demo:
            return {"ok": False, "status": 400, "error": "Session expired. Please sign in again."}
        code = f"{secrets.randbelow(1_000_000):06d}"
        _demo[reference] = {"code": code, "exp": time.time() + OTP_TTL_SECS, "tries": 0}
        print(f"[it_auth][demo] resent code {code} (ref {reference[:8]}…)")
        return {"ok": True, "sent_to": _mask_mobile(mobile), "dev_code": code}

    # IT's collection exposes no resend endpoint. Without re-sending the password
    # we can't re-trigger /genetics/login, so ask the user to start over.
    # If IT adds a resend endpoint, wire it here.
    return {"ok": False, "status": 400,
            "error": "To get a new code, please go back and sign in again."}
