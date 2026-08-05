from __future__ import annotations

ADMIN = "admin"

SECTIONS = {
    "cmc": {
        "label": "CMC Trackers",
        "path": "/cmc/",
        "page": "cmc.html",
        "parent": None,
    },
    "anderson": {
        "label": "Anderson Trackers",
        "path": "/anderson/",
        "page": "anderson.html",
        "parent": None,
    },
    "bioinfo": {
        "label": "Bioinfo Trackers",
        "path": "/bioinfo/",
        "page": "bioinfo.html",
        "parent": "anderson",
    },
}

TRACKERS = {
    "cmc-onco": {
        "label": "CMC ONCO Tracker",
        "path": "/cmc-onco/",
        "page": "cmc-onco.html",
        "section": "cmc",
    },
    "exome": {
        "label": "Exome Sample Tracker",
        "path": "/exome-tracker/",
        "page": "exome-tracker/index.html",
        "section": "bioinfo",
    },
}

GRANTABLE = (ADMIN,) + tuple(TRACKERS)

LABELS = {ADMIN: "Admin", **{k: v["label"] for k, v in TRACKERS.items()}}

LEGACY = {
    "cmc": ["cmc-onco"],
    "anderson": ["exome"],
}


def normalize(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",")]
    else:
        parts = [str(p).strip() for p in value]
    expanded = []
    for p in parts:
        expanded.extend(LEGACY.get(p, [p]))
    seen, out = set(), []
    for p in expanded:
        if p and p in GRANTABLE and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def to_stored(accesses) -> str:
    return ",".join(normalize(accesses))


def is_admin(accesses) -> bool:
    return ADMIN in normalize(accesses)


def tracker_keys(accesses) -> list[str]:
    acc = normalize(accesses)
    if ADMIN in acc:
        return list(TRACKERS)
    return [a for a in acc if a in TRACKERS]


def can_open_tracker(accesses, key: str) -> bool:
    return key in tracker_keys(accesses)


def _section_chain(section_key: str) -> list[str]:
    chain, cur = [], section_key
    while cur:
        chain.append(cur)
        cur = SECTIONS.get(cur, {}).get("parent")
    return chain


def can_open_section(accesses, section_key: str) -> bool:
    for key in tracker_keys(accesses):
        if section_key in _section_chain(TRACKERS[key]["section"]):
            return True
    return False


def visible_sections(accesses, parent=None) -> list[str]:
    return [k for k, v in SECTIONS.items()
            if v["parent"] == parent and can_open_section(accesses, k)]


def home_for(accesses) -> str:
    acc = normalize(accesses)
    if not acc:
        return "/login"
    if ADMIN in acc:
        return "/"
    keys = tracker_keys(acc)
    if not keys:
        return "/login"
    if len(keys) == 1:
        return TRACKERS[keys[0]]["path"]
    tops = visible_sections(acc, parent=None)
    if len(tops) == 1:
        return SECTIONS[tops[0]]["path"]
    return "/"
