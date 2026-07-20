"""
db.py — MySQL storage layer for the role mapping (mobile → role).

This table is the ONLY account data this app owns. Identity (passwords, the
accounts themselves) and the OTP flow are owned by IT's auth API — see
it_auth.py. Here we only record which role a mobile number is allowed to use.

Enabled only when MySQL settings are present in backend/.env:

    MYSQL_HOST=127.0.0.1
    MYSQL_PORT=3306
    MYSQL_USER=anderson
    MYSQL_PASSWORD=your-password
    MYSQL_DB=anderson_trackings

If those are absent (or the server is unreachable), the app falls back to the
local roles.json file — see role_store.py. Uses PyMySQL (pure-Python driver,
no build step).
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

try:
    import pymysql
    from pymysql.cursors import DictCursor
    _HAVE_PYMYSQL = True
except Exception:  # driver not installed yet
    _HAVE_PYMYSQL = False

HOST = os.getenv("MYSQL_HOST", "").strip()
PORT = int(os.getenv("MYSQL_PORT", "3306"))
USER = os.getenv("MYSQL_USER", "").strip()
PASSWORD = os.getenv("MYSQL_PASSWORD", "")
DB = os.getenv("MYSQL_DB", "").strip()


def is_configured() -> bool:
    """True when MySQL connection settings are present and the driver is installed."""
    return _HAVE_PYMYSQL and bool(HOST and USER and DB)


def get_conn():
    return pymysql.connect(
        host=HOST,
        port=PORT,
        user=USER,
        password=PASSWORD,
        database=DB,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=5,
    )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_roles (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    mobile     VARCHAR(32) UNIQUE NOT NULL,
    role       VARCHAR(32) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4;
"""


def init_schema() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)


def count_roles() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM user_roles")
            return cur.fetchone()["n"]


def list_roles() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT mobile, role FROM user_roles ORDER BY mobile")
            return list(cur.fetchall())


def get_role(mobile: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT mobile, role FROM user_roles WHERE mobile=%s",
                (mobile,),
            )
            return cur.fetchone()


def set_role(mobile: str, role: str) -> None:
    """Insert the mapping, or update the role if the mobile already exists."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_roles (mobile, role) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE role=VALUES(role)",
                (mobile, role),
            )


def delete_role(mobile: str) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            return cur.execute(
                "DELETE FROM user_roles WHERE mobile=%s", (mobile,)
            )
