
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
    {"mobile": "7358752950", "name": "Admin", "role": "admin"},
]


def normalize_mobile(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


_backend: str | None = None


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
                    db.set_role(r["mobile"], r["role"], r.get("name"))
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


def all() -> list[dict]:
    if backend_name() == "mysql":
        return db.list_roles()
    return _file_load()


def get(mobile: str) -> dict | None:
    key = normalize_mobile(mobile)
    if backend_name() == "mysql":
        return db.get_role(key)
    for r in _file_load():
        if normalize_mobile(r["mobile"]) == key:
            return r
    return None


def set_role(mobile: str, role: str, name: str | None = None) -> None:
    key = normalize_mobile(mobile)
    if backend_name() == "mysql":
        db.set_role(key, role, name)
        return
    rows = _file_load()
    for r in rows:
        if normalize_mobile(r["mobile"]) == key:
            r["role"] = role
            if name is not None:
                r["name"] = name
            _file_save(rows)
            return
    rows.append({"mobile": key, "name": name or "", "role": role})
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
