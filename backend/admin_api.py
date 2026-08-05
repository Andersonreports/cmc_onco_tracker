from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel

from auth import read_session
import access
import role_store

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(session_cookie: str | None):
    sess = read_session(session_cookie)
    if not sess:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if not access.is_admin(sess.get("acc")):
        raise HTTPException(status_code=403, detail="This area is for admins only.")
    return sess


class UserBody(BaseModel):
    mobile: str
    name: str | None = None
    role: str | list[str]


class PasswordBody(BaseModel):
    password: str


@router.get("/users")
def list_users(anderson_session: str | None = Cookie(default=None)):
    _require_admin(anderson_session)
    users = [
        {"mobile": r.get("mobile", ""), "name": r.get("name") or "",
         "accesses": access.normalize(r.get("role")),
         "local_password": bool(r.get("password_hash"))}
        for r in role_store.all()
    ]
    return {"users": users, "grantable": list(access.GRANTABLE), "labels": access.LABELS}


@router.post("/users")
def upsert_user(body: UserBody, anderson_session: str | None = Cookie(default=None)):
    _require_admin(anderson_session)
    mobile = role_store.normalize_mobile(body.mobile)
    if len(mobile) < 10:
        raise HTTPException(status_code=400, detail="Enter a valid mobile number.")
    accesses = access.normalize(body.role)
    if not accesses:
        raise HTTPException(
            status_code=400,
            detail=f"Select at least one access. Valid: {', '.join(access.GRANTABLE)}.")
    name = (body.name or "").strip()
    role_store.set_role(mobile, access.to_stored(accesses), name)
    return {"ok": True, "mobile": mobile, "name": name, "accesses": accesses}


@router.delete("/users/{mobile}")
def delete_user(mobile: str, anderson_session: str | None = Cookie(default=None)):
    sess = _require_admin(anderson_session)
    key = role_store.normalize_mobile(mobile)
    if key == role_store.normalize_mobile(sess.get("sub", "")):
        raise HTTPException(status_code=400, detail="You can't remove your own access.")
    if not role_store.delete(key):
        raise HTTPException(status_code=404, detail="No such user.")
    return {"ok": True}


@router.post("/users/{mobile}/password")
def set_user_password(mobile: str, body: PasswordBody, anderson_session: str | None = Cookie(default=None)):
    _require_admin(anderson_session)
    key = role_store.normalize_mobile(mobile)
    if not role_store.get(key):
        raise HTTPException(status_code=404, detail="No such user.")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    role_store.set_password(key, body.password)
    return {"ok": True}


@router.delete("/users/{mobile}/password")
def clear_user_password(mobile: str, anderson_session: str | None = Cookie(default=None)):
    _require_admin(anderson_session)
    key = role_store.normalize_mobile(mobile)
    if not role_store.get(key):
        raise HTTPException(status_code=404, detail="No such user.")
    role_store.clear_password(key)
    return {"ok": True}
