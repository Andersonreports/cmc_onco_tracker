from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from auth import read_session
import role_store

router = APIRouter(prefix="/admin", tags=["admin"])

ROLES = ("admin", "cmc", "anderson")


def _require_admin(session_cookie: str | None):
    sess = read_session(session_cookie)
    if not sess:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if sess.get("role") != "admin":
        raise HTTPException(status_code=403, detail="This area is for admins only.")
    return sess


class UserBody(BaseModel):
    mobile: str
    name: str | None = None
    role: str


@router.get("/users")
def list_users(anderson_session: str | None = Cookie(default=None)):
    _require_admin(anderson_session)
    users = [
        {"mobile": r.get("mobile", ""), "name": r.get("name") or "", "role": r.get("role", "")}
        for r in role_store.all()
    ]
    return {"users": users, "roles": list(ROLES)}


@router.post("/users")
def upsert_user(body: UserBody, anderson_session: str | None = Cookie(default=None)):
    _require_admin(anderson_session)
    mobile = role_store.normalize_mobile(body.mobile)
    if len(mobile) < 10:
        raise HTTPException(status_code=400, detail="Enter a valid mobile number.")
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(ROLES)}.")
    name = (body.name or "").strip()
    role_store.set_role(mobile, body.role, name)
    return {"ok": True, "mobile": mobile, "name": name, "role": body.role}


@router.delete("/users/{mobile}")
def delete_user(mobile: str, anderson_session: str | None = Cookie(default=None)):
    sess = _require_admin(anderson_session)
    key = role_store.normalize_mobile(mobile)
    if key == role_store.normalize_mobile(sess.get("sub", "")):
        raise HTTPException(status_code=400, detail="You can't remove your own access.")
    if not role_store.delete(key):
        raise HTTPException(status_code=404, detail="No such user.")
    return {"ok": True}
