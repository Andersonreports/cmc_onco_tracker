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
    "clinical-history": {
        "label": "Clinical History Tracker",
        "path": "/clinical-history/",
        "page": "clinical-history.html",
        "section": "bioinfo",
    },
    "cmc-sample-tracking": {
        "label": "CMC Sample Tracking",
        "path": "/cmc-sample-tracking/",
        "page": "cmc-sample-tracking.html",
        "section": "bioinfo",
    },
    "coverage": {
        "label": "Coverage Checker",
        "path": "/anderson-coverage/",
        "page": None,
        "section": "anderson",
    },
}

GRANTABLE = (ADMIN,) + tuple(TRACKERS)

LABELS = {ADMIN: "Admin", **{k: v["label"] for k, v in TRACKERS.items()}}

# A role is what an admin actually assigns. Its trackers are derived from the
# section tree rather than listed, so a tracker added to SECTIONS/TRACKERS lands
# in the right roles on its own — "sections" is what the role reaches, "without"
# carves a branch back out of it.
ROLES = {
    "cmc": {
        "label": "CMC",
        "sections": ("cmc",),
        "home": "/cmc/",
    },
    "anderson": {
        "label": "Anderson",
        "sections": ("anderson",),
        "without": ("bioinfo",),
        "home": "/anderson/",
    },
    # Same reach as each other; they differ only in what they may do inside a
    # tracker, which "duty" names and exome_roles turns into permissions.
    "and-bioinfo-primary": {
        "label": "Anderson + Bioinfo · Primary Team",
        "sections": ("anderson",),
        "home": "/anderson/",
        "duty": "primary",
    },
    "and-bioinfo-lead": {
        "label": "Anderson + Bioinfo · Team Lead",
        "sections": ("anderson",),
        "home": "/anderson/",
        "duty": "lead",
    },
    "and-bioinfo-member": {
        "label": "Anderson + Bioinfo · Team Member",
        "sections": ("anderson",),
        "home": "/anderson/",
        "duty": "member",
    },
    # Named by tracker rather than section, for people who need only this one
    # tracker and nothing else the bioinfo section would otherwise bundle in.
    "clinical-history-only": {
        "label": "Clinical History Tracker Only",
        "trackers": ("clinical-history",),
        # Lands on the Anderson Trackers hub, same as the bioinfo roles, rather
        # than straight into the one tracker — access-gate.js masks Coverage
        # Checker for them there, and Exome once they open Bioinfo Trackers.
        "home": "/anderson/",
    },
    ADMIN: {
        "label": "Admin",
        "everything": True,
        "home": "/",
    },
}


# Assigned before the team duties existed; a lead is the closest equivalent.
ALIASES = {"and-bioinfo": "and-bioinfo-lead"}


def _parts(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    return [ALIASES.get(s, s) for s in (str(p).strip() for p in value) if s]


def duty_of(value) -> str:
    """What the role may do inside a tracker, as opposed to which it reaches."""
    role = role_of(value)
    if role == ADMIN:
        return ADMIN
    return ROLES.get(role, {}).get("duty", "") if role else ""


def role_trackers(role_key: str) -> list[str]:
    spec = ROLES.get(role_key)
    if not spec:
        return []
    if spec.get("everything"):
        return list(TRACKERS)
    if spec.get("trackers"):
        return list(spec["trackers"])
    reaches = set(spec.get("sections", ()))
    without = set(spec.get("without", ()))
    keys = []
    for key, tracker in TRACKERS.items():
        chain = set(_section_chain(tracker["section"]))
        if chain & reaches and not chain & without:
            keys.append(key)
    return keys


def role_of(value) -> str | None:
    """The named role stored for a user, if their value carries one."""
    for part in _parts(value):
        if part in ROLES:
            return part
    return None


def normalize(value) -> list[str]:
    """Expand a stored value into the grants the page gates test against.

    Takes a role name, or the bare tracker keys that predate roles, so an
    older stored value keeps working untouched.
    """
    seen, out = set(), []
    for part in _parts(value):
        granted = ([ADMIN] if part == ADMIN else []) + role_trackers(part) \
            if part in ROLES else [part]
        for key in granted:
            if key in GRANTABLE and key not in seen:
                seen.add(key)
                out.append(key)
    return out


def to_stored(accesses) -> str:
    """A role is stored under its own name; only pre-role values keep a list,
    since expanding a role would lose the landing page that comes with it."""
    role = role_of(accesses)
    return role if role else ",".join(normalize(accesses))


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


def open_sections(accesses) -> list[str]:
    """Every section the user may open, nested ones included, so a section page
    can hide the cards leading somewhere they'd only be bounced back from."""
    return [k for k in SECTIONS if can_open_section(accesses, k)]


def home_for(accesses) -> str:
    role = role_of(accesses)
    if role:
        return ROLES[role]["home"]
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
