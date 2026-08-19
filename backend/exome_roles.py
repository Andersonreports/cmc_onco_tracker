from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from auth import COOKIE_NAME, read_session
import access

ROLES = ("admin", "lead", "primary", "member", "viewer")

TRACKER_KEY = "exome"

# What each duty may do here. "upload" is adding samples the lab has sequenced;
# "edit" is everything done to a sample afterwards — allocating a reviewer,
# release date, CNV status, remarks, cancelling.
CAPABILITIES = {
    "admin":   frozenset({"upload", "edit"}),
    "lead":    frozenset({"edit"}),
    "primary": frozenset({"upload"}),
    "member":  frozenset(),
    "viewer":  frozenset(),
}


def _parent_session(request: Request) -> dict | None:
    return read_session(request.cookies.get(COOKIE_NAME))


def role_for_accesses(accesses, stored_role=None) -> str:
    """The duty this person carries in the tracker.

    stored_role is the role name as assigned; accesses alone cannot say which
    duty it was, since every and-bioinfo duty expands to the same grants.
    """
    if access.is_admin(accesses):
        return "admin"
    if not access.can_open_tracker(accesses, TRACKER_KEY):
        return "viewer"
    return access.duty_of(stored_role) or "lead"


def role_for(request: Request) -> str:
    sess = _parent_session(request) or {}
    return role_for_accesses(sess.get("acc"), sess.get("role"))


def can(request: Request, capability: str) -> bool:
    return capability in CAPABILITIES.get(role_for(request), frozenset())


def can_edit(request: Request) -> bool:
    return can(request, "edit")


def can_upload(request: Request) -> bool:
    return can(request, "upload")


def username_for(request: Request) -> str:
    """Display name for the signed-in user, stamped onto records as last_updated_by."""
    sess = _parent_session(request) or {}
    mobile = sess.get("sub", "")
    try:
        import role_store
        return ((role_store.get(mobile) or {}).get("name") or "").strip() or mobile
    except Exception:
        return mobile


def forbidden(detail: str = "Your role cannot modify reports"):
    return JSONResponse({"error": detail}, status_code=403)


def require_tracker_access(request: Request) -> dict:
    sess = _parent_session(request)
    if not sess:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if not access.can_open_tracker(sess.get("acc"), TRACKER_KEY):
        raise HTTPException(status_code=403, detail="This tracker is not available for your role.")
    return sess
