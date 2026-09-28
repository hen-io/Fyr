import os

import yaml
from flask import Blueprint, current_app, jsonify, request, send_from_directory, session

from ..auth import require_role

config_bp = Blueprint("config", __name__)


_UNCATEGORIZED = "_uncategorized"


def _apps_path(cfg):
    return os.path.join(cfg["CONFIG_DIR"], "apps.config")


def _layout_path(cfg):
    return os.path.join(cfg["CONFIG_DIR"], "ui.conf")


def _flatten_apps(data):
    """On disk, apps.config groups apps under "categories: {name: {icon,
    description, apps: [app, ...]}}" - easier to hand-edit as one block per
    category than a flat list with a repeated "category" field, and lets a
    category carry its own icon/description. The API still speaks the flat
    app form (each app tagged with "category", omitted for _uncategorized),
    so TileGrid's existing per-app grouping logic doesn't need to change -
    see _category_meta for the icon/description side of a category."""
    flat = []
    for category, cat_data in (data.get("categories") or {}).items():
        apps = (cat_data or {}).get("apps") or [] if isinstance(cat_data, dict) else (cat_data or [])
        for app in apps:
            entry = dict(app)
            if category != _UNCATEGORIZED:
                entry["category"] = category
            flat.append(entry)
    return flat


def _category_meta(data):
    """{name: {icon, description}} for every category that set either -
    icon is an MDI icon name (see frontend's constants/categories.js for
    the curated set it resolves against), not raw SVG path data."""
    meta = {}
    for category, cat_data in (data.get("categories") or {}).items():
        if category == _UNCATEGORIZED or not isinstance(cat_data, dict):
            continue
        icon = cat_data.get("icon")
        description = cat_data.get("description")
        if icon or description:
            meta[category] = {"icon": icon, "description": description}
    return meta


def _nest_apps(flat_apps, existing_categories):
    """Inverse of _flatten_apps - preserves first-seen category order and
    carries over each category's existing icon/description (there's no
    admin UI to edit those yet, so a PUT of the flat app list alone must
    not silently drop them)."""
    categories = {}
    for app in flat_apps:
        entry = dict(app)
        category = entry.pop("category", None) or _UNCATEGORIZED
        categories.setdefault(category, []).append(entry)
    result = {}
    for name, apps in categories.items():
        existing = (existing_categories or {}).get(name)
        meta = dict(existing) if isinstance(existing, dict) else {}
        meta["apps"] = apps
        result[name] = meta
    return result


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
    data = _load_yaml(_apps_path(current_app.config), {})
    apps = _flatten_apps(data)
    if "username" not in session:
        # visibility: "authenticated" must actually hide the tile, not just
        # let the frontend choose not to render it - otherwise anyone can
        # read it straight off this endpoint. Filter here, not in TileGrid.
        apps = [app for app in apps if app.get("visibility") != "authenticated"]
    # default_mode here is the GLOBAL fallback ("window"/"tab"), used only
    # when neither a visitor's own personal preference nor an app's own
    # default_mode is set - distinct from (and lower-priority than) the
    # per-app "default_mode" field inside each app entry.
    return jsonify({"default_mode": data.get("default_mode"), "categories": _category_meta(data), "apps": apps})


@config_bp.route("/api/apps", methods=["PUT"])
@require_role("admin")
def put_apps():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("apps"), list):
        return jsonify({"error": "invalid_body"}), 400

    existing = _load_yaml(_apps_path(current_app.config), {})
    existing_categories = dict(existing.get("categories") or {})

    # Optional category metadata overrides (icon/description, the Admin
    # Panel's Categories tab) - merged onto whatever already existed for
    # that category name. The apps actually IN a category always come
    # from the flat "apps" list below (_nest_apps), never from here - this
    # only ever touches icon/description.
    overrides = body.get("categories") if isinstance(body.get("categories"), dict) else {}
    for name, meta in overrides.items():
        if not isinstance(meta, dict):
            continue
        current = existing_categories.get(name)
        current = dict(current) if isinstance(current, dict) else {}
        current["icon"] = meta.get("icon")
        current["description"] = meta.get("description")
        existing_categories[name] = current

    data = {
        "default_mode": body.get("default_mode"),
        "categories": _nest_apps(body["apps"], existing_categories),
    }
    _save_yaml(_apps_path(current_app.config), data)
    return jsonify({"ok": True})


@config_bp.route("/api/layout", methods=["GET"])
def get_layout():
    data = _load_yaml(_layout_path(current_app.config), {"layout": {}})
    layout = data.get("layout", {})
    if "username" not in session:
        # Layout entries are keyed by app title, so a hidden app's title
        # (though not its url/icon) would otherwise leak through here even
        # after get_apps() filters it out - same reasoning as there.
        apps = _flatten_apps(_load_yaml(_apps_path(current_app.config), {}))
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
