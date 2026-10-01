import os
import re
from functools import wraps

from flask import current_app, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from .fileio import load_json, save_json

VALID_ROLES = ("visitor", "admin")

# Usernames end up in file names (avatars/<username>.png) and URLs, so they
# are restricted to a safe alphabet - no path separators, no leading dot.
USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")

# A real-looking hash to check a nonexistent username's password against, so a
# lookup miss costs the same scrypt work as a real one - without this,
# response time alone tells an attacker which usernames exist.
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing-only")


def _users_path(config=None):
    config = config or current_app.config
    return os.path.join(config["DATA_DIR"], "users.json")


def load_users(config=None):
    return load_json(_users_path(config), {})


def save_users(users, config=None):
    save_json(_users_path(config), users)


def change_password(username, new_password, config=None):
    """Overwrites username's password hash in place, keeping their role.
    Caller must already have verified the current password - this only
    does the write."""
    users = load_users(config)
    if username not in users:
        raise KeyError(username)
    users[username]["password_hash"] = generate_password_hash(new_password)
    users[username]["session_epoch"] = int(users[username].get("session_epoch") or 0) + 1
    save_users(users, config)
    return users[username]["session_epoch"]


def session_epoch(username, config=None):
    """Bumped whenever every existing session of the account must stop working
    (password changed or reset, "sign out everywhere"). A session carries the
    epoch it was created under; current_user() refuses one that is behind."""
    return int((load_users(config).get(username) or {}).get("session_epoch") or 0)


def bump_session_epoch(username, config=None):
    users = load_users(config)
    if username not in users:
        raise KeyError(username)
    users[username]["session_epoch"] = int(users[username].get("session_epoch") or 0) + 1
    save_users(users, config)
    return users[username]["session_epoch"]


def create_user(username, password, role, config=None):
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}")
    if not USERNAME_RE.match(username or ""):
        raise ValueError("username may only contain letters, digits, '.', '_' and '-' (max 64)")
    users = load_users(config)
    users[username] = {
        "password_hash": generate_password_hash(password),
        "role": role,
    }
    save_users(users, config)


def verify_login(username, password, config=None):
    """Returns the user's role on success, or None on bad username/password.
    Deliberately doesn't distinguish "no such user" from "wrong password" in
    its return value - that distinction belongs in a log, never in what a
    client can observe, or it becomes a way to enumerate valid usernames."""
    users = load_users(config)
    user = users.get(username)
    hash_to_check = user["password_hash"] if user else _DUMMY_HASH
    valid = check_password_hash(hash_to_check, password)
    if not user or not valid:
        return None
    return user["role"]


def current_user(config=None):
    """The logged-in session's user, re-checked against users.json on
    every call rather than trusting session["role"] as set at login. A
    session's role is otherwise just a stale snapshot from whenever they
    last logged in - without this, an admin demoted (or deleted) via the
    Admin Panel keeps their old privileges on every request until their
    cookie naturally expires (up to 30 days by default) or they happen to
    log out, which defeats the entire point of server-side sessions being
    revocable in the first place. Returns None if not logged in, or if the
    account no longer exists - clearing the session in that second case,
    since there's nothing left for it to legitimately refer to. The same
    goes for a session created before the account's password was last
    changed (see session_epoch)."""
    if "username" not in session:
        return None
    username = session["username"]
    users = load_users(config)
    user = users.get(username)
    if not user or int(session.get("epoch") or 0) != int(user.get("session_epoch") or 0):
        session.clear()
        return None
    return {
        "username": username,
        "role": user.get("role"),
        "display_name": user.get("display_name"),
        "has_avatar": bool(user.get("avatar_ext")),
    }


def require_role(*roles):
    """Route decorator: 401 if not logged in (or no longer a real
    account), 403 if logged in but not one of `roles`. @require_role()
    with no args just means "any logged-in user"."""

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify({"error": "not_authenticated"}), 401
            if roles and user["role"] not in roles:
                return jsonify({"error": "forbidden"}), 403
            return fn(*args, **kwargs)

        return wrapped

    return decorator
