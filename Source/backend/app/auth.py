import json
import os
from functools import wraps

from flask import current_app, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

VALID_ROLES = ("visitor", "admin")

# A real-looking hash to check a nonexistent username's password against, so a
# lookup miss costs the same scrypt work as a real one - without this,
# response time alone tells an attacker which usernames exist.
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing-only")


def _users_path(config=None):
    config = config or current_app.config
    return os.path.join(config["DATA_DIR"], "users.json")


def load_users(config=None):
    path = _users_path(config)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users, config=None):
    path = _users_path(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def change_password(username, new_password, config=None):
    """Overwrites username's password hash in place, keeping their role.
    Caller must already have verified the current password - this only
    does the write."""
    users = load_users(config)
    if username not in users:
        raise KeyError(username)
    users[username]["password_hash"] = generate_password_hash(new_password)
    save_users(users, config)


def create_user(username, password, role, config=None):
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}")
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


def require_role(*roles):
    """Route decorator: 401 if not logged in, 403 if logged in but not one
    of `roles`. @require_role() with no args just means "any logged-in user"."""

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if "username" not in session:
                return jsonify({"error": "not_authenticated"}), 401
            if roles and session.get("role") not in roles:
                return jsonify({"error": "forbidden"}), 403
            return fn(*args, **kwargs)

        return wrapped

    return decorator
