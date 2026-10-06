import os

from flask import Blueprint, current_app, jsonify, session

from .. import audit
from ..auth import USERNAME_RE, VALID_ROLES, Refused, change_password, create_user, load_users, require_role, update_users, verify_login
from ..passwords import MAX_LENGTH, password_problem
from ..prefs import clear_prefs
from ..ratelimit import is_locked_out, record_failure, record_success
from ..reqtools import client_address, json_object, secret, text

users_bp = Blueprint("users", __name__)


def _admin_count(users):
    return sum(1 for u in users.values() if u.get("role") == "admin")


def _confirmed(body):
    """Every change to accounts needs the acting admin's own password again
    (`confirm_password`), not just their session. A session can be left open
    on a shared computer or be taken over; the password cannot - and without
    this, such a session could give itself or anyone else a new password and
    lock every real admin out. Returns None when confirmed, else the error
    response. Wrong guesses count against the same limiter as logins."""
    username = session["username"]
    address = client_address()
    if is_locked_out(username, address):
        return jsonify({"error": "too_many_attempts"}), 429
    if verify_login(username, secret(body, "confirm_password"), current_app.config) is None:
        record_failure(username, address)
        audit.record("admin_confirmation_failed", user=username, addr=address)
        return jsonify({"error": "confirm_password"}), 403
    record_success(username, address)
    return None


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
    password = secret(body, "password", MAX_LENGTH * 4)
    role = body.get("role") or "visitor"

    if not username:
        return jsonify({"error": "username_required"}), 400
    if not USERNAME_RE.match(username):
        return jsonify({"error": "invalid_username"}), 400
    if not isinstance(role, str) or role not in VALID_ROLES:
        return jsonify({"error": "invalid_role"}), 400
    problem = password_problem(password, username)
    if problem:
        return jsonify({"error": problem}), 400
    if username in load_users(current_app.config):
        return jsonify({"error": "username_taken"}), 409
    refusal = _confirmed(body)
    if refusal:
        return refusal

    try:
        create_user(username, password, role, current_app.config)
    except Refused as err:  # created by someone else in the meantime
        return jsonify({"error": err.code}), 409
    audit.record("user_created", user=username, role=role, by=session["username"])
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
    if username not in load_users(current_app.config):
        return jsonify({"error": "not_found"}), 404
    refusal = _confirmed(json_object())
    if refusal:
        return refusal

    def change(users):
        if username not in users:
            raise Refused("not_found")
        if users[username].get("role") == "admin" and _admin_count(users) <= 1:
            raise Refused("cannot_delete_last_admin")
        return users.pop(username)

    try:
        removed = update_users(change, current_app.config)
    except Refused as err:
        return jsonify({"error": err.code}), 404 if err.code == "not_found" else 400
    # Nothing of the account is left behind: its saved settings and picture go too.
    clear_prefs(current_app.config, username)
    ext = removed.get("avatar_ext")
    if ext and USERNAME_RE.match(username):
        try:
            os.remove(os.path.join(current_app.config["DATA_DIR"], "avatars", f"{username}.{ext}"))
        except OSError:
            pass
    audit.record("user_deleted", user=username, by=session["username"])
    return jsonify({"ok": True})


@users_bp.route("/api/users/<username>/password", methods=["PUT"])
@require_role("admin")
def reset_password(username):
    """An admin sets a new password for an account (a forgotten password).
    Every session that account had open ends."""
    body = json_object()
    password = secret(body, "password", MAX_LENGTH * 4)
    problem = password_problem(password, username)
    if problem:
        return jsonify({"error": problem}), 400
    if username not in load_users(current_app.config):
        return jsonify({"error": "not_found"}), 404
    refusal = _confirmed(body)
    if refusal:
        return refusal
    try:
        epoch = change_password(username, password, current_app.config)
    except KeyError:
        return jsonify({"error": "not_found"}), 404
    if session.get("username") == username:
        session["epoch"] = epoch  # resetting your own password keeps you signed in
    audit.record("password_reset", user=username, by=session["username"])
    return jsonify({"ok": True})


@users_bp.route("/api/users/<username>/role", methods=["PUT"])
@require_role("admin")
def change_role(username):
    body = json_object()
    role = body.get("role")
    if not isinstance(role, str) or role not in VALID_ROLES:
        return jsonify({"error": "invalid_role"}), 400
    users = load_users(current_app.config)
    if username not in users:
        return jsonify({"error": "not_found"}), 404
    if users[username].get("role") == "admin" and role != "admin" and _admin_count(users) <= 1:
        return jsonify({"error": "cannot_demote_last_admin"}), 400
    refusal = _confirmed(body)
    if refusal:
        return refusal

    def change(users):
        if username not in users:
            raise Refused("not_found")
        # checked again here, inside the same step as the write: two admins
        # demoting each other at the same moment must not leave none
        if users[username].get("role") == "admin" and role != "admin" and _admin_count(users) <= 1:
            raise Refused("cannot_demote_last_admin")
        users[username]["role"] = role

    try:
        update_users(change, current_app.config)
    except Refused as err:
        return jsonify({"error": err.code}), 404 if err.code == "not_found" else 400
    audit.record("role_changed", user=username, role=role, by=session["username"])
    return jsonify({"ok": True})
