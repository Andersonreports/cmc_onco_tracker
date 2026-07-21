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
    name       VARCHAR(191),
    role       VARCHAR(32) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4;
"""


def init_schema() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)
            cur.execute(
                "SELECT COUNT(*) AS n FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name='user_roles' AND column_name='name'",
                (DB,),
            )
            if cur.fetchone()["n"] == 0:
                cur.execute("ALTER TABLE user_roles ADD COLUMN name VARCHAR(191) AFTER mobile")


def count_roles() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM user_roles")
            return cur.fetchone()["n"]


def list_roles() -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT mobile, name, role FROM user_roles ORDER BY name, mobile")
            return list(cur.fetchall())


def get_role(mobile: str) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT mobile, name, role FROM user_roles WHERE mobile=%s",
                (mobile,),
            )
            return cur.fetchone()


def set_role(mobile: str, role: str, name: str | None = None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_roles (mobile, name, role) VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE role=VALUES(role), name=COALESCE(VALUES(name), name)",
                (mobile, name, role),
            )


def delete_role(mobile: str) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            return cur.execute(
                "DELETE FROM user_roles WHERE mobile=%s", (mobile,)
            )
