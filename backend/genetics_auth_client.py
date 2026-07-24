from __future__ import annotations

import base64
import json
import os
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

GENETICS_BASE_URL = os.getenv("GENETICS_API_BASE",
                        "https://integration.andrsn.in").strip().rstrip("/")
GENETICS_SERVICE_USERNAME = os.getenv("GENETICS_API_USERNAME", "").strip()
GENETICS_SERVICE_PASSWORD = os.getenv("GENETICS_API_PASSWORD", "")
GENETICS_TOKEN_PATH = os.getenv("GENETICS_TOKEN_PATH", "/auth/login").strip()
GENETICS_LOGIN_PATH = os.getenv("GENETICS_LOGIN_PATH", "/genetics/login").strip()
GENETICS_VERIFY_PATH = os.getenv("GENETICS_VERIFY_PATH",
                           "/genetics/verify_otp").strip()
GENETICS_TIMEOUT = int(os.getenv("GENETICS_API_TIMEOUT", "15"))

_NOT_CONFIGURED = {
    "ok": False, "status": 503,
    "error": "The sign-in service is not configured on the server. Contact the administrator.",
}


def is_configured() -> bool:
    return bool(GENETICS_BASE_URL and GENETICS_SERVICE_USERNAME and GENETICS_SERVICE_PASSWORD)


def _extract(data: dict | None, *keys: str):
    for src in (data, (data or {}).get("data") if isinstance(data, dict) else None):
        if isinstance(src, dict):
            for k in keys:
                if src.get(k) not in (None, ""):
                    return src[k]
    return None


def _jwt_exp(token: str) -> int:
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return int(json.loads(base64.urlsafe_b64decode(seg)).get("exp", 0))
    except Exception:
        return 0


def _mask_mobile(mobile: str) -> str:
    digits = "".join(c for c in mobile if c.isdigit())
    return ("••••••" + digits[-4:]) if len(digits) >= 4 else "your registered number"


def _request(path: str, payload: dict, with_auth: bool = True, _retry: bool = True):
    url = f"{GENETICS_BASE_URL}{path}"
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
        with urllib.request.urlopen(req, timeout=GENETICS_TIMEOUT, context=ctx) as resp:
            body = resp.read().decode() or "{}"
            return resp.status, json.loads(body), None
    except urllib.error.HTTPError as e:
        if e.code == 401 and with_auth and _retry:
            _service_token(force=True)
            return _request(path, payload, with_auth, _retry=False)
        try:
            data = json.loads(e.read().decode() or "{}")
        except Exception:
            data = {}
        return e.code, data, _extract(data, "message", "error") or "Request failed."
    except Exception as e:
        print(f"[genetics_auth][error] {url}: {e}")
        return 502, None, "Sign-in service unreachable."


_svc_token: str | None = None
_svc_exp: float = 0.0


def _service_token(force: bool = False) -> str | None:
    global _svc_token, _svc_exp
    if not force and _svc_token and time.time() < _svc_exp - 30:
        return _svc_token
    status, data, err = _request(
        GENETICS_TOKEN_PATH,
        {"username": GENETICS_SERVICE_USERNAME, "password": GENETICS_SERVICE_PASSWORD},
        with_auth=False,
    )
    if status != 200 or not data:
        print(f"[genetics_auth] service login failed ({status}): {err}")
        return None
    token = _extract(data, "token", "access_token",
                     "jwt", "accessToken", "bearer")
    if not token:
        print(
            f"[genetics_auth] service login: no token in response keys {list(data)}")
        return None
    _svc_token = token
    _svc_exp = _jwt_exp(token) or (time.time() + 600)
    return _svc_token


def login(mobile: str, password: str) -> dict:
    if not is_configured():
        return dict(_NOT_CONFIGURED)
    status, data, err = _request(
        GENETICS_LOGIN_PATH, {"mobile_number": mobile, "password": password})
    data = data or {}
    if 200 <= status < 300 or data.get("message") == "success":
        reference = data.get("hash")
        if not reference:
            nested = data.get("data")
            reference = nested if isinstance(
                nested, str) else (nested or {}).get("hash")
        if reference:
            return {"ok": True, "reference": reference, "sent_to": _mask_mobile(mobile)}
        if data.get("success") is True and data.get("message") == "Login successful":
            return {"ok": True, "skip_otp": True}
        return {"ok": False, "status": 502,
                "error": "Login succeeded but the sign-in service returned no OTP hash."}
    if status >= 500:
        return {"ok": False, "status": 502, "error": "Could not reach the sign-in service. Please try again."}
    return {"ok": False, "status": status,
            "error": data.get("message") or data.get("error") or err or "Invalid mobile number or password."}


def verify(reference: str, code: str, mobile: str = "") -> dict:
    if not is_configured():
        return dict(_NOT_CONFIGURED)
    status, data, err = _request(
        GENETICS_VERIFY_PATH, {"otp": code, "hash": reference, "mobile": mobile})
    data = data or {}
    if 200 <= status < 300 or data.get("message") == "success":
        return {"ok": True}
    if status >= 500:
        return {"ok": False, "status": 502, "error": "Could not reach the sign-in service. Please try again."}
    return {"ok": False, "status": status,
            "error": data.get("message") or data.get("error") or err or "Incorrect code. Please try again."}


def resend(reference: str, mobile: str = "") -> dict:
    if not is_configured():
        return dict(_NOT_CONFIGURED)
    return {"ok": False, "status": 400,
            "error": "To get a new code, please go back and sign in again."}
