from flask import Blueprint, current_app, jsonify, request

from ..auth import require_role
from ..prefs import bump_epoch, clear_prefs, get_epoch
from .config import _load_yaml, _save_yaml, _layout_path

defaults_bp = Blueprint("defaults", __name__)

# Which settings an admin may set a server-wide default for, and what type
# each must be. Deliberately a plain allowlist here instead of mirroring the
# frontend's full settings schema (constants/settings.js) - the server only
# needs to refuse garbage shapes; whether "palette: neon" is a real palette
# is the frontend's business (an unknown value just falls back to its own
# built-in default there).
_ALLOWED = {
    "palette": str,
    "theme": str,
    "fontStyle": str,
    "roundness": str,
    "colorMode": str,
    "bgEffect": str,
    "hoverEffect": str,
    "tilesPerRow": (str, int),
    "gap": int,
    "statusInterval": int,
    "loaderMode": str,
    "dockLabels": str,
    "siteTitle": str,
    "showVersion": str,
    "copyrightText": str,
    "language": str,
    "narrowLauncherLast": str,
    "tileOpacity": int,
    "tileBlur": int,
    "gridMargin": int,
    "contentWidth": int,
    "fullscreenMargin": int,
}


def _clean_defaults(raw):
    cleaned = {}
    for key, value in raw.items():
        expected = _ALLOWED.get(key)
        if expected is None or isinstance(value, bool) or not isinstance(value, expected):
            continue
        if isinstance(value, str):
            value = value.strip()[:40]
        elif not -1000 <= value <= 5000:
            continue
        cleaned[key] = value
    return cleaned


@defaults_bp.route("/api/defaults", methods=["GET"])
def get_defaults():
    data = _load_yaml(_layout_path(current_app.config), {})
    return jsonify({"defaults": data.get("defaults") or {}, "epoch": get_epoch(current_app.config)})


@defaults_bp.route("/api/defaults", methods=["PUT"])
@require_role("admin")
def put_defaults():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("defaults"), dict):
        return jsonify({"error": "invalid_body"}), 400
    path = _layout_path(current_app.config)
    existing = _load_yaml(path, {})
    existing["defaults"] = _clean_defaults(body["defaults"])
    _save_yaml(path, existing)
    return jsonify({"ok": True})


@defaults_bp.route("/api/defaults/reset-user-prefs", methods=["POST"])
@require_role("admin")
def reset_all_user_prefs():
    """Everyone goes back to the server defaults: saved prefs for every
    account are deleted, and the epoch bump makes every browser (including
    logged-out visitors, whom the server has no record of) discard the
    overrides it has cached locally the next time it loads."""
    clear_prefs(current_app.config)
    epoch = bump_epoch(current_app.config)
    return jsonify({"ok": True, "epoch": epoch})
