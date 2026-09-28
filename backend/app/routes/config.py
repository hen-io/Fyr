import os

import yaml
from flask import Blueprint, current_app, jsonify, request, send_from_directory, session

from ..auth import require_role

config_bp = Blueprint("config", __name__)


def _apps_path(cfg):
    return os.path.join(cfg["CONFIG_DIR"], "apps.config")


def _layout_path(cfg):
    return os.path.join(cfg["CONFIG_DIR"], "ui.conf")


def _load_yaml(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or default


def _save_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


@config_bp.route("/api/apps", methods=["GET"])
def get_apps():
    data = _load_yaml(_apps_path(current_app.config), {"apps": []})
    apps = data.get("apps", [])
    if "username" not in session:
        # visibility: "authenticated" must actually hide the tile, not just
        # let the frontend choose not to render it - otherwise anyone can
        # read it straight off this endpoint. Filter here, not in TileGrid.
        apps = [app for app in apps if app.get("visibility") != "authenticated"]
    return jsonify(apps)


@config_bp.route("/api/apps", methods=["PUT"])
@require_role("admin")
def put_apps():
    body = request.get_json(silent=True)
    if not isinstance(body, list):
        return jsonify({"error": "invalid_body"}), 400
    _save_yaml(_apps_path(current_app.config), {"apps": body})
    return jsonify({"ok": True})


@config_bp.route("/api/layout", methods=["GET"])
def get_layout():
    data = _load_yaml(_layout_path(current_app.config), {"layout": {}})
    layout = data.get("layout", {})
    if "username" not in session:
        # Layout entries are keyed by app title, so a hidden app's title
        # (though not its url/icon) would otherwise leak through here even
        # after get_apps() filters it out - same reasoning as there.
        apps = _load_yaml(_apps_path(current_app.config), {"apps": []}).get("apps", [])
        hidden_titles = {app["title"] for app in apps if app.get("visibility") == "authenticated"}
        layout = {title: pos for title, pos in layout.items() if title not in hidden_titles}
    return jsonify(layout)


@config_bp.route("/api/layout", methods=["PUT"])
@require_role("admin")
def put_layout():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "invalid_body"}), 400
    # ui.conf also holds "widgets" as a sibling key - read-modify-write
    # instead of overwriting the whole file, or saving a layout would
    # silently wipe out every configured widget.
    path = _layout_path(current_app.config)
    existing = _load_yaml(path, {})
    existing["layout"] = body
    _save_yaml(path, existing)
    return jsonify({"ok": True})


@config_bp.route("/icons/<path:filename>")
def serve_icon(filename):
    icons_dir = os.path.join(current_app.config["CONFIG_DIR"], "icons")
    return send_from_directory(icons_dir, filename)
