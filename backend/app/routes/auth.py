import json
import os

from flask import Blueprint, current_app, jsonify, request, send_from_directory, session

from .. import audit
from ..auth import USERNAME_RE, bump_session_epoch, change_password, current_user, load_users, require_role, session_epoch, set_user_fields, verify_login
from ..passwords import MAX_LENGTH, password_problem
from ..prefs import clear_prefs, get_prefs, set_prefs
from ..imageio import ImageRejected, normalize_avatar
from ..ratelimit import is_locked_out, record_failure, record_success
from ..reqtools import client_address, json_object, secret, text

auth_bp = Blueprint("auth", __name__)

# What an upload may claim to be. The claim is only a first filter: the bytes
# are decoded and re-encoded (imageio.normalize_avatar) before anything is kept.
_AVATAR_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
_MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _avatars_dir(config):
    return os.path.join(config["DATA_DIR"], "avatars")


def _start_session(username, role):
    """A brand new session for this login: the old one's contents are dropped
    AND its id is replaced, so an id planted in the browser beforehand (session
    fixation) is worthless afterwards."""
    session.clear()
    regenerate = getattr(current_app.session_interface, "regenerate", None)
    if regenerate:
        regenerate(session)
    session["username"] = username
    session["role"] = role
    session["epoch"] = session_epoch(username, current_app.config)


@auth_bp.route("/api/login", methods=["POST"])
def login():
    body = json_object()
    username = text(body, "username", 128)
    password = secret(body, "password")
    address = client_address()

    if not username:
        return jsonify({"error": "invalid_credentials"}), 401
    if is_locked_out(username, address):
        # Same error either way - "locked out" and "wrong password" must
        # look identical to the client, or the lockout itself becomes a way
        # to confirm a username is real.
        audit.record("login_refused_locked", user=username, addr=address)
        return jsonify({"error": "invalid_credentials"}), 401

    role = verify_login(username, password)
    if role is None:
        record_failure(username, address)
        audit.record("login_failed", user=username, addr=address)
        return jsonify({"error": "invalid_credentials"}), 401

    record_success(username, address)
    _start_session(username, role)
    audit.record("login", user=username, addr=address)
    return jsonify({"username": username, "role": role})


@auth_bp.route("/api/logout", methods=["POST"])
def logout():
    if "username" in session:
        audit.record("logout", user=session["username"])
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
    if not isinstance(body, dict) or len(json.dumps(body)) > 65536:
        return jsonify({"error": "invalid_body"}), 400
    set_prefs(session["username"], body, current_app.config)
    return jsonify({"ok": True})


@auth_bp.route("/api/me/prefs", methods=["DELETE"])
@require_role()
def reset_my_prefs():
    clear_prefs(current_app.config, session["username"])
    return jsonify({"ok": True})


@auth_bp.route("/api/me/password", methods=["PUT"])
@require_role()
def change_my_password():
    username = session["username"]
    address = client_address()
    if is_locked_out(username, address):
        # Same lockout mechanism as login - someone with a hijacked session
        # (or a shared machine) shouldn't get unlimited guesses at the
        # current password just because there's no username to enumerate.
        return jsonify({"error": "too_many_attempts"}), 429

    body = json_object()
    current_password = secret(body, "current_password")
    new_password = secret(body, "new_password", MAX_LENGTH * 4)

    if verify_login(username, current_password) is None:
        record_failure(username, address)
        audit.record("password_change_refused", user=username, addr=address)
        return jsonify({"error": "wrong_current_password"}), 401
    record_success(username, address)

    problem = password_problem(new_password, username)
    if problem:
        return jsonify({"error": problem}), 400

    # Every other session of this account ends here; this one carries on.
    session["epoch"] = change_password(username, new_password, current_app.config)
    audit.record("password_changed", user=username, addr=address)
    return jsonify({"ok": True})


@auth_bp.route("/api/me/sessions", methods=["DELETE"])
@require_role()
def sign_out_everywhere_else():
    """Ends every other session of this account (a lost phone, a shared PC)."""
    session["epoch"] = bump_session_epoch(session["username"], current_app.config)
    audit.record("sessions_ended", user=session["username"])
    return jsonify({"ok": True})


@auth_bp.route("/api/me/profile", methods=["PUT"])
@require_role()
def update_my_profile():
    username = session["username"]
    body = json_object()
    raw = body.get("display_name")
    if raw is not None and (not isinstance(raw, str) or len(raw.strip()) > 60):
        return jsonify({"error": "display_name_too_long"}), 400
    display_name = (raw or "").strip()

    set_user_fields(username, current_app.config, display_name=display_name or None)
    return jsonify({"ok": True})


@auth_bp.route("/api/me/avatar", methods=["PUT"])
@require_role()
def upload_my_avatar():
    username = session["username"]
    if not USERNAME_RE.match(username):
        # Accounts created before usernames were restricted: never build a
        # file path from a name that could contain separators.
        return jsonify({"error": "avatar_unavailable"}), 400
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "no_file"}), 400

    if file.mimetype not in _AVATAR_TYPES:
        return jsonify({"error": "unsupported_type"}), 400

    data = file.read(_MAX_AVATAR_BYTES + 1)
    if len(data) > _MAX_AVATAR_BYTES:
        return jsonify({"error": "file_too_large"}), 400
    # Decoded and re-encoded rather than stored as sent: what ends up on disk
    # is always a real, small picture - never HTML with an image's file name,
    # and without the camera/location data a photo may carry.
    try:
        data = normalize_avatar(data)
    except ImageRejected:
        return jsonify({"error": "not_an_image"}), 400
    ext = "webp"

    avatars_dir = _avatars_dir(current_app.config)
    os.makedirs(avatars_dir, exist_ok=True)

    users = load_users(current_app.config)
    old_ext = users.get(username, {}).get("avatar_ext")
    if old_ext and old_ext != ext:
        old_path = os.path.join(avatars_dir, f"{username}.{old_ext}")
        if os.path.exists(old_path):
            os.remove(old_path)

    with open(os.path.join(avatars_dir, f"{username}.{ext}"), "wb") as f:
        f.write(data)

    set_user_fields(username, current_app.config, avatar_ext=ext)
    return jsonify({"ok": True})


@auth_bp.route("/api/me/avatar", methods=["DELETE"])
@require_role()
def delete_my_avatar():
    username = session["username"]
    if not USERNAME_RE.match(username):
        return jsonify({"error": "avatar_unavailable"}), 400
    users = load_users(current_app.config)
    ext = users.get(username, {}).get("avatar_ext")
    if ext:
        path = os.path.join(_avatars_dir(current_app.config), f"{username}.{ext}")
        if os.path.exists(path):
            os.remove(path)
        set_user_fields(username, current_app.config, avatar_ext=None)
    return jsonify({"ok": True})


@auth_bp.route("/api/avatar/<username>")
def get_avatar(username):
    # Public (no login required) - an avatar is exactly as visible as the
    # tile grid itself already is to anyone with the URL, nothing new
    # exposed. send_from_directory rejects path traversal in `username`
    # the same way serve_icon (config.py) already relies on for filenames.
    users = load_users(current_app.config)
    ext = users.get(username, {}).get("avatar_ext")
    if not ext or not USERNAME_RE.match(username):
        return jsonify({"error": "not_found"}), 404
    response = send_from_directory(_avatars_dir(current_app.config), f"{username}.{ext}")
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'"
    return response
