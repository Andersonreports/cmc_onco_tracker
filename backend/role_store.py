"""
role_store.py — single source of truth for the role mapping (mobile → role).

This is the ONLY account data this app owns. Identity (passwords, the accounts
themselves) and the whole OTP flow belong to IT's auth API (see it_auth.py).
Here we only decide which suite a mobile number is allowed to see.

Users sign in with their mobile number, so mappings are keyed by the number.
Numbers are normalized (see normalize_mobile) so "+91 98765 43210",
"09876543210" and "9876543210" all resolve to the same key.

Chooses its backend automatically:
  • MySQL   — when MySQL settings are present in .env AND reachable (see db.py)
  • file    — otherwise, backend/roles.json (zero-setup local default)

Either way it exposes the same small API used by auth.py and manage_roles.py:
  get(mobile) · all() · set_role(mobile, role) · delete(mobile)
  · normalize_mobile(raw) · backend_name()
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

import db

ROLES_FILE = Path(__file__).parent / "roles.json"


DEFAULT_ROLES = [
    {"mobile": "7358752950", "role": "admin"},
    {"mobile": "9000000002", "role": "cmc"},
    {"mobile": "9000000003", "role": "anderson"},
]


def normalize_mobile(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):   # +91XXXXXXXXXX
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):  # 0XXXXXXXXXX
        digits = digits[1:]
    return digits


_backend: str | None = None  # "mysql" | "file"


def _print_seed_banner(where: str) -> None:
    print("=" * 62)
    print(f" role_store: seeded initial role mappings in {where}.")
    print(" Edit them anytime with manage_roles.py (set / delete).")
    for r in DEFAULT_ROLES:
        print(f"   - {r['mobile']:<12} -> {r['role']}")
    print("=" * 62)


def backend_name() -> str:
    global _backend
    if _backend is not None:
        return _backend
    if db.is_configured():
        try:
            db.init_schema()
            if db.count_roles() == 0:
                for r in DEFAULT_ROLES:
                    db.set_role(r["mobile"], r["role"])
                _print_seed_banner(f"MySQL ({db.DB})")
            _backend = "mysql"
            print(
                f"role_store: using MySQL backend ({db.USER}@{db.HOST}/{db.DB}).")
            return _backend
        except Exception as e:
            print("=" * 62)
            print(f" role_store: MySQL configured but unreachable ({e}).")
            print(" Falling back to roles.json. Fix .env / start MySQL to use the DB.")
            print("=" * 62)
    _backend = "file"
    return _backend


# ── File backend helpers ──────────────────────────────────────

def _file_load() -> list[dict]:
    if not ROLES_FILE.exists():
        ROLES_FILE.write_text(json.dumps(
            {"roles": DEFAULT_ROLES}, indent=2), encoding="utf-8")
        _print_seed_banner("backend/roles.json")
    try:
        return json.loads(ROLES_FILE.read_text(encoding="utf-8")).get("roles", [])
    except Exception:
        return []


def _file_save(rows: list[dict]) -> None:
    ROLES_FILE.write_text(json.dumps(
        {"roles": rows}, indent=2), encoding="utf-8")


# ── Public API ────────────────────────────────────────────────

def all() -> list[dict]:
    if backend_name() == "mysql":
        return db.list_roles()
    return _file_load()


def get(mobile: str) -> dict | None:
    """Return {mobile, role} for the given mobile number, or None if unmapped."""
    key = normalize_mobile(mobile)
    if backend_name() == "mysql":
        return db.get_role(key)
    for r in _file_load():
        if normalize_mobile(r["mobile"]) == key:
            return r
    return None


def set_role(mobile: str, role: str) -> None:
    """Create the mapping, or update the role if the mobile already exists."""
    key = normalize_mobile(mobile)
    if backend_name() == "mysql":
        db.set_role(key, role)
        return
    rows = _file_load()
    for r in rows:
        if normalize_mobile(r["mobile"]) == key:
            r["role"] = role
            _file_save(rows)
            return
    rows.append({"mobile": key, "role": role})
    _file_save(rows)


def delete(mobile: str) -> bool:
    key = normalize_mobile(mobile)
    if backend_name() == "mysql":
        return db.delete_role(key) > 0
    rows = _file_load()
    kept = [r for r in rows if normalize_mobile(r["mobile"]) != key]
    if len(kept) == len(rows):
        return False
    _file_save(kept)
    return True
