import os

from flask import Blueprint, current_app, jsonify, request, send_from_directory, session

from ..auth import change_password, current_user, load_users, require_role, save_users, verify_login
from ..prefs import clear_prefs, get_prefs, set_prefs
from ..ratelimit import is_locked_out, record_failure, record_success

auth_bp = Blueprint("auth", __name__)

# Whatever browsers actually produce from an <input type="file" accept="image/*">
# or a canvas .toBlob() - no re-encoding happens server-side (no image lib in
# requirements.txt), so the upload is stored byte-for-byte under whichever of
# these extensions matches its declared type.
_AVATAR_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
_MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _avatars_dir(config):
    return os.path.join(config["DATA_DIR"], "avatars")


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


@auth_bp.route("/api/me/prefs", methods=["DELETE"])
@require_role()
def reset_my_prefs():
    clear_prefs(current_app.config, session["username"])
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


@auth_bp.route("/api/me/profile", methods=["PUT"])
@require_role()
def update_my_profile():
    username = session["username"]
    body = request.get_json(silent=True) or {}
    display_name = (body.get("display_name") or "").strip()
    if len(display_name) > 60:
        return jsonify({"error": "display_name_too_long"}), 400

    users = load_users(current_app.config)
    users[username]["display_name"] = display_name or None
    save_users(users, current_app.config)
    return jsonify({"ok": True})


@auth_bp.route("/api/me/avatar", methods=["PUT"])
@require_role()
def upload_my_avatar():
    username = session["username"]
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "no_file"}), 400

    ext = _AVATAR_TYPES.get(file.mimetype)
    if not ext:
        return jsonify({"error": "unsupported_type"}), 400

    data = file.read(_MAX_AVATAR_BYTES + 1)
    if len(data) > _MAX_AVATAR_BYTES:
        return jsonify({"error": "file_too_large"}), 400

    avatars_dir = _avatars_dir(current_app.config)
    os.makedirs(avatars_dir, exist_ok=True)

    users = load_users(current_app.config)
    old_ext = users.get(username, {}).get("avatar_ext")
    # A different extension than last time (png -> jpg, say) would
    # otherwise leave the old file sitting there under its own name
    # forever - nothing points at it once avatar_ext changes below, but
    # it'd still be on disk.
    if old_ext and old_ext != ext:
        old_path = os.path.join(avatars_dir, f"{username}.{old_ext}")
        if os.path.exists(old_path):
            os.remove(old_path)

    with open(os.path.join(avatars_dir, f"{username}.{ext}"), "wb") as f:
        f.write(data)

    users[username]["avatar_ext"] = ext
    save_users(users, current_app.config)
    return jsonify({"ok": True})


@auth_bp.route("/api/me/avatar", methods=["DELETE"])
@require_role()
def delete_my_avatar():
    username = session["username"]
    users = load_users(current_app.config)
    ext = users.get(username, {}).get("avatar_ext")
    if ext:
        path = os.path.join(_avatars_dir(current_app.config), f"{username}.{ext}")
        if os.path.exists(path):
            os.remove(path)
        users[username]["avatar_ext"] = None
        save_users(users, current_app.config)
    return jsonify({"ok": True})


@auth_bp.route("/api/avatar/<username>")
def get_avatar(username):
    # Public (no login required) - an avatar is exactly as visible as the
    # tile grid itself already is to anyone with the URL, nothing new
    # exposed. send_from_directory rejects path traversal in `username`
    # the same way serve_icon (config.py) already relies on for filenames.
    users = load_users(current_app.config)
    ext = users.get(username, {}).get("avatar_ext")
    if not ext:
        return jsonify({"error": "not_found"}), 404
    return send_from_directory(_avatars_dir(current_app.config), f"{username}.{ext}")
