"""CLI for backend administration, run inside the container:

    docker exec -it fyr python3 manage.py adduser

Never exposed over the network - this is the only way accounts get created,
by design (no self-register endpoint).
"""

import getpass
import sys

from app.auth import VALID_ROLES, create_user, load_users
from app.config import Config

_CONFIG = {"DATA_DIR": Config.DATA_DIR}


def adduser():
    username = input("Username: ").strip()
    if not username:
        print("Username cannot be empty.")
        return 1

    existing = load_users(_CONFIG)
    if username in existing:
        confirm = input(f"'{username}' already exists - overwrite? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return 1

    role = input(f"Role [{'/'.join(VALID_ROLES)}] (default: visitor): ").strip() or "visitor"
    if role not in VALID_ROLES:
        print(f"Role must be one of {VALID_ROLES}.")
        return 1

    password = getpass.getpass("Password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        return 1
    if password != getpass.getpass("Confirm password: "):
        print("Passwords did not match.")
        return 1

    create_user(username, password, role, _CONFIG)
    print(f"User '{username}' created with role '{role}'.")
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "adduser":
        print("Usage: python3 manage.py adduser")
        return 1
    return adduser()


if __name__ == "__main__":
    sys.exit(main())
