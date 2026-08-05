import sys

import role_store

ROLES = {"admin", "cmc", "anderson"}

USAGE = """\
Usage:
  python manage_roles.py list
  python manage_roles.py set <mobile> <role> [name...]
  python manage_roles.py delete <mobile>
  python manage_roles.py setpass <mobile> <password>
  python manage_roles.py clearpass <mobile>

Roles: admin | cmc | anderson

setpass/clearpass control local password sign-in: a user with a local
password bypasses genetics API entirely and signs in straight against
this roles table.
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


def cmd_setpass(args):
    mobile, password = args[0], args[1]
    try:
        role_store.set_password(mobile, password)
    except ValueError as e:
        sys.exit(str(e))
    key = role_store.normalize_mobile(mobile)
    print(f"Set local password for {key}. They will now sign in without contacting IT's API.")


def cmd_clearpass(args):
    role_store.clear_password(args[0])
    key = role_store.normalize_mobile(args[0])
    print(f"Cleared local password for {key}. They will use IT's API again.")


COMMANDS = {
    "list": (cmd_list, 0),
    "set": (cmd_set, 2),
    "delete": (cmd_delete, 1),
    "setpass": (cmd_setpass, 2),
    "clearpass": (cmd_clearpass, 1),
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
