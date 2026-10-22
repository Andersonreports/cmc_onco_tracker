"""CMC Research Samples (plasmids) tracker.

Unlike cmc_sample_tracking.py's main sheet, this source sheet ("CMC Plasmids
followup") needs no write-back and no service-account auth — it's shared as
"Anyone with the link can view", so a plain CSV export fetch is enough.
"""
from __future__ import annotations

import csv
import io
import os
import re
import time
from datetime import datetime, timezone

import requests

from env_loader import load_backend_env

load_backend_env()

SPREADSHEET_ID = os.getenv(
    "CMC_RS_SPREADSHEET_ID", "1-pSuyxJWgAtBpgVh9kebAxqvK3ZgwTUC88HDhztjIQY")
SHEET_GID = os.getenv("CMC_RS_SHEET_GID", "0")
CACHE_SECONDS = float(os.getenv("CMC_RS_CACHE_SECONDS", "60"))

_EXPORT_URL = "https://docs.google.com/spreadsheets/d/{id}/export?format=csv&gid={gid}"

_COLUMN_ALIASES = {
    "slNo": ("S.no", "Sl No", "S No"),
    "sampleName": ("Sample Name",),
    "sampleReceivedDate": ("Sample Recieved Date", "Sample Received Date"),
    "assayRegistered": ("Assay Registered",),
    "libraryPreparationDate": ("Library Prepration Date", "Library Preparation Date"),
    "sequencedRunId": ("Sequenced and RUN ID", "Sequenced and Run ID"),
    "order": ("Order",),
}

_DATE_FIELDS = ("sampleReceivedDate", "libraryPreparationDate")

_DMY_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$")


class ResearchSamplesError(Exception):
    pass


def _norm_header(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


def _find_col(headers: list, *names: str) -> int:
    normed = [_norm_header(h) for h in headers]
    for name in names:
        try:
            return normed.index(_norm_header(name))
        except ValueError:
            continue
    return -1


def _get_string(row: list, idx: int) -> str:
    if idx < 0 or idx >= len(row) or row[idx] is None:
        return ""
    return str(row[idx]).strip()


def _format_date(val: str) -> str:
    s = (val or "").strip()
    if not s:
        return ""
    m = _DMY_RE.match(s)
    if not m:
        return s  # not a plain date, e.g. "RTR" or "EXCLUDED DUE TO LOW CONC"
    d, mo, y = m.groups()
    if len(y) == 2:
        y = "20" + y
    return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"


def _fetch_csv_rows() -> list[list[str]]:
    if not SPREADSHEET_ID:
        raise ResearchSamplesError("CMC_RS_SPREADSHEET_ID is not configured")
    url = _EXPORT_URL.format(id=SPREADSHEET_ID, gid=SHEET_GID)
    resp = requests.get(url, timeout=20)
    if resp.status_code != 200:
        raise ResearchSamplesError(
            f"Could not read the research samples sheet (HTTP {resp.status_code}) — "
            'make sure it\'s shared as "Anyone with the link can view"')
    resp.encoding = "utf-8"
    return list(csv.reader(io.StringIO(resp.text)))


def _process_rows(data: list[list[str]]) -> list[dict]:
    if len(data) < 2:
        return []

    headers = data[0]
    idx = {key: _find_col(headers, *names) for key, names in _COLUMN_ALIASES.items()}

    rows = []
    last_order = ""
    for r in data[1:]:
        if not _get_string(r, idx["sampleName"]):
            continue
        row = {key: _get_string(r, i) for key, i in idx.items() if key not in _DATE_FIELDS}
        for key in _DATE_FIELDS:
            row[key] = _format_date(_get_string(r, idx[key]))

        # The sheet only labels the first row of a batch with "Order N" —
        # every row after it (same run, same dates) is left blank but
        # belongs to that same order. Forward-fill so grouping/filtering by
        # order works on every row, not just batch leaders.
        if row["order"]:
            last_order = row["order"]
        else:
            row["order"] = last_order

        rows.append(row)
    return rows


_cache: dict | None = None
_cache_at = 0.0


def get_research_samples() -> dict:
    global _cache, _cache_at
    now = time.monotonic()
    if _cache is not None and (now - _cache_at) < CACHE_SECONDS:
        return _cache

    rows = _process_rows(_fetch_csv_rows())
    data = {
        "rows": rows,
        "metadata": {
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "totalSamples": len(rows),
        },
    }
    _cache = data
    _cache_at = now
    return data
