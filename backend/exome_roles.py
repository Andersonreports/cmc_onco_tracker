from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from auth import COOKIE_NAME, read_session
import access

ROLES = ("admin", "lead", "viewer")

TRACKER_KEY = "exome"


def _parent_session(request: Request) -> dict | None:
    return read_session(request.cookies.get(COOKIE_NAME))


def role_for_accesses(accesses) -> str:
    if access.is_admin(accesses):
        return "admin"
    if access.can_open_tracker(accesses, TRACKER_KEY):
        return "lead"
    return "viewer"


def role_for(request: Request) -> str:
    sess = _parent_session(request)
    return role_for_accesses((sess or {}).get("acc"))


def can_edit(request: Request) -> bool:
    return role_for(request) in ("admin", "lead")


def forbidden(detail: str = "Your role cannot modify reports"):
    return JSONResponse({"error": detail}, status_code=403)


def require_tracker_access(request: Request) -> dict:
    sess = _parent_session(request)
    if not sess:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if not access.can_open_tracker(sess.get("acc"), TRACKER_KEY):
        raise HTTPException(status_code=403, detail="This tracker is not available for your role.")
    return sess
