"""CMC Sample Tracking — data source, mail sending, and the daily TAT-deadline
alert job.

Ported from the standalone cmc_sampletracker_database Node/Express backend
(services/sheetsService.js, services/mailer.js, services/tatAlerts.js) so the
tracker runs in-process alongside the other trackers instead of as a separate
Node server. Behaviour matches that backend action-for-action; only the
runtime changed.
"""
from __future__ import annotations

import base64
import json
import os
import re
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage

import requests

from env_loader import load_backend_env

load_backend_env()

SPREADSHEET_ID = os.getenv("CMC_ST_SPREADSHEET_ID", "")
APPS_SCRIPT_EXEC_URL = os.getenv("CMC_ST_APPS_SCRIPT_EXEC_URL", "")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv(
    "CMC_ST_GOOGLE_APPLICATION_CREDENTIALS", "./service-account.json")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("CMC_ST_GOOGLE_SERVICE_ACCOUNT_JSON", "")

SMTP_HOST = os.getenv("CMC_ST_SMTP_HOST", "")
SMTP_PORT = int(os.getenv("CMC_ST_SMTP_PORT", "587") or "587")
SMTP_SECURE = os.getenv("CMC_ST_SMTP_SECURE", "false").strip().lower() == "true"
SMTP_USER = os.getenv("CMC_ST_SMTP_USER", "")
SMTP_PASS = os.getenv("CMC_ST_SMTP_PASS", "")
MAIL_FROM = os.getenv("CMC_ST_MAIL_FROM", "") or SMTP_USER

ALERT_RECIPIENTS = os.getenv("CMC_ST_ALERT_RECIPIENTS", "")
DASHBOARD_URL = os.getenv("CMC_ST_DASHBOARD_URL", "")
TAT_ALERT_CRON = os.getenv("CMC_ST_TAT_ALERT_CRON", "0 9 * * *")
TZ_NAME = os.getenv("CMC_ST_TZ", "Asia/Kolkata")
ENABLE_TAT_ALERTS = os.getenv("CMC_ST_ENABLE_TAT_ALERTS", "true").strip().lower() != "false"

ENABLE_EXOME_SYNC = os.getenv("CMC_ST_ENABLE_EXOME_SYNC", "true").strip().lower() != "false"
EXOME_SYNC_MINUTES = int(os.getenv("CMC_ST_EXOME_SYNC_MINUTES", "20"))

# Read-write, not read-only: the bulk release-date edit writes back to the
# sheet through this same client when the Apps Script exec URL isn't set.
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_sheets_client = None


class SampleTrackingError(Exception):
    pass


# --- Google Sheets -----------------------------------------------------

def _sheets_client_cached():
    global _sheets_client
    if _sheets_client is not None:
        return _sheets_client

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    if GOOGLE_SERVICE_ACCOUNT_JSON:
        import json
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SHEETS_SCOPES)
    else:
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_APPLICATION_CREDENTIALS, scopes=SHEETS_SCOPES)

    _sheets_client = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return _sheets_client


_COLUMN_ALIASES = {
    "slNo": ("Sl No",),
    "andersonId": ("Anderson ID",),
    "sampleNumber": ("Sample Number",),
    "remarks": ("Remarks",),
    "name": ("Name",),
    "gender": ("Gender",),
    "testName": ("Test Name",),
    "clientDoctorName": ("Client Doctor Name",),
    "clientName": ("Client Name",),
    "sampleType": ("Sample Type",),
    "history": ("History",),
    "receivedDate": ("Received Date",),
    "tatRawData": ("TAT Raw date", "TAT Raw data"),
    "tatReport": ("TAT Report",),
    "reports": ("Reports",),
    "rawDataReceived": ("Raw data sent", "Raw data received"),
    "reportReleasedDate": ("Report released date",),
    "reportSentLink": ("Report sent link",),
    "rawDataSentTo": ("Raw data sent to",),
    "rawDataSentLink": ("Raw data sent link",),
    "status": ("Status",),
}

_DATE_FIELDS = (
    "receivedDate", "tatRawData", "tatReport", "reports",
    "rawDataReceived", "reportReleasedDate",
)


def _find_col(headers: list, *names: str) -> int:
    lowered = [str(h or "").strip().lower() for h in headers]
    for name in names:
        try:
            return lowered.index(name.lower())
        except ValueError:
            continue
    return -1


def _get_string(row: list, idx: int) -> str:
    if idx < 0 or idx >= len(row) or row[idx] is None:
        return ""
    return str(row[idx]).strip()


_DMY_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _format_date(val) -> str:
    if val is None or val == "":
        return ""
    s = str(val).strip()
    if not s:
        return ""
    if _ISO_RE.match(s):
        return s

    m = _DMY_RE.match(s)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = "20" + y
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"

    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def _parse_sheet_name(name: str) -> dict:
    parts = name.split(" ")
    if len(parts) >= 2:
        return {"month": parts[0], "year": parts[1]}
    return {"month": name, "year": ""}


def _process_sheet(data: list[list], sheet_name: str) -> dict:
    if len(data) < 2:
        return {"headers": [], "rows": [], "sheetInfo": _parse_sheet_name(sheet_name)}

    headers = data[0]
    idx = {key: _find_col(headers, *names) for key, names in _COLUMN_ALIASES.items()}

    rows = []
    for sheet_row_number, r in enumerate(data[1:], start=2):
        if all((c == "" or c is None) for c in r):
            continue
        row = {key: _get_string(r, i) for key, i in idx.items()
               if key not in _DATE_FIELDS}
        for key in _DATE_FIELDS:
            i = idx[key]
            row[key] = _format_date(r[i]) if 0 <= i < len(r) else ""
        row["_sourceSheet"] = sheet_name
        row["_rowIndex"] = sheet_row_number
        rows.append(row)

    return {"headers": headers, "rows": rows, "sheetInfo": _parse_sheet_name(sheet_name)}


def _fetch_from_apps_script(action: str):
    resp = requests.get(APPS_SCRIPT_EXEC_URL, params={"action": action}, timeout=30)
    try:
        payload = resp.json()
    except ValueError as exc:
        raise SampleTrackingError(
            f"Apps Script returned a non-JSON response for action={action}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise SampleTrackingError(payload["error"])
    return payload


CACHE_SECONDS = float(os.getenv("CMC_ST_CACHE_SECONDS", "12"))

_all_data_cache: dict | None = None
_all_data_cache_at = 0.0


def get_all_data() -> dict:
    """The Apps Script exec URL path (Code.gs's getAllData()) reads every
    monthly sheet serially with no batching, on top of the Web App's own
    cold-start lag, so a fresh call is slow. A short cache absorbs repeat
    loads (page opens, tab switches) within that window without going stale
    for long; the Sheets API path below is already fast enough not to need
    it, but caching it too is harmless.
    """
    global _all_data_cache, _all_data_cache_at
    now = time.monotonic()
    if _all_data_cache is not None and (now - _all_data_cache_at) < CACHE_SECONDS:
        return _all_data_cache

    data = _get_all_data_uncached()
    _all_data_cache = data
    _all_data_cache_at = now
    return data


def _get_all_data_uncached() -> dict:
    if APPS_SCRIPT_EXEC_URL:
        return _fetch_from_apps_script("getAllData")

    if not SPREADSHEET_ID:
        raise SampleTrackingError("CMC_ST_SPREADSHEET_ID is not configured")

    sheets = _sheets_client_cached().spreadsheets()
    meta = sheets.get(spreadsheetId=SPREADSHEET_ID,
                       fields="sheets.properties.title").execute()
    sheet_names = [s["properties"]["title"] for s in meta.get("sheets", [])]

    result = {
        "sheets": {},
        "metadata": {
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "totalSheets": 0,
            "totalSamples": 0,
        },
    }
    if not sheet_names:
        return result

    ranges = [f"'{name}'!A:Z" for name in sheet_names]
    batch = sheets.values().batchGet(spreadsheetId=SPREADSHEET_ID, ranges=ranges).execute()

    for name, value_range in zip(sheet_names, batch.get("valueRanges", [])):
        processed = _process_sheet(value_range.get("values", []), name)
        if processed["rows"]:
            result["sheets"][name] = {"headers": processed["headers"], "rows": processed["rows"]}
            result["metadata"]["totalSheets"] += 1
            result["metadata"]["totalSamples"] += len(processed["rows"])

    return result


def get_registration_rows() -> list[dict]:
    if APPS_SCRIPT_EXEC_URL:
        payload = _fetch_from_apps_script("getRegistrations")
        return payload.get("registrations") or payload.get("rows") or []

    if not SPREADSHEET_ID:
        raise SampleTrackingError("CMC_ST_SPREADSHEET_ID is not configured")

    sheets = _sheets_client_cached().spreadsheets()
    meta = sheets.get(spreadsheetId=SPREADSHEET_ID,
                       fields="sheets.properties.title").execute()
    reg_name = next(
        (s["properties"]["title"] for s in meta.get("sheets", [])
         if re.search("regist", s["properties"]["title"], re.I)),
        None,
    )
    if not reg_name:
        return []

    res = sheets.values().get(spreadsheetId=SPREADSHEET_ID, range=f"'{reg_name}'!A:Z").execute()
    data = res.get("values", [])
    if len(data) < 2:
        return []

    headers = data[0]
    return [
        {h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)}
        for row in data[1:]
    ]


# --- Writing edits back to the sheet ------------------------------------

def _col_letter(index: int) -> str:
    """0-based column index -> A1 column letters (0 -> 'A', 26 -> 'AA')."""
    index += 1
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _update_report_released_date_bulk_via_sheets_api(items: list[dict], default_value: str) -> dict:
    if not SPREADSHEET_ID:
        return {"success": False, "error": "CMC_ST_SPREADSHEET_ID is not configured"}

    sheets = _sheets_client_cached().spreadsheets()
    col_by_sheet: dict[str, int] = {}
    data_updates = []
    errors = []

    for item in items:
        sheet_name = item.get("sheetName")
        row_index = item.get("rowIndex")
        value = item.get("value") or default_value
        if not sheet_name or not row_index:
            errors.append("Invalid row reference")
            continue
        try:
            if sheet_name not in col_by_sheet:
                header_row = sheets.values().get(
                    spreadsheetId=SPREADSHEET_ID, range=f"'{sheet_name}'!1:1").execute()
                headers = (header_row.get("values") or [[]])[0]
                col_by_sheet[sheet_name] = _find_col(headers, "Report released date")
            col = col_by_sheet[sheet_name]
            if col < 0:
                errors.append(f"Report released date column not found in {sheet_name}")
                continue
            rng = f"'{sheet_name}'!{_col_letter(col)}{row_index}"
            data_updates.append({"range": rng, "values": [[value]]})
        except Exception as exc:  # noqa: BLE001 - one bad row shouldn't abort the batch
            errors.append(str(exc))

    if data_updates:
        sheets.values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "USER_ENTERED", "data": data_updates},
        ).execute()

    return {"success": len(data_updates) > 0, "updated": len(data_updates), "errors": errors}


def update_report_released_date_bulk(items: list[dict], value: str = "") -> dict:
    """Fill "Report released date" for every {sheetName, rowIndex} pair given.

    Two callers share this: the UI's "select samples, fill the release date
    once" bulk action (every item shares `value`), and the exome-tracker sync
    (each item carries its own `value`, since each Anderson ID has its own
    release date there — an item's own value wins over the shared one).
    """
    if not items:
        return {"success": False, "error": "No rows selected"}

    if APPS_SCRIPT_EXEC_URL:
        result = _post_to_apps_script("updateReportReleasedDateBulk", {
            "items": items, "value": value,
        })
    else:
        result = _update_report_released_date_bulk_via_sheets_api(items, value)

    if result.get("success"):
        global _all_data_cache
        _all_data_cache = None  # next getAllData() reflects the edit instead of a stale cache
    return result


# --- Exome tracker sync ---------------------------------------------------
#
# The exome tracker (backend/exome_api.py, via reports_client.py) tracks
# every WES/WGS/Mito sample — a superset that includes CMC's own samples,
# keyed by the same Anderson ID. Once a sample's report is released there,
# the team no longer has to enter that same date a second time in the CMC
# sheet: this pulls it across automatically, matched by Anderson ID.

_EXOME_DATE_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")


def _exome_date_to_iso(value: str) -> str:
    """reports_client normalizes exome dates to DD-MM-YYYY; the sheet
    stores/expects YYYY-MM-DD (see _format_date above)."""
    m = _EXOME_DATE_RE.match(str(value or "").strip())
    if not m:
        return ""
    d, mo, y = m.groups()
    return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"


def _exome_release_dates_by_anderson_id() -> dict[str, str]:
    import reports_client

    if not reports_client.is_configured():
        return {}

    dates: dict[str, str] = {}
    for rec in reports_client.list_reports():
        and_id = str(rec.get("and_id") or "").strip().upper()
        iso = _exome_date_to_iso(rec.get("report_release_date"))
        if and_id and iso:
            dates[and_id] = iso
    return dates


def sync_release_dates_from_exome_tracker() -> dict:
    """Auto-fill CMC's "Report released date" from the exome tracker's own
    release date for any CMC sample that already has one there but not here,
    matched by Anderson ID. Best-effort: any failure is returned, never
    raised, since this runs opportunistically (after an exome edit, and on
    a periodic timer) and must never disrupt its caller.
    """
    try:
        exome_dates = _exome_release_dates_by_anderson_id()
    except Exception as exc:  # noqa: BLE001 - reports API being down shouldn't break the caller
        return {"success": False, "error": str(exc)}

    if not exome_dates:
        return {"success": True, "updated": 0}

    try:
        all_data = get_all_data()
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}

    items = []
    for sheet_name, sheet in all_data.get("sheets", {}).items():
        for row in sheet.get("rows", []):
            if row.get("reportReleasedDate"):
                continue  # already filled — exome isn't the only way this gets set
            and_id = str(row.get("andersonId") or "").strip().upper()
            row_index = row.get("_rowIndex")
            released = exome_dates.get(and_id)
            if and_id and row_index and released:
                items.append({"sheetName": sheet_name, "rowIndex": row_index, "value": released})

    if not items:
        return {"success": True, "updated": 0}

    result = update_report_released_date_bulk(items)
    result.setdefault("updated", len(items) if result.get("success") else 0)
    return result


_exome_sync_scheduler = None


def schedule_exome_release_sync() -> None:
    """Periodic safety-net poll, catching anything the after-edit trigger in
    exome_api.py missed (a transient failure, or an edit path it doesn't
    hook). Runs every CMC_ST_EXOME_SYNC_MINUTES minutes."""
    global _exome_sync_scheduler
    if not ENABLE_EXOME_SYNC or _exome_sync_scheduler is not None:
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    def _run():
        try:
            result = sync_release_dates_from_exome_tracker()
            if result.get("updated"):
                print(f"[cmc_sample_tracking] exome sync filled {result['updated']} release date(s)")
        except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
            print(f"[cmc_sample_tracking] exome sync job failed: {exc}")

    _exome_sync_scheduler = BackgroundScheduler(timezone=TZ_NAME)
    _exome_sync_scheduler.add_job(_run, IntervalTrigger(minutes=EXOME_SYNC_MINUTES))
    _exome_sync_scheduler.start()
    print(f"[cmc_sample_tracking] exome release-date sync scheduled every {EXOME_SYNC_MINUTES} min")


def trigger_exome_sync_async() -> None:
    """Fire-and-forget sync, called right after an exome report's release
    date is set/edited, so the CMC sheet picks it up within seconds instead
    of waiting for the next periodic poll. Runs off-thread so a slow or
    failing sync never delays the exome tracker's own response.
    """
    import threading

    def _run():
        try:
            result = sync_release_dates_from_exome_tracker()
            if result.get("updated"):
                print(f"[cmc_sample_tracking] exome sync (post-edit) filled {result['updated']} release date(s)")
        except Exception as exc:  # noqa: BLE001 - never let this affect the exome save
            print(f"[cmc_sample_tracking] exome sync (post-edit) failed: {exc}")

    threading.Thread(target=_run, daemon=True).start()


# --- Mail ---------------------------------------------------------------

_DATA_URL_RE = re.compile(r"^data:([^;]+);base64,(.+)$", re.S)


def _build_message(*, to: str, cc: str, subject: str, text_body: str,
                    html_body: str, attachments: list[dict]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject or "(No Subject)"
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    for att in attachments or []:
        m = _DATA_URL_RE.match(str((att or {}).get("dataUrl") or ""))
        if not m:
            continue
        content_type, b64 = m.groups()
        maintype, _, subtype = content_type.partition("/")
        msg.add_attachment(base64.b64decode(b64), maintype=maintype or "application",
                            subtype=subtype or "octet-stream",
                            filename=att.get("name") or "attachment")
    return msg


def _send_via_smtp(msg: EmailMessage) -> None:
    if not SMTP_HOST:
        raise SampleTrackingError("CMC_ST_SMTP_HOST is not configured")
    cls = smtplib.SMTP_SSL if SMTP_SECURE else smtplib.SMTP
    with cls(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        if not SMTP_SECURE:
            server.starttls()
        if SMTP_USER:
            server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


def _post_to_apps_script(action: str, params: dict) -> dict:
    try:
        resp = requests.post(
            APPS_SCRIPT_EXEC_URL,
            data=json.dumps({"action": action, **params}),
            headers={"Content-Type": "text/plain"},
            timeout=30,
        )
        return resp.json()
    except Exception as exc:  # noqa: BLE001 - mirrors the Node fallback's catch-all
        return {"success": False, "error": str(exc)}


def _send_via_apps_script(params: dict) -> dict:
    return _post_to_apps_script("sendEmail", params)


def send_email_action(params: dict) -> dict:
    if APPS_SCRIPT_EXEC_URL:
        return _send_via_apps_script(params)

    try:
        raw_body = re.sub(r"\n\n(Thanks\b)", r"\n\1", str(params.get("body") or ""))

        html_body = params.get("htmlBody")
        if html_body:
            html_body = re.sub(r"<br\s*/?><br\s*/?>(Thanks\b)", r"<br>\1", html_body, flags=re.I)
        else:
            esc = (raw_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            html_body = (
                '<div style="font-family:Arial,sans-serif;font-size:14px;'
                'line-height:1.8;color:#222;max-width:700px;">'
                + esc.replace("\n", "<br>") + "</div>"
            )

        msg = _build_message(
            to=params.get("to") or "",
            cc=params.get("cc") or "",
            subject=params.get("subject") or "",
            text_body=raw_body,
            html_body=html_body,
            attachments=params.get("attachments") or [],
        )
        _send_via_smtp(msg)
        return {"success": True}
    except Exception as exc:  # noqa: BLE001 - reported back to the caller as JSON
        return {"success": False, "error": str(exc)}


# --- Daily TAT-deadline alert job ---------------------------------------

def _is_released(row: dict) -> bool:
    status = (row.get("status") or "").lower()
    return bool(
        "release" in status or "complete" in status
        or row.get("reportReleasedDate") or row.get("rawDataSentTo")
    )


def _due_state(deadline: str, today: datetime.date) -> str | None:
    try:
        deadline_date = datetime.strptime(deadline[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    if deadline_date == today:
        return "Due Today"
    if deadline_date < today:
        return "Overdue"
    return None


def send_tat_deadline_emails() -> None:
    all_data = get_all_data()
    today = datetime.now().date()

    report_alerts, raw_data_alerts = [], []
    for sheet_name, sheet in all_data.get("sheets", {}).items():
        for row in sheet.get("rows", []):
            if _is_released(row):
                continue

            if row.get("tatReport"):
                state = _due_state(row["tatReport"], today)
                if state:
                    report_alerts.append({**row, "alertType": f"Report {state}",
                                           "deadline": row["tatReport"]})

            if row.get("tatRawData"):
                state = _due_state(row["tatRawData"], today)
                if state:
                    raw_data_alerts.append({**row, "alertType": f"Raw Data {state}",
                                             "deadline": row["tatRawData"]})

    if report_alerts:
        _send_alert_email(report_alerts, "TAT Report Deadline Alert", "#d9534f")
    if raw_data_alerts:
        _send_alert_email(raw_data_alerts, "TAT Raw Data Deadline Alert", "#f0ad4e")
    if not report_alerts and not raw_data_alerts:
        print("[cmc_sample_tracking] No TAT deadlines found for today.")


def _alert_row_html(sample: dict, index: int, theme_color: str) -> str:
    bg = "#ffffff" if index % 2 == 0 else "#f9f9f9"
    return f"""
      <tr style="background-color: {bg}; border-bottom: 1px solid #eee;">
        <td style="padding: 12px;"><strong>{sample.get('andersonId') or 'N/A'}</strong><br><small style="color: #888;">{sample.get('sampleNumber') or ''}</small></td>
        <td style="padding: 12px;">{sample.get('name') or 'N/A'}<br><small style="color: #666;">{sample.get('clientName') or ''}</small></td>
        <td style="padding: 12px;">{sample.get('testName') or 'N/A'}</td>
        <td style="padding: 12px; color: {theme_color}; font-weight: bold;">{sample.get('deadline')}</td>
        <td style="padding: 12px;"><span style="background: {theme_color}15; color: {theme_color}; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: bold; border: 1px solid {theme_color}30;">{sample.get('alertType')}</span></td>
        <td style="padding: 12px; color: #777;">{sample.get('_sourceSheet')}</td>
      </tr>
    """


def _send_alert_email(samples: list[dict], alert_category: str, theme_color: str) -> None:
    subject = f"TAT Alert - {alert_category}: {len(samples)} Samples Identified"

    rows_html = "".join(_alert_row_html(s, i, theme_color) for i, s in enumerate(samples))
    html_body = f"""
    <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; max-width: 900px; border: 1px solid #eee; border-radius: 8px; overflow: hidden;">
      <div style="background-color: {theme_color}; color: white; padding: 20px; text-align: center;">
        <h2 style="margin: 0;">{alert_category}</h2>
        <p style="margin: 5px 0 0 0; opacity: 0.9;">Action required for the following samples</p>
      </div>
      <div style="padding: 20px;">
        <table border="0" cellpadding="10" style="border-collapse: collapse; width: 100%; font-size: 14px;">
          <thead>
            <tr style="border-bottom: 2px solid #eee; text-align: left; color: #666;">
              <th style="padding: 12px;">Anderson ID</th>
              <th style="padding: 12px;">Patient/Client</th>
              <th style="padding: 12px;">Test</th>
              <th style="padding: 12px;">Deadline</th>
              <th style="padding: 12px;">Category</th>
              <th style="padding: 12px;">Sheet</th>
            </tr>
          </thead>
          <tbody>
            {rows_html}
          </tbody>
        </table>
        <div style="margin-top: 30px; text-align: center;">
          <p style="margin-bottom: 20px; color: #666;">Please update the status in the tracker once the task is completed.</p>
          <a href="{DASHBOARD_URL}" style="background-color: #3498db; color: white; padding: 12px 25px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">Open Lab Tracker Dashboard</a>
        </div>
      </div>
      <div style="background-color: #f8f9fa; padding: 15px; text-align: center; font-size: 11px; color: #999; border-top: 1px solid #eee;">
        This is an automated system notification. Please do not reply to this email.
      </div>
    </div>
    """

    if APPS_SCRIPT_EXEC_URL:
        # Same path the "Send Mail" button uses (MailApp, via Code.gs's
        # doPost) — no separate SMTP setup needed when a sheet's exec URL
        # is already the data source.
        result = _send_via_apps_script({
            "to": ALERT_RECIPIENTS,
            "subject": subject,
            "body": "This message requires an HTML-capable mail client to view.",
            "htmlBody": html_body,
        })
        if not result.get("success"):
            raise SampleTrackingError(result.get("error") or "Apps Script sendEmail failed")
    else:
        msg = EmailMessage()
        msg["From"] = MAIL_FROM
        msg["To"] = ALERT_RECIPIENTS
        msg["Subject"] = subject
        msg.set_content("This message requires an HTML-capable mail client to view.")
        msg.add_alternative(html_body, subtype="html")
        _send_via_smtp(msg)
    print(f"[cmc_sample_tracking] TAT alert sent: {subject} to {ALERT_RECIPIENTS}")


_scheduler = None


def schedule_tat_alerts() -> None:
    """Start the daily TAT-deadline alert job, matching the standalone app's
    node-cron schedule (CMC_ST_TAT_ALERT_CRON, default 09:00 daily)."""
    global _scheduler
    if not ENABLE_TAT_ALERTS or _scheduler is not None:
        return

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    def _run():
        try:
            send_tat_deadline_emails()
        except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
            print(f"[cmc_sample_tracking] TAT alert job failed: {exc}")

    _scheduler = BackgroundScheduler(timezone=TZ_NAME)
    _scheduler.add_job(_run, CronTrigger.from_crontab(TAT_ALERT_CRON, timezone=TZ_NAME))
    _scheduler.start()
    print(f'[cmc_sample_tracking] TAT alerts scheduled with cron "{TAT_ALERT_CRON}"')
