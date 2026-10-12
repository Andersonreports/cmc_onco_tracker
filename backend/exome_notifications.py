from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

_PATH = Path(os.getenv("EXOME_NOTIFICATIONS_PATH", "").strip()
             or Path(__file__).parent / "exome_notifications.json")
_lock = threading.Lock()
_MAX_KEPT = 1000


def _load() -> list[dict]:
    try:
        data = json.loads(_PATH.read_text() or "[]")
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _save(items: list[dict]) -> None:
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[-_MAX_KEPT:], indent=2))
    tmp.replace(_PATH)


def _key(name: str) -> str:
    return " ".join(str(name or "").lower().replace("dr.", "").replace(".", " ").split())


def _is_recipient(user: str, to: str) -> bool:
    u, t = _key(user), _key(to)
    return bool(u and t) and (t in u or u.split()[0] == t.split()[0])


def record_reviewer_changes(changes: list[tuple[dict, str, str]]) -> None:
    """changes: (row, previous reviewer, new reviewer) for each sample whose
    reviewer was set or changed. Best-effort — never blocks the save itself."""
    now = datetime.now().strftime("%d-%m-%Y")
    fresh = []
    for row, old, new in changes:
        old, new = str(old or "").strip(), str(new or "").strip()
        if not new or _key(old) == _key(new):
            continue
        fresh.append({
            "id": uuid.uuid4().hex,
            "to": new,
            "from": old,
            "kind": "transferred" if old else "allocated",
            "sample": str(row.get("name") or row.get("gen_id") or "").strip(),
            "gen_id": str(row.get("gen_id") or "").strip(),
            "run": str(row.get("run_text") or "").strip(),
            "by": str(row.get("last_updated_by") or "").strip(),
            "date": now,
            "at": datetime.now().isoformat(timespec="seconds"),
            "read_by": [],
        })
    if not fresh:
        return
    try:
        with _lock:
            _save(_load() + fresh)
    except Exception as e:
        print(f"[exome_notifications] not recorded: {e}")


def record_run_uploads(rows: list[dict]) -> None:
    """One notification per run in an upload, addressed to every team lead."""
    runs: dict[str, list[dict]] = {}
    for row in rows:
        runs.setdefault(str(row.get("run_text") or "").strip(), []).append(row)
    now = datetime.now()
    fresh = [{
        "id": uuid.uuid4().hex,
        "audience": "lead",
        "to": "",
        "from": "",
        "kind": "run_uploaded",
        "sample": "",
        "gen_id": "",
        "run": run,
        "count": len(group),
        "by": str(group[0].get("last_updated_by") or "").strip(),
        "date": now.strftime("%d-%m-%Y"),
        "at": now.isoformat(timespec="seconds"),
        "read_by": [],
    } for run, group in runs.items() if run]
    if not fresh:
        return
    try:
        with _lock:
            _save(_load() + fresh)
    except Exception as e:
        print(f"[exome_notifications] not recorded: {e}")


def _visible(n: dict, user: str, role: str) -> bool:
    if role == "admin":
        return True
    if n.get("audience"):
        return n["audience"] == role
    return _is_recipient(user, n.get("to", ""))


def for_user(user: str, role: str) -> list[dict]:
    items = [n for n in _load() if _visible(n, user, role)]
    out = []
    for n in reversed(items):
        out.append({**{k: v for k, v in n.items() if k != "read_by"},
                    "read": user in n.get("read_by", [])})
    return out[:200]


def mark_read(user: str, role: str, ids: list[str] | None) -> None:
    with _lock:
        items = _load()
        for n in items:
            if ids is not None and n["id"] not in ids:
                continue
            if _visible(n, user, role) and user not in n.setdefault("read_by", []):
                n["read_by"].append(user)
        _save(items)
