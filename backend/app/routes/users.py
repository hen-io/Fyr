import os

from flask import Blueprint, current_app, jsonify, session

from ..auth import USERNAME_RE, VALID_ROLES, change_password, create_user, load_users, require_role, save_users
from ..prefs import clear_prefs
from ..reqtools import json_object, secret, text

users_bp = Blueprint("users", __name__)


def _admin_count(users):
    return sum(1 for u in users.values() if u.get("role") == "admin")


@users_bp.route("/api/users", methods=["GET"])
@require_role("admin")
def list_users():
    users = load_users(current_app.config)
    return jsonify([{"username": name, "role": info.get("role")} for name, info in users.items()])


@users_bp.route("/api/users", methods=["POST"])
@require_role("admin")
def add_user():
    body = json_object()
    username = text(body, "username", 128)
    password = secret(body, "password")
    role = body.get("role") or "visitor"

    if not username:
        return jsonify({"error": "username_required"}), 400
    if not USERNAME_RE.match(username):
        return jsonify({"error": "invalid_username"}), 400
    if not isinstance(role, str) or role not in VALID_ROLES:
        return jsonify({"error": "invalid_role"}), 400
    if len(password) < 8:
        return jsonify({"error": "password_too_short"}), 400

    users = load_users(current_app.config)
    if username in users:
        return jsonify({"error": "username_taken"}), 409

    create_user(username, password, role, current_app.config)
    return jsonify({"ok": True}), 201


@users_bp.route("/api/users/<username>", methods=["DELETE"])
@require_role("admin")
def delete_user(username):
    # Both guards below exist for the same reason: an admin action must
    # never be able to lock every admin out of admin actions, including
    # by mistake - "delete every admin including yourself, one click at a
    # time" is an easy trap without them.
    if session.get("username") == username:
        return jsonify({"error": "cannot_delete_self"}), 400

    users = load_users(current_app.config)
    if username not in users:
        return jsonify({"error": "not_found"}), 404

    if users[username].get("role") == "admin" and _admin_count(users) <= 1:
        return jsonify({"error": "cannot_delete_last_admin"}), 400

    removed = users.pop(username)
    save_users(users, current_app.config)
    # Nothing of the account is left behind: its saved settings and picture go too.
    clear_prefs(current_app.config, username)
    ext = removed.get("avatar_ext")
    if ext and USERNAME_RE.match(username):
        try:
            os.remove(os.path.join(current_app.config["DATA_DIR"], "avatars", f"{username}.{ext}"))
        except OSError:
            pass
    return jsonify({"ok": True})


@users_bp.route("/api/users/<username>/password", methods=["PUT"])
@require_role("admin")
def reset_password(username):
    """An admin sets a new password for an account (a forgotten password).
    Every session that account had open ends."""
    password = secret(json_object(), "password")
    if len(password) < 8:
        return jsonify({"error": "password_too_short"}), 400
    if username not in load_users(current_app.config):
        return jsonify({"error": "not_found"}), 404
    epoch = change_password(username, password, current_app.config)
    if session.get("username") == username:
        session["epoch"] = epoch  # resetting your own password keeps you signed in
    return jsonify({"ok": True})


@users_bp.route("/api/users/<username>/role", methods=["PUT"])
@require_role("admin")
def change_role(username):
    role = json_object().get("role")
    if not isinstance(role, str) or role not in VALID_ROLES:
        return jsonify({"error": "invalid_role"}), 400

    users = load_users(current_app.config)
    if username not in users:
        return jsonify({"error": "not_found"}), 404

    if users[username].get("role") == "admin" and role != "admin" and _admin_count(users) <= 1:
        return jsonify({"error": "cannot_demote_last_admin"}), 400

    users[username]["role"] = role
    save_users(users, current_app.config)
    return jsonify({"ok": True})
