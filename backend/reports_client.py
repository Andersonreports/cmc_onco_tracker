from __future__ import annotations

import json
import os
import re
import ssl
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import genetics_auth_client

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    pass

REPORTS_API_BASE = (os.getenv("REPORTS_API_BASE", "").strip().rstrip("/")
                    or genetics_auth_client.GENETICS_BASE_URL)
REPORTS_API_KEY = os.getenv("REPORTS_API_KEY", "").strip()
REPORTS_API_TIMEOUT = int(os.getenv("REPORTS_API_TIMEOUT", "15"))

def _env_path(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


PATH_QUERY = _env_path("REPORTS_PATH_QUERY", "/genetics/get_sample_data_by_params")
PATH_LIST = _env_path("REPORTS_PATH_LIST", PATH_QUERY)
PATH_INSERT = _env_path("REPORTS_PATH_INSERT", "/genetics/insert_data")
PATH_UPDATE = _env_path("REPORTS_PATH_UPDATE", "/genetics/update_data")
PATH_BULK = _env_path("REPORTS_PATH_BULK", "/genetics/insert_bulk_data")


class ReportsAPIError(Exception):
    """Raised when the API is unreachable or returns an error.

    When status/body/content_type hold that answer verbatim so
    callers can pass it straight through instead of inventing one. They stay
    unset when nothing came back at all (unreachable, timed out, unconfigured).
    """

    def __init__(self, message: str, status: int | None = None,
                 body: str = "", content_type: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body
        self.content_type = content_type


class ReportNotFound(ReportsAPIError):
    """Raised when a gen_id does not match any record."""


class ReportsAPIUnsupported(ReportsAPIError):
    """Raised for operations where API does not expose (e.g. delete)."""


def is_configured() -> bool:
    return bool(REPORTS_API_BASE)


_MESSAGE_KEYS = ("message", "error", "detail", "msg")


def error_message(body: str) -> str:
    """The API's own wording for a failure, or "" when its body carries none."""
    try:
        parsed = json.loads(body or "")
    except Exception:
        return ""
    if not isinstance(parsed, dict):
        return ""
    for key in _MESSAGE_KEYS:
        val = parsed.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _auth_header() -> str | None:
    if REPORTS_API_KEY:
        return f"Bearer {REPORTS_API_KEY}"
    token = genetics_auth_client.service_token()
    return f"Bearer {token}" if token else None


def _post(path: str, payload: dict | None = None, _retry: bool = True):
    if not is_configured():
        raise ReportsAPIError("REPORTS_API_BASE is not configured.")
    url = f"{REPORTS_API_BASE}{path}"
    headers = {"Content-Type": "application/json"}
    auth = _auth_header()
    if auth:
        headers["Authorization"] = auth
    data = json.dumps(payload if payload is not None else {}).encode()
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=REPORTS_API_TIMEOUT, context=ctx) as resp:
            body = resp.read().decode() or "null"
            return json.loads(body)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) and _retry and not REPORTS_API_KEY:
            genetics_auth_client.service_token(force=True)
            return _post(path, payload, _retry=False)
        body = e.read().decode(errors="replace") if e.fp else ""
        raise ReportsAPIError(
            f"POST {path} failed ({e.code}): {body[:300]}",
            status=e.code, body=body,
            content_type=e.headers.get("Content-Type", "") if e.headers else "",
        ) from e
    except ReportsAPIError:
        raise
    except Exception as e:
        raise ReportsAPIError(f"POST {path} unreachable: {e}") from e


_LIST_KEYS = ("response", "sample_data", "data", "records", "rows", "result", "results")


def _records(resp) -> list[dict]:
    """Pull the record list out of whatever envelope API wraps it in."""
    if isinstance(resp, list):
        return [r for r in resp if isinstance(r, dict)]
    if not isinstance(resp, dict):
        return []
    for key in _LIST_KEYS:
        val = resp.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
        if isinstance(val, dict):
            nested = _records(val)
            if nested:
                return nested
    return []


FIELD_MAP = {
    "name":        "sample_name",
    "test":        "test_name",
    "gen_id":      "gen_id",
    "and_id":      "anderson_id",
    "client":      "client_name",
    "tat":         "tat",
    "rep_exp":     "repeat_expansion",
    "cnv_status":  "cnv_status",
    "analyst_raw": "analyze_by",
    "ana_date":    "analyze_date",
    "pri_rev":     "reviewer",
    "remarks":     "remarks",
    "report_release_date": "report_release_date",
    "history":     "history_writeup",
    "run_text":    "run_number",
    "bioinfo_time": "bioinfo_analysis_time",
}

_DATE_FIELDS = ("tat", "ana_date", "report_release_date")

_NULLABLE_DATES = ("ana_date", "report_release_date")

BOOL_MAP = {
    "is_priority":   "is_priority",
    "is_reanalysis": "is_re_analysis",
}

_LOCAL_FIELDS = ("final",)

_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")

_BLANK_MARK = re.compile(r"^(?:[-‐-―−⬝.\s]+|na|n/a|nil|none|null)$", re.I)


def _is_blank(value) -> bool:
    return bool(_BLANK_MARK.match(str(value or "").strip())) or not str(value or "").strip()


def _date_norm(value) -> str:
    """Any incoming date -> DD-MM-YYYY.

    That is how dates are stored as strings in IT's database and how the
    tracker displays and submits them, so this is the one canonical format on
    both sides — no conversion happens anywhere else.
    """
    s = str(value or "").strip().strip("()").strip()
    if _is_blank(s):
        return ""
    m = _ISO_DATE.match(s)
    if m:
        return f"{m.group(3).zfill(2)}-{m.group(2).zfill(2)}-{m.group(1)}"
    parts = re.split(r"[-/._]", s)          # a few legacy rows use 30_05_26
    if len(parts) >= 3 and len(parts[0]) <= 2 and parts[0].isdigit():
        year = parts[2][:4]
        if len(year) == 2 and year.isdigit():   # legacy 2-digit years: 25 -> 2025
            year = f"20{year}"
        return f"{parts[0].zfill(2)}-{parts[1].zfill(2)}-{year}"
    return s


_date_in = _date_norm
_date_out = _date_norm


UNASSIGNED_RUN = 9999


def _run_number(run_text: str) -> int:
    """Last number in the run label, e.g. 'SURFseq- Run-102' -> 102."""
    nums = re.findall(r"\d+", str(run_text or ""))
    return int(nums[-1]) if nums else UNASSIGNED_RUN


def report_id(rec: dict) -> str:
    """IT's numeric primary key, falling back to gen_id on odd records."""
    raw = rec.get("id")
    if raw not in (None, ""):
        return str(raw).strip()
    for key in ("gen_id", "anderson_id", "sample_name"):
        val = str(rec.get(key) or "").strip()
        if val:
            return val
    return ""


def _to_app(rec: dict) -> dict:
    row: dict = {}
    for app_key, it_key in FIELD_MAP.items():
        val = rec.get(it_key)
        row[app_key] = _date_in(val) if app_key in _DATE_FIELDS else (
            "" if val is None else str(val).strip())
    for app_key, it_key in BOOL_MAP.items():
        row[app_key] = bool(rec.get(it_key))

    row["visible"] = bool(rec.get("visible", True))
    row["id"] = report_id(rec)
    row["run_number"] = _run_number(row["run_text"])
    row["last_updated_by"] = str(rec.get("last_updated_by") or "").strip()
    row["last_updated_at"] = str(rec.get("last_updated_at") or "").strip()

    raw = row["analyst_raw"]
    bracket = re.search(r"\(([^)]+)\)", raw)
    row["assign_date"] = bracket.group(1).strip() if bracket else ""
    row["analyst"] = re.sub(r"\s*\([^)]*\)", "", raw).strip()
    row["sno"] = ""

    local = _overlay_get(row["id"])
    for f in _LOCAL_FIELDS:
        row[f] = local.get(f, "")
    return row


def _clean(value) -> str:
    """A placeholder dash means absent; API should get an empty string."""
    s = str(value or "").strip()
    return "" if _is_blank(s) else s


UNKNOWN_USER = "Tracker"


def _timestamp() -> str:
    """UTC in the millisecond ISO form API's own records come back in."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _to_it(row: dict, record_id: str = "") -> dict:
    rec: dict = {}
    for app_key, it_key in FIELD_MAP.items():
        val = row.get(app_key, "")
        if app_key not in _DATE_FIELDS:
            rec[it_key] = _clean(val)
            continue
        out = _date_out(val)
        rec[it_key] = (out or None) if app_key in _NULLABLE_DATES else out
    for app_key, it_key in BOOL_MAP.items():
        rec[it_key] = bool(row.get(app_key))

    rec["visible"] = bool(row.get("visible", True))

    who = str(row.get("last_updated_by") or "").strip() or UNKNOWN_USER
    rec["last_updated_by"] = who
    rec["last_updated_at"] = _timestamp()

    key = str(record_id or row.get("id") or "").strip()
    if key.isdigit():
        rec["id"] = int(key)
    else:
        rec["created_by"] = who
        rec["created_at"] = rec["last_updated_at"]
    return rec


_OVERLAY_PATH = Path(_env_path(
    "REPORTS_OVERLAY_PATH", str(Path(__file__).parent / "tracker_local_fields.json")))
_overlay_lock = threading.Lock()
_overlay_cache: dict | None = None


def _overlay_all() -> dict:
    global _overlay_cache
    if _overlay_cache is None:
        try:
            _overlay_cache = json.loads(_OVERLAY_PATH.read_text() or "{}")
        except Exception:
            _overlay_cache = {}
    return _overlay_cache


def _overlay_get(key: str) -> dict:
    if not key:
        return {}
    val = _overlay_all().get(key)
    return val if isinstance(val, dict) else {}


def _overlay_set(key: str, row: dict) -> None:
    """Persist the app-only fields for one record, dropping empty entries."""
    if not key:
        return
    entry = {f: str(row.get(f) or "").strip() for f in _LOCAL_FIELDS}
    with _overlay_lock:
        data = _overlay_all()
        if any(entry.values()):
            data[key] = entry
        else:
            data.pop(key, None)
        try:
            tmp = _OVERLAY_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(_OVERLAY_PATH)
        except Exception as e:
            print(f"[reports_client] could not write overlay {_OVERLAY_PATH}: {e}")


def status() -> dict:
    if not is_configured():
        return {"reachable": False, "base_url": None,
                "error": "REPORTS_API_BASE not configured"}
    try:
        _post(PATH_LIST, {"sample_data": {}})
        return {"reachable": True, "base_url": REPORTS_API_BASE}
    except ReportsAPIError as e:
        return {"reachable": False, "base_url": REPORTS_API_BASE, "error": str(e)}


def list_reports() -> list[dict]:
    """visible=False is API's own soft delete, set from their side. The tracker
    never sets it and shows a called-off sample by its remarks instead, but it
    still honours a row they have hidden."""
    return [_to_app(rec) for rec in _records(_post(PATH_LIST, {"sample_data": {}}))
            if rec.get("visible", True)]


def get_report(report_id_: str) -> dict | None:
    """Single record, used to rebuild a full row before a whole-record update."""
    for rec in _records(_post(PATH_QUERY, {"sample_data": {"id": report_id_}})):
        if report_id(rec) == str(report_id_):
            return _to_app(rec)
    return None


def create_report(payload: dict) -> dict:
    resp = _post(PATH_INSERT, {"sample_data": _to_it(payload)})
    row = dict(payload)
    gen_id = str(payload.get("gen_id") or "").strip()
    row["id"] = ""
    if gen_id:
        matches = [r for r in _records(_post(PATH_QUERY, {"sample_data": {"gen_id": gen_id}}))
                   if str(r.get("gen_id") or "").strip() == gen_id]
        if matches:
            row["id"] = report_id(max(matches, key=lambda r: int(str(r.get("id") or 0))))
    _overlay_set(row["id"], payload)
    row["_response"] = resp if isinstance(resp, dict) else {}
    return row


_PRESERVED = ("bioinfo_time",)


def update_report(report_id_: str, payload: dict) -> dict | None:
    if not str(report_id_ or "").strip().isdigit():
        return None

    payload = dict(payload)
    if any(not str(payload.get(f) or "").strip() for f in _PRESERVED):
        current = get_report(report_id_)
        if current:
            for f in _PRESERVED:
                if not str(payload.get(f) or "").strip():
                    payload[f] = current.get(f, "")

    rec = _to_it(payload, record_id=report_id_)
    if not rec.get("id"):        
        return None
    _post(PATH_UPDATE, {"sample_data": rec})
    _overlay_set(report_id_, payload)
    row = dict(payload)
    row["id"] = report_id_
    return row


def bulk_add(reports: list[dict]) -> int:
    if not reports:
        return 0
    _post(PATH_BULK, {"sample_data": [_to_it(r) for r in reports]})

    pending = {str(r.get("gen_id") or "").strip(): r for r in reports
               if any(str(r.get(f) or "").strip() for f in _LOCAL_FIELDS)}
    if pending:
        try:
            for rec in _records(_post(PATH_LIST, {"sample_data": {}})):
                gen_id = str(rec.get("gen_id") or "").strip()
                if gen_id in pending:
                    _overlay_set(report_id(rec), pending.pop(gen_id))
        except ReportsAPIError as e:
            print(f"[reports_client] bulk_add: clinical reviewers not stored: {e}")
    return len(reports)


def _patch_many(id: list[str], changes: dict) -> int:
    """Apply the same change to a batch of records.

    API only accepts whole records, so each one has to be read before it can be
    written. One list read covers the whole batch instead of a lookup per id,
    which halves the round trips — allocation hands over a full run at a time.
    """
    if not id:
        return 0
    wanted = {str(i) for i in id}
    stored = {row["id"]: row for row in list_reports() if row["id"] in wanted}

    count = 0
    for id_ in id:
        row = stored.get(str(id_))
        if row is None:
            continue
        row.update(changes)
        update_report(str(id_), row)
        count += 1
    return count


def bulk_release(id: list[str], report_release_date: str) -> int:
    return _patch_many(id, {"report_release_date": report_release_date})


def bulk_remarks(id: list[str], remarks: str) -> int:
    return _patch_many(id, {"remarks": remarks})


def bulk_reviewer(id: list[str], pri_rev: str) -> int:
    return _patch_many(id, {"pri_rev": pri_rev})
