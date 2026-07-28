
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
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


_PBKDF2_ITERATIONS = 260_000


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password_hash(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def has_local_password(mobile: str) -> bool:
    mapping = get(mobile)
    return bool(mapping and mapping.get("password_hash"))


def verify_local_password(mobile: str, password: str) -> bool:
    mapping = get(mobile)
    stored = mapping.get("password_hash") if mapping else None
    return bool(stored) and _verify_password_hash(password, stored)


def set_password(mobile: str, password: str) -> None:
    key = normalize_mobile(mobile)
    if not get(key):
        raise ValueError(f"No role mapping for {key}. Set a role first with 'set'.")
    password_hash = _hash_password(password)
    if backend_name() == "mysql":
        db.set_password_hash(key, password_hash)
        return
    rows = _file_load()
    for r in rows:
        if normalize_mobile(r["mobile"]) == key:
            r["password_hash"] = password_hash
            _file_save(rows)
            return


def clear_password(mobile: str) -> None:
    key = normalize_mobile(mobile)
    if backend_name() == "mysql":
        db.set_password_hash(key, None)
        return
    rows = _file_load()
    for r in rows:
        if normalize_mobile(r["mobile"]) == key:
            r.pop("password_hash", None)
            _file_save(rows)
            return
