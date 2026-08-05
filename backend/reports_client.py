from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

# Exome Sample Tracker reports live in IT's database and reach us over this
# REST API. The paths, bearer auth and payload shape below assume plain REST
# conventions (GET/POST/PUT/PATCH/DELETE /reports, "id" on each record) and
# must be reconciled with IT's actual contract.
REPORTS_API_BASE = os.getenv("REPORTS_API_BASE", "").strip().rstrip("/")
REPORTS_API_KEY = os.getenv("REPORTS_API_KEY", "").strip()
REPORTS_API_TIMEOUT = int(os.getenv("REPORTS_API_TIMEOUT", "15"))


class ReportsAPIError(Exception):
    """Raised when the IT reports API is unreachable or returns an error."""


class ReportNotFound(ReportsAPIError):
    """Raised when the IT reports API returns 404 for a specific report id."""


def is_configured() -> bool:
    return bool(REPORTS_API_BASE)


def _request(method: str, path: str, payload: dict | None = None):
    if not is_configured():
        raise ReportsAPIError("REPORTS_API_BASE is not configured.")
    url = f"{REPORTS_API_BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if REPORTS_API_KEY:
        headers["Authorization"] = f"Bearer {REPORTS_API_KEY}"
    data = json.dumps(payload).encode() if payload is not None else None
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=REPORTS_API_TIMEOUT, context=ctx) as resp:
            body = resp.read().decode() or "null"
            return json.loads(body)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ReportNotFound(f"{method} {path}: not found") from e
        body = e.read().decode() if e.fp else ""
        raise ReportsAPIError(f"{method} {path} failed ({e.code}): {body[:300]}") from e
    except Exception as e:
        raise ReportsAPIError(f"{method} {path} unreachable: {e}") from e


def status() -> dict:
    if not is_configured():
        return {"reachable": False, "base_url": None, "error": "REPORTS_API_BASE not configured"}
    try:
        _request("GET", "/reports")
        return {"reachable": True, "base_url": REPORTS_API_BASE}
    except ReportsAPIError as e:
        return {"reachable": False, "base_url": REPORTS_API_BASE, "error": str(e)}


def list_reports() -> list[dict]:
    return _request("GET", "/reports") or []


def create_report(payload: dict) -> dict:
    return _request("POST", "/reports", payload)


def update_report(report_id: str, payload: dict) -> dict | None:
    try:
        return _request("PUT", f"/reports/{report_id}", payload)
    except ReportNotFound:
        return None


def delete_report(report_id: str) -> bool:
    try:
        _request("DELETE", f"/reports/{report_id}")
        return True
    except ReportNotFound:
        return False


def bulk_add(reports: list[dict]) -> int:
    count = 0
    for r in reports:
        create_report(r)
        count += 1
    return count


def _partial_update(report_id: str, payload: dict) -> dict | None:
    # PATCH, not PUT: these callers only carry one changed field and must
    # not overwrite the rest of the record. Assumes IT's API supports
    # PATCH for partial updates — confirm once the real contract is known.
    try:
        return _request("PATCH", f"/reports/{report_id}", payload)
    except ReportNotFound:
        return None


def bulk_release(ids: list[str], rel_date: str) -> int:
    count = 0
    for id_ in ids:
        if _partial_update(id_, {"rel_date": rel_date}) is not None:
            count += 1
    return count


def bulk_remark(ids: list[str], remark: str) -> int:
    count = 0
    for id_ in ids:
        if _partial_update(id_, {"remark": remark}) is not None:
            count += 1
    return count
