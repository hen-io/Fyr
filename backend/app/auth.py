import os
import re
import threading
import time
from functools import wraps

from flask import current_app, jsonify, request, session

from . import passwords
from .fileio import load_json, save_json

VALID_ROLES = ("visitor", "admin")

# Usernames end up in file names (avatars/<username>.png) and URLs, so they
# are restricted to a safe alphabet - no path separators, no leading dot.
USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")

# What survives when an existing account is given a new password and role from
# the command line (manage.py adduser on an existing name).
_PROFILE_FIELDS = ("display_name", "avatar_ext")


class Refused(Exception):
    """Raised inside an update_users() change to leave the file untouched;
    `code` is the error to report."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _users_path(config=None):
    config = config or current_app.config
    return os.path.join(config["DATA_DIR"], "users.json")


def load_users(config=None):
    return load_json(_users_path(config), {})


def save_users(users, config=None):
    # 0600: the file holds the password hashes - what an attacker would need
    # to start guessing passwords offline.
    save_json(_users_path(config), users, mode=0o600)


_users_lock = threading.RLock()


def update_users(change, config=None):
    """Every change to users.json goes through here: read, change, write as
    ONE step. Requests run on several threads; two of them each doing their own
    read-then-write could otherwise overwrite one another - and a profile
    update that started a moment earlier would silently undo a password change
    (bringing back the old password and the sessions it was meant to end).
    `change(users)` edits the dict in place; what it returns is returned. If it
    raises, nothing is written."""
    with _users_lock:
        users = load_users(config)
        result = change(users)
        save_users(users, config)
        return result


def _next_epoch(previous=0):
    """See session_epoch(). Never a value an earlier session of the same
    username could hold: it only goes up, and it starts from the clock rather
    than from zero - so deleting an account and creating one with the same name
    does not bring a forgotten old session back to life."""
    return max(int(previous or 0) + 1, int(time.time() * 1000))


def session_epoch(username, config=None):
    """Changed whenever every existing session of the account must stop working
    (password changed or reset, "sign out everywhere", account re-created). A
    session carries the epoch it was created under; current_user() refuses one
    that does not match."""
    return int((load_users(config).get(username) or {}).get("session_epoch") or 0)


def bump_session_epoch(username, config=None):
    def change(users):
        if username not in users:
            raise KeyError(username)
        users[username]["session_epoch"] = _next_epoch(users[username].get("session_epoch"))
        return users[username]["session_epoch"]

    return update_users(change, config)


def change_password(username, new_password, config=None):
    """Replaces the password and ends every session the account has (the
    caller's own carries on by adopting the returned epoch). The caller decides
    whether the change is allowed - this only does the write."""
    hashed = passwords.hash_password(new_password)  # slow on purpose: outside the lock

    def change(users):
        if username not in users:
            raise KeyError(username)
        users[username]["password_hash"] = hashed
        users[username]["session_epoch"] = _next_epoch(users[username].get("session_epoch"))
        return users[username]["session_epoch"]

    return update_users(change, config)


def create_user(username, password, role, config=None, overwrite=False):
    """A new account. With `overwrite` an existing account of that name gets
    this password and role instead (and loses its sessions) but keeps its
    profile; without it, an existing name is Refused("username_taken")."""
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}")
    if not USERNAME_RE.match(username or ""):
        raise ValueError("username may only contain letters, digits, '.', '_' and '-' (max 64)")
    hashed = passwords.hash_password(password)

    def change(users):
        previous = users.get(username)
        if previous is not None and not overwrite:
            raise Refused("username_taken")
        kept = {key: previous[key] for key in _PROFILE_FIELDS if previous and previous.get(key)}
        users[username] = {**kept, "password_hash": hashed, "role": role, "session_epoch": _next_epoch((previous or {}).get("session_epoch"))}

    update_users(change, config)


def set_user_fields(username, config=None, **fields):
    """Profile fields (display_name, avatar_ext) of an existing account."""

    def change(users):
        if username not in users:
            raise KeyError(username)
        users[username].update(fields)

    update_users(change, config)


def _upgrade_hash(username, stored, password, config):
    """The password was just proven correct against a hash made with older
    settings: store it again with the current ones. Sessions are untouched -
    the password itself has not changed."""
    try:
        fresh = passwords.hash_password(password)

        def change(users):
            if (users.get(username) or {}).get("password_hash") != stored:
                raise Refused("changed_meanwhile")
            users[username]["password_hash"] = fresh

        update_users(change, config)
    except (Refused, passwords.Busy, OSError):
        pass  # the login itself succeeded; the upgrade happens next time


def verify_login(username, password, config=None):
    """Returns the user's role on success, or None on bad username/password.
    Deliberately doesn't distinguish "no such user" from "wrong password" in
    its return value - that distinction belongs in a log, never in what a
    client can observe, or it becomes a way to enumerate valid usernames."""
    user = load_users(config).get(username)
    stored = user.get("password_hash") if isinstance(user, dict) else None
    # No such user (or no hash): still checked, against a dummy hash, so both cases cost the same work.
    valid, stale = passwords.verify_password(stored, password)
    if not isinstance(user, dict) or not stored or not valid:
        return None
    if stale:
        _upgrade_hash(username, stored, password, config)
    return user.get("role")


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
                # an account reaching for something only an admin may do: worth a line in the log
                from . import audit

                audit.record("refused", user=user["username"], role=user["role"], method=request.method, path=request.path)
                return jsonify({"error": "forbidden"}), 403
            return fn(*args, **kwargs)

        return wrapped

    return decorator
