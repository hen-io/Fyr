"""CLI for backend administration, run inside the container:

    docker exec -it fyr python3 manage.py adduser

Never exposed over the network - this is the only way accounts get created,
by design (no self-register endpoint).
"""

import getpass
import sys

from app.auth import VALID_ROLES, create_user, load_users
from app.config import Config
from app.passwords import MIN_LENGTH, password_problem

_CONFIG = {"DATA_DIR": Config.DATA_DIR}

_PROBLEMS = {
    "password_too_short": f"Password must be at least {MIN_LENGTH} characters.",
    "password_too_long": "Password is too long.",
    "password_too_similar": "Password is too close to the username.",
    "password_too_common": "That password is too easy to guess (a well-known password, a keyboard run, or a common word with digits). Pick something else.",
}


def adduser():
    username = input("Username: ").strip()
    if not username:
        print("Username cannot be empty.")
        return 1

    existing = load_users(_CONFIG)
    if username in existing:
        confirm = input(f"'{username}' already exists - set a new password and role for it? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return 1

    role = input(f"Role [{'/'.join(VALID_ROLES)}] (default: visitor): ").strip() or "visitor"
    if role not in VALID_ROLES:
        print(f"Role must be one of {VALID_ROLES}.")
        return 1

    password = getpass.getpass("Password: ")
    problem = password_problem(password, username)
    if problem:
        print(_PROBLEMS[problem])
        return 1
    if password != getpass.getpass("Confirm password: "):
        print("Passwords did not match.")
        return 1

    try:
        # An existing account keeps its profile but loses every open session.
        create_user(username, password, role, _CONFIG, overwrite=True)
    except ValueError as err:
        print(f"Could not create the user: {err}")
        return 1
    print(f"User '{username}' {'updated' if username in existing else 'created'} with role '{role}'.")
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "adduser":
        print("Usage: python3 manage.py adduser")
        return 1
    return adduser()


if __name__ == "__main__":
    sys.exit(main())
