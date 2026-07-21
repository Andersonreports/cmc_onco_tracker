import sys

import role_store

ROLES = {"admin", "cmc", "anderson"}

USAGE = """\
Usage:
  python manage_roles.py list
  python manage_roles.py set <mobile> <role> [name...]
  python manage_roles.py delete <mobile>

Roles: admin | cmc | anderson
"""


def cmd_list(_):
    rows = role_store.all()
    print(f"[backend: {role_store.backend_name()}]")
    if not rows:
        print("No role mappings yet.")
        return
    print(f"{'MOBILE':<16}{'ROLE':<12}{'NAME'}")
    print("-" * 44)
    for r in rows:
        print(f"{r['mobile']:<16}{r['role']:<12}{r.get('name') or ''}")


def cmd_set(args):
    mobile, role = args[0], args[1]
    name = " ".join(args[2:]).strip() or None
    if role not in ROLES:
        sys.exit(f"Invalid role '{role}'. Choose one of: {', '.join(sorted(ROLES))}")
    key = role_store.normalize_mobile(mobile)
    if not key:
        sys.exit(f"Invalid mobile number: {mobile}")
    existed = role_store.get(key) is not None
    role_store.set_role(key, role, name)
    verb = "Updated" if existed else "Added"
    print(f"{verb} {key} -> {role}" + (f" ({name})" if name else "") + ".")


def cmd_delete(args):
    if not role_store.delete(args[0]):
        sys.exit(f"No such mapping: {args[0]}")
    print(f"Deleted role mapping for {role_store.normalize_mobile(args[0])}.")


COMMANDS = {
    "list": (cmd_list, 0),
    "set": (cmd_set, 2),
    "delete": (cmd_delete, 1),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(USAGE)
        sys.exit(1)
    fn, min_args = COMMANDS[sys.argv[1]]
    args = sys.argv[2:]
    if len(args) < min_args:
        sys.exit(f"'{sys.argv[1]}' needs at least {min_args} argument(s). See --help.")
    fn(args)


if __name__ == "__main__":
    main()
