import os
import re

from flask import Blueprint, current_app, jsonify, request, send_from_directory, session

from .. import audit, tileurls
from ..auth import current_user, require_role
from ..fileio import load_yaml, save_yaml
from ..imageio import ImageRejected, verify_icon

config_bp = Blueprint("config", __name__)


_UNCATEGORIZED = "_uncategorized"
_VIEWERS = ("anonymous", "visitor", "admin")


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
            if not isinstance(app, dict):
                continue  # hand-edited file: skip junk rather than 500 for everyone
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
        hidden_for = [v for v in (cat_data.get("hidden_for") or []) if v in _VIEWERS]
        if icon or description or hidden_for or not cat_data.get("apps"):
            meta[category] = {"icon": icon, "description": description, "hidden_for": hidden_for}
    return meta


def _nest_apps(flat_apps, existing_categories):
    """Inverse of _flatten_apps - preserves first-seen category order and
    carries over each category's existing icon/description (there's no
    admin UI to edit those yet, so a PUT of the flat app list alone must
    not silently drop them)."""
    categories = {}
    for app in flat_apps:
        entry = {k: v for k, v in dict(app).items() if v is not None}
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
    return load_yaml(path, default)


def _save_yaml(path, data):
    save_yaml(path, data)


_ICON_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}\.(png|jpe?g|webp|gif|ico|svg)$")
_STROKE_COLORS = ("ink", "accent", "white", "black", "auto")
_APP_KEYS = ("title", "url", "internalUrl", "icon", "category", "visibility", "default_mode", "keywords")


def _clean_apps(raw):
    """Apps arrive from the admin UI: keep only known keys, bound their
    lengths, require http(s) URLs and a plain icon file name, and reject
    duplicate titles (the layout is keyed by title). Returns (apps, error)."""
    cleaned, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        app = {}
        for key in _APP_KEYS:
            value = item.get(key)
            if value is None or value == "":
                continue
            if not isinstance(value, str) or len(value) > 500:
                return None, "invalid_app"
            app[key] = value.strip()
        stroke = item.get("iconStroke")
        if stroke not in (None, ""):
            if isinstance(stroke, bool) or not isinstance(stroke, (int, float)) or not 0 <= stroke <= 6:
                return None, "invalid_app"
            app["iconStroke"] = stroke
        color = item.get("iconStrokeColor")
        if color not in (None, ""):
            if color not in _STROKE_COLORS:
                return None, "invalid_app"
            app["iconStrokeColor"] = color
        for key in ("badgeColor", "badgeColor2"):
            value = item.get(key)
            if value not in (None, ""):
                if not tileurls.hex_colour(value):
                    return None, "invalid_app"
                app[key] = value.lower()
        title = app.get("title", "")
        if not title or len(title) > 80:
            return None, "invalid_title"
        if title in seen:
            return None, "duplicate_title"
        seen.add(title)
        for key in ("url", "internalUrl"):
            if key in app and not re.match(r"^https?://[^\s/]+", app[key]):
                return None, "invalid_url"
        if "url" not in app:
            return None, "invalid_url"
        if "icon" in app and not _ICON_NAME.match(app["icon"]):
            return None, "invalid_icon"
        if app.get("default_mode") not in (None, "window", "tab"):
            return None, "invalid_mode"
        if app.get("visibility") not in (None, "authenticated"):
            return None, "invalid_visibility"
        if "category" in app and (len(app["category"]) > 60 or app["category"] == _UNCATEGORIZED):
            return None, "invalid_category"
        cleaned.append(app)
    return cleaned, None


def _viewer():
    """Which audience the current request belongs to: not logged in, a
    logged-in visitor, or an admin."""
    user = current_user(current_app.config)
    if not user:
        return "anonymous"
    return "admin" if user.get("role") == "admin" else "visitor"


def _hidden_categories(data, viewer):
    """Categories whose `hidden_for` list names this viewer class."""
    hidden = set()
    for name, cat in (data.get("categories") or {}).items():
        if isinstance(cat, dict) and viewer in (cat.get("hidden_for") or []):
            hidden.add(name)
    return hidden


@config_bp.route("/api/apps", methods=["GET"])
def get_apps():
    data = _load_yaml(_apps_path(current_app.config), {})
    viewer = _viewer()
    # ?all=1 is the admin editor's unfiltered view (an admin can hide a
    # category from admins too, and must still be able to edit it).
    show_all = request.args.get("all") == "1" and viewer == "admin"
    hidden = set() if show_all else _hidden_categories(data, viewer)
    apps = [a for a in _flatten_apps(data) if a.get("category") not in hidden]
    if viewer == "anonymous":
        # visibility: "authenticated" must actually hide the tile, not just
        # let the frontend choose not to render it - otherwise anyone can
        # read it straight off this endpoint. Filter here, not in TileGrid.
        apps = [app for app in apps if app.get("visibility") != "authenticated"]
    # Server-drawn tile effects: signed picture URLs, worked out from the
    # admin's settings (see tileurls.py), for the apps that get them.
    chosen = tileurls.settings(_load_yaml(_layout_path(current_app.config), {}).get("defaults"))
    icons_dir = os.path.join(current_app.config["CONFIG_DIR"], "icons")
    for app in apps:
        if isinstance(app.get("icon"), str) and _ICON_NAME.match(app["icon"]):
            fx = tileurls.urls_for(app, chosen, icons_dir, current_app.config["SECRET_KEY"])
            if fx:
                app["fx"] = fx
    meta ={k: v for k, v in _category_meta(data).items() if k not in hidden}
    if not show_all:
        for entry in meta.values():
            entry.pop("hidden_for", None)
    # default_mode here is the GLOBAL fallback ("window"/"tab"), used only
    # when neither a visitor's own personal preference nor an app's own
    # default_mode is set - distinct from (and lower-priority than) the
    # per-app "default_mode" field inside each app entry.
    return jsonify({"default_mode": data.get("default_mode"), "categories": meta, "apps": apps})


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
        # Only touched when the request says something about it - a save
        # from a tab that doesn't know about audiences must not erase it.
        if "hidden_for" in meta:
            hidden_for = [v for v in (meta.get("hidden_for") or []) if v in _VIEWERS] if isinstance(meta.get("hidden_for"), list) else []
            if hidden_for:
                current["hidden_for"] = hidden_for
            else:
                current.pop("hidden_for", None)
        existing_categories[name] = current

    apps, error = _clean_apps(body["apps"])
    if error:
        return jsonify({"error": error}), 400
    default_mode = body.get("default_mode")
    if default_mode not in (None, "window", "tab"):
        return jsonify({"error": "invalid_mode"}), 400

    categories = _nest_apps(apps, existing_categories)
    # Categories named in the request but holding no apps are kept (that is
    # how an empty category gets created); ones not named and with no apps
    # simply disappear (that is how one is deleted).
    for name in overrides:
        if name != _UNCATEGORIZED and name not in categories:
            meta = overrides[name] if isinstance(overrides[name], dict) else {}
            hidden_for = [v for v in (meta.get("hidden_for") or []) if v in _VIEWERS] if isinstance(meta.get("hidden_for"), list) else []
            categories[name] = {"icon": meta.get("icon"), "description": meta.get("description"), "apps": []}
            if hidden_for:
                categories[name]["hidden_for"] = hidden_for
    # The admin editor sends its categories in display order; honour it when
    # it names every category (first-seen order would shuffle empty ones).
    named = [n for n in overrides if n in categories and n != _UNCATEGORIZED]
    if named and all(n in named for n in categories if n != _UNCATEGORIZED):
        ordered = {n: categories[n] for n in named}
        ordered.update({n: v for n, v in categories.items() if n not in ordered})
        categories = ordered
    data = {"default_mode": default_mode, "categories": categories}
    _save_yaml(_apps_path(current_app.config), data)
    return jsonify({"ok": True})


@config_bp.route("/api/layout", methods=["GET"])
def get_layout():
    data = _load_yaml(_layout_path(current_app.config), {"layout": {}})
    layout = data.get("layout", {})
    # Layout entries are keyed by app title, so a hidden app's title
    # (though not its url/icon) would otherwise leak through here even
    # after get_apps() filters it out - same reasoning as there.
    apps_data = _load_yaml(_apps_path(current_app.config), {})
    viewer = _viewer()
    hidden = _hidden_categories(apps_data, viewer)
    hidden_titles = set()
    for app in _flatten_apps(apps_data):
        if app.get("category") in hidden or (viewer == "anonymous" and app.get("visibility") == "authenticated"):
            hidden_titles.add(app["title"])
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
    response = send_from_directory(icons_dir, filename, max_age=300)
    # Icons are images; if one is ever opened as a page it must not run
    # anything (an SVG could carry script).
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'"
    return response


def _icons_dir():
    return os.path.join(current_app.config["CONFIG_DIR"], "icons")


def _icon_users(data):
    """{icon file name: [titles of the apps showing it]}"""
    users = {}
    for app in _flatten_apps(data):
        if isinstance(app.get("icon"), str):
            users.setdefault(app["icon"], []).append(app.get("title") or "")
    return users


def _set_app_icons(data, old, new):
    """Point every app showing `old` at `new` (None: at no icon). Returns how many."""
    changed = 0
    for cat_data in (data.get("categories") or {}).values():
        apps = cat_data.get("apps") if isinstance(cat_data, dict) else cat_data
        for app in apps or []:
            if isinstance(app, dict) and app.get("icon") == old:
                if new:
                    app["icon"] = new
                else:
                    app.pop("icon", None)
                changed += 1
    return changed


@config_bp.route("/api/icons", methods=["GET"])
@require_role("admin")
def list_icons():
    """The file names; with ?details=1 also each file's size, when it was
    last changed and which apps show it (the admin panel's logo tab)."""
    try:
        names = sorted((n for n in os.listdir(_icons_dir()) if _ICON_NAME.match(n)), key=str.lower)
    except OSError:
        names = []
    if not request.args.get("details"):
        return jsonify(names)
    users = _icon_users(_load_yaml(_apps_path(current_app.config), {}))
    icons = []
    for name in names:
        try:
            stat = os.stat(os.path.join(_icons_dir(), name))
        except OSError:
            continue
        icons.append({"name": name, "size": stat.st_size, "modified": int(stat.st_mtime), "used_by": users.get(name, [])})
    return jsonify({"icons": icons})


@config_bp.route("/api/icons/<name>", methods=["PATCH"])
@require_role("admin")
def rename_icon(name):
    """Rename a logo file. The apps showing it follow along."""
    body = request.get_json(silent=True)
    new = body.get("name") if isinstance(body, dict) else None
    if not _ICON_NAME.match(name) or not isinstance(new, str) or not _ICON_NAME.match(new):
        return jsonify({"error": "invalid_name"}), 400
    # The extension says what kind of image the file is; it stays.
    if name.rsplit(".", 1)[1].lower() != new.rsplit(".", 1)[1].lower():
        return jsonify({"error": "extension_changed"}), 400
    source, target = os.path.join(_icons_dir(), name), os.path.join(_icons_dir(), new)
    if not os.path.isfile(source):
        return jsonify({"error": "not_found"}), 404
    if new == name:
        return jsonify({"name": new, "apps": 0})
    # (A change of capitals only is the same file on a case-insensitive disk.)
    if os.path.exists(target) and not (new.lower() == name.lower() and os.path.samefile(source, target)):
        return jsonify({"error": "exists"}), 409
    os.rename(source, target)
    data = _load_yaml(_apps_path(current_app.config), {})
    changed = _set_app_icons(data, name, new)
    if changed:
        _save_yaml(_apps_path(current_app.config), data)
    audit.record("icon_renamed", icon=name, to=new, apps=changed, by=session["username"])
    return jsonify({"name": new, "apps": changed})


@config_bp.route("/api/icons/<name>", methods=["DELETE"])
@require_role("admin")
def delete_icon(name):
    """Delete a logo file. One that apps still show is only deleted with
    ?force=1, and those apps are then left without a logo."""
    if not _ICON_NAME.match(name):
        return jsonify({"error": "invalid_name"}), 400
    path = os.path.join(_icons_dir(), name)
    if not os.path.isfile(path):
        return jsonify({"error": "not_found"}), 404
    data = _load_yaml(_apps_path(current_app.config), {})
    used_by = _icon_users(data).get(name, [])
    if used_by and not request.args.get("force"):
        return jsonify({"error": "in_use", "apps": used_by}), 409
    os.remove(path)
    if used_by:
        _set_app_icons(data, name, None)
        _save_yaml(_apps_path(current_app.config), data)
    audit.record("icon_deleted", icon=name, apps=len(used_by), by=session["username"])
    return jsonify({"ok": True, "apps": len(used_by)})


@config_bp.route("/api/icons", methods=["POST"])
@require_role("admin")
def upload_icon():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "no_file"}), 400
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(file.filename)).lstrip(".")
    # SVG is allowed for icons already on disk, but not uploaded: it can carry script.
    if not _ICON_NAME.match(name) or name.lower().endswith(".svg"):
        return jsonify({"error": "unsupported_type"}), 400
    data = file.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        return jsonify({"error": "file_too_large"}), 400
    # The bytes must really decode as the image type the extension claims.
    try:
        verify_icon(data, name.rsplit(".", 1)[1])
    except ImageRejected:
        return jsonify({"error": "not_an_image"}), 400
    icons_dir = _icons_dir()
    os.makedirs(icons_dir, exist_ok=True)
    # The logo tab asks before replacing a file (it sends replace=1 once the
    # admin has agreed); without the field an upload overwrites, as before.
    if request.form.get("replace") == "0" and os.path.exists(os.path.join(icons_dir, name)):
        return jsonify({"error": "exists", "name": name}), 409
    with open(os.path.join(icons_dir, name), "wb") as f:
        f.write(data)
    return jsonify({"name": name}), 201
