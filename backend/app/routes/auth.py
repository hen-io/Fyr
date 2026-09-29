from flask import Blueprint, current_app, jsonify, request, session

from ..auth import change_password, current_user, require_role, verify_login
from ..prefs import get_prefs, set_prefs
from ..ratelimit import is_locked_out, record_failure, record_success

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or is_locked_out(username):
        # Same error either way - "locked out" and "wrong password" must
        # look identical to the client, or the lockout itself becomes a way
        # to confirm a username is real.
        return jsonify({"error": "invalid_credentials"}), 401

    role = verify_login(username, password)
    if role is None:
        record_failure(username)
        return jsonify({"error": "invalid_credentials"}), 401

    record_success(username)
    session.clear()
    session["username"] = username
    session["role"] = role
    return jsonify({"username": username, "role": role})


@auth_bp.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/api/me")
def me():
    # Live-checked (current_user), not session["role"] directly - the
    # frontend polls this to decide what to show (admin-only buttons,
    # etc.), so a demoted/deleted account needs to see that reflected
    # here too, not just have the backend separately reject the actions.
    user = current_user(current_app.config)
    if not user:
        return jsonify({"error": "not_authenticated"}), 401
    return jsonify(user)


@auth_bp.route("/api/me/prefs", methods=["GET"])
@require_role()
def get_my_prefs():
    return jsonify(get_prefs(session["username"], current_app.config))


@auth_bp.route("/api/me/prefs", methods=["PUT"])
@require_role()
def put_my_prefs():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "invalid_body"}), 400
    set_prefs(session["username"], body, current_app.config)
    return jsonify({"ok": True})


@auth_bp.route("/api/me/password", methods=["PUT"])
@require_role()
def change_my_password():
    username = session["username"]
    if is_locked_out(username):
        # Same lockout mechanism as login - someone with a hijacked session
        # (or a shared machine) shouldn't get unlimited guesses at the
        # current password just because there's no username to enumerate.
        return jsonify({"error": "too_many_attempts"}), 429

    body = request.get_json(silent=True) or {}
    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""

    if verify_login(username, current_password) is None:
        record_failure(username)
        return jsonify({"error": "wrong_current_password"}), 401

    if len(new_password) < 8:
        return jsonify({"error": "password_too_short"}), 400

    record_success(username)
    change_password(username, new_password, current_app.config)
    return jsonify({"ok": True})
