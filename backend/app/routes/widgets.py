import json
import math
import re
import threading
import time
import uuid

from flask import Blueprint, current_app, jsonify, request

from ..auth import current_user, require_role
from .config import _load_yaml, _save_yaml, _layout_path

widgets_bp = Blueprint("widgets", __name__)

DEFAULT_GRID = {"columns": 12, "row_height": 90}

# Widgets poll every few seconds - the HA source's default cache window
# (WEATHER_CACHE_TTL, minutes) is far too stale for a live sensor tile.
WIDGET_MAX_AGE = 8

_HA_IDENT = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_MAX_HISTORY_POINTS = 150


# --- config normalization ---------------------------------------------------


def _normalize_geometry(widget):
    """ui.conf is hand-editable - a widget missing x/y/w/h (or with a
    non-numeric value in one) shouldn't break the frontend's grid math
    (NaN in a CSS grid-column/row) or the edit-mode drag/resize math.
    Defaults to a 1x1 cell at the origin, which is always valid, just
    probably not where you want it - visibly wrong rather than silently
    broken, and an easy drag away from fixed."""

    def _num(value, fallback):
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    return {
        **widget,
        "x": max(0, _num(widget.get("x"), 0)),
        "y": max(0, _num(widget.get("y"), 0)),
        "w": max(1, _num(widget.get("w"), 1)),
        "h": max(1, _num(widget.get("h"), 1)),
    }


def _clean_grid(raw, existing):
    grid = {**DEFAULT_GRID, **(existing or {})}
    if isinstance(raw, dict):
        for key, lo, hi in (("columns", 1, 24), ("row_height", 30, 300)):
            try:
                value = int(raw.get(key, grid[key]))
            except (TypeError, ValueError):
                continue
            grid[key] = min(hi, max(lo, value))
    return grid


def _clean_widgets(raw, columns):
    """Saved widgets come from the editor UI (or a hand-edited file) - make
    sure every one has a unique string id and a type, fits inside the grid,
    and is a plain dict. Everything else (label, source, buttons, ...) is
    type-specific config the frontend's widget registry owns, so it's
    passed through untouched rather than duplicating every schema here."""
    seen = set()
    cleaned = []
    for widget in raw:
        if not isinstance(widget, dict):
            continue
        wtype = str(widget.get("type") or "").strip()[:32]
        if not wtype:
            continue
        wid = str(widget.get("id") or "").strip()[:64]
        if not wid or wid in seen:
            wid = f"{wtype}-{uuid.uuid4().hex[:8]}"
        seen.add(wid)
        widget = _normalize_geometry({**widget, "id": wid, "type": wtype})
        widget["w"] = min(widget["w"], columns)
        widget["x"] = min(widget["x"], columns - widget["w"])
        cleaned.append(widget)
    return cleaned


def _seed_footer(data, cfg):
    """The footer used to show a fixed clock plus home-mode / indoor
    temperature / weather chips. They are ordinary widgets now (editable,
    movable, removable); the first time a dashboard is read, the ones that
    were showing are created so nothing disappears. `zones_seeded` makes
    this happen exactly once - deleting them afterwards sticks."""
    if data.get("zones_seeded"):
        return False
    widgets = list(data.get("widgets") or [])
    seeded = []
    if cfg.get("HA_HOME_MODE_ENTITY"):
        seeded.append({"id": "footer-homemode", "type": "homemode", "w": 2})
    if cfg.get("HA_INDOOR_TEMP_ENTITY"):
        seeded.append({"id": "footer-indoortemp", "type": "indoortemp", "w": 1})
    seeded.append({"id": "footer-weather", "type": "weather", "w": 1})
    seeded.append({"id": "footer-clock", "type": "clock", "w": 2, "show_date": False, "font_scale": 1.6, "bare": True})
    for i, item in enumerate(seeded):
        widgets.append({"x": i, "y": 0, "h": 1, "zone": "footer", **item})
    data["widgets"] = widgets
    data["zones_seeded"] = True
    return True


def _dashboard(cfg):
    """A small grid of widgets (ui.conf: "grid" for its dimensions,
    "widgets" for what's placed in it and where) shown ABOVE the app
    launcher - the launcher itself is NOT one of these widgets (it was,
    briefly; that made its wildly variable height fight with a fixed grid
    cell, overflowing downward and visually covering whatever widget
    happened to be positioned below it). The launcher is a separate,
    naturally-sized section the frontend always renders after this grid."""
    data = _load_yaml(_layout_path(cfg), {})
    if _seed_footer(data, cfg):
        try:
            _save_yaml(_layout_path(cfg), data)
        except OSError:
            pass
    grid = _clean_grid(None, data.get("grid"))
    widgets = [_normalize_geometry(w) for w in (data.get("widgets") or []) if isinstance(w, dict)]
    return grid, widgets


def _visible(widget):
    """visibility: "authenticated" hides a widget from anonymous visitors,
    server-side - same rule (and same reasoning) as tiles in /api/apps."""
    return widget.get("visibility") != "authenticated" or current_user(current_app.config) is not None


def _find_widget(widget_id):
    _, widgets = _dashboard(current_app.config)
    widget = next((w for w in widgets if w.get("id") == widget_id), None)
    if widget is None or not _visible(widget):
        return None
    return widget


# --- reading values ---------------------------------------------------------


def _drill(raw, path):
    """MQTT payloads are often JSON ({"temperature": 21.5, "battery": 90}) -
    `path` ("temperature", "sensors.0.value") picks one field out."""
    try:
        node = json.loads(raw)
        for part in str(path).split("."):
            node = node[int(part)] if isinstance(node, list) else node[part]
        return node
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def _to_number(state):
    if isinstance(state, bool) or state is None:
        return None
    try:
        number = float(state)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _display(state):
    if state is None:
        return None
    if isinstance(state, (dict, list)):
        return json.dumps(state, ensure_ascii=False)
    return str(state)


def _read_one(source_name, key, attribute):
    source = current_app.datasources.get(source_name)
    raw = source.get_value(key, max_age=WIDGET_MAX_AGE)
    unit = None
    name = None
    if isinstance(raw, dict):  # Home Assistant: full state payload
        attrs = raw.get("attributes") or {}
        state = attrs.get(attribute) if attribute else raw.get("state")
        if not attribute:
            unit = attrs.get("unit_of_measurement")
        name = attrs.get("friendly_name")
    else:  # MQTT: raw payload string
        state = _drill(raw, attribute) if attribute else raw
    return {"state": _display(state), "number": _to_number(state), "unit": unit, "name": name}


def read_id(key, attribute):
    """How a (key, attribute) pair is named inside a widget's `values` map -
    must match readId() in the frontend's widgets/useWidgetData.js."""
    return f"{key}#{attribute}" if attribute else key


def _reads(widget):
    """Every (source, key, attribute) this widget wants live values for."""
    default_source = widget.get("source")
    reads = []
    if widget.get("key"):
        reads.append((default_source, widget["key"], widget.get("attribute")))
    for entity in widget.get("entities") or []:
        if isinstance(entity, dict):
            reads.append((entity.get("source") or default_source, entity.get("key"), entity.get("attribute")))
    if default_source == "home_assistant":
        # Button grids show whether their target is currently on.
        for button in widget.get("buttons") or []:
            if isinstance(button, dict) and button.get("entity_id"):
                reads.append(("home_assistant", button["entity_id"], None))
    return [(s, k, a) for s, k, a in reads if s and isinstance(k, str) and k]


def _collect(widget):
    values = {}
    for source_name, key, attribute in _reads(widget):
        try:
            values[read_id(key, attribute)] = _read_one(source_name, key, attribute)
        except Exception:
            values[read_id(key, attribute)] = {"error": "unavailable"}
    return {"values": values}


# --- routes -----------------------------------------------------------------


@widgets_bp.route("/api/widgets", methods=["GET"])
def list_widgets():
    grid, widgets = _dashboard(current_app.config)
    return jsonify({"grid": grid, "widgets": [w for w in widgets if _visible(w)]})


@widgets_bp.route("/api/widgets", methods=["PUT"])
@require_role("admin")
def put_widgets():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("widgets"), list):
        return jsonify({"error": "invalid_body"}), 400
    path = _layout_path(current_app.config)
    existing = _load_yaml(path, {})
    grid = _clean_grid(body.get("grid"), existing.get("grid"))
    existing["grid"] = grid
    existing["widgets"] = _clean_widgets(body["widgets"], grid["columns"])
    # An explicit save is the admin's statement of what the dashboard holds:
    # never seed the default footer widgets on top of it afterwards.
    existing["zones_seeded"] = True
    _save_yaml(path, existing)
    return jsonify({"ok": True})


@widgets_bp.route("/api/widgets/reset", methods=["POST"])
@require_role("admin")
def reset_widgets():
    """Back to an empty dashboard with the default grid (widgets are only
    dashboard content - apps, users and settings are untouched)."""
    path = _layout_path(current_app.config)
    existing = _load_yaml(path, {})
    existing["grid"] = dict(DEFAULT_GRID)
    existing["widgets"] = []
    existing["zones_seeded"] = True
    _save_yaml(path, existing)
    return jsonify({"ok": True})


@widgets_bp.route("/api/widget/<widget_id>")
def get_widget_data(widget_id):
    widget = _find_widget(widget_id)
    if widget is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(_collect(widget))


@widgets_bp.route("/api/sources")
@require_role("admin")
def list_sources():
    return jsonify(current_app.datasources.describe())


@widgets_bp.route("/api/sources/<name>/keys")
@require_role("admin")
def list_source_keys(name):
    try:
        keys = current_app.datasources.get(name).list_keys()
    except Exception:
        keys = []
    return jsonify({"keys": keys})


# --- integration widgets (Sonarr / Radarr / qBittorrent ...) -----------------

INTEGRATION_WIDGETS = {"arr_calendar", "arr_queue", "qbit_torrents", "backrest_plans", "backrest_operations"}
_INTEGRATION_TTL = 5
_integration_cache = {}
_integration_lock = threading.Lock()


def _integration_source(widget):
    """The live integration serving this widget, or (None, error response)."""
    if widget.get("type") not in INTEGRATION_WIDGETS:
        return None, (jsonify({"error": "not_found"}), 404)
    try:
        source = current_app.datasources.get(widget.get("source"))
    except KeyError:
        return None, (jsonify({"error": "integration_disabled"}), 404)
    if widget["type"] not in source.WIDGETS:
        return None, (jsonify({"error": "not_found"}), 404)
    return source, None


def _integration_payload(source, widget, cache_key=None):
    now = time.time()
    if cache_key:
        with _integration_lock:
            hit = _integration_cache.get(cache_key)
        if hit and now - hit[0] < _INTEGRATION_TTL:
            return hit[1]
    data = source.widget_data(widget["type"], widget)
    if cache_key:
        with _integration_lock:
            if len(_integration_cache) > 256:
                _integration_cache.clear()
            _integration_cache[cache_key] = (now, data)
    return data


@widgets_bp.route("/api/widget/<widget_id>/integration")
def get_widget_integration(widget_id):
    widget = _find_widget(widget_id)
    if widget is None:
        return jsonify({"error": "not_found"}), 404
    source, error = _integration_source(widget)
    if error:
        return error
    try:
        return jsonify(_integration_payload(source, widget, cache_key=(widget_id, json.dumps(widget, sort_keys=True, default=str))))
    except Exception:
        return jsonify({"error": "unavailable"}), 502


@widgets_bp.route("/api/widget/<widget_id>/integration-action", methods=["POST"])
def run_widget_integration_action(widget_id):
    widget = _find_widget(widget_id)
    if widget is None:
        return jsonify({"error": "not_found"}), 404
    source, error = _integration_source(widget)
    if error:
        return error
    # Same rule as button widgets: acting on the real world needs a login.
    if not widget.get("allow_anonymous") and current_user(current_app.config) is None:
        return jsonify({"error": "not_authenticated"}), 401
    action = (request.get_json(silent=True) or {}).get("action")
    if action not in source.ACTIONS:
        return jsonify({"error": "invalid_action"}), 400
    try:
        source.run_widget_action(action, widget)
    except Exception:
        return jsonify({"error": "action_failed"}), 502
    return jsonify({"ok": True})


@widgets_bp.route("/api/integration-preview", methods=["POST"])
@require_role("admin")
def preview_integration_widget():
    """The editor's live preview of an unsaved integration widget."""
    widget = request.get_json(silent=True)
    if not isinstance(widget, dict):
        return jsonify({"error": "invalid_body"}), 400
    source, error = _integration_source(widget)
    if error:
        return error
    try:
        return jsonify(_integration_payload(source, widget))
    except Exception:
        return jsonify({"error": "unavailable"}), 502


@widgets_bp.route("/api/widget-data", methods=["POST"])
@require_role("admin")
def preview_widget_data():
    """Live values for a widget config that isn't saved yet - the editor's
    preview. Read-only; never runs actions."""
    widget = request.get_json(silent=True)
    if not isinstance(widget, dict):
        return jsonify({"error": "invalid_body"}), 400
    return jsonify(_collect(widget))


_WEATHER_ID = re.compile(r"^weather\.[a-z0-9_]+$")


@widgets_bp.route("/api/widget/<widget_id>/weather")
def get_widget_weather(widget_id):
    """Current conditions for a weather widget: the weather.* entity chosen
    in the widget (else HA_WEATHER_ENTITY), plus a short daily forecast when
    the entity still exposes one as an attribute."""
    from .legacy import CONDITION_ICONS

    widget = _find_widget(widget_id)
    if widget is None or widget.get("type") != "weather":
        return jsonify({"error": "not_found"}), 404
    entity = widget.get("key") or current_app.config["HA_WEATHER_ENTITY"]
    if not isinstance(entity, str) or not _WEATHER_ID.match(entity):
        return jsonify({"error": "invalid_entity"}), 400
    try:
        payload = current_app.datasources.get("home_assistant").get_value(entity, max_age=WIDGET_MAX_AGE * 4)
    except Exception:
        return jsonify({"error": "weather_unavailable"}), 502

    attrs = payload.get("attributes") or {}
    condition = payload.get("state", "unknown")
    forecast = []
    for day in (attrs.get("forecast") or [])[:5]:
        if isinstance(day, dict):
            forecast.append(
                {
                    "datetime": day.get("datetime"),
                    "condition": day.get("condition"),
                    "icon": CONDITION_ICONS.get(day.get("condition"), "🌡️"),
                    "temperature": day.get("temperature"),
                    "templow": day.get("templow"),
                }
            )
    return jsonify(
        {
            "condition": condition,
            "icon": CONDITION_ICONS.get(condition, "🌡️"),
            "temperature": attrs.get("temperature"),
            "temperature_unit": attrs.get("temperature_unit", "°C"),
            "apparent_temperature": attrs.get("apparent_temperature"),
            "humidity": attrs.get("humidity"),
            "wind_speed": attrs.get("wind_speed"),
            "wind_speed_unit": attrs.get("wind_speed_unit"),
            "pressure": attrs.get("pressure"),
            "pressure_unit": attrs.get("pressure_unit"),
            "forecast": forecast,
        }
    )


@widgets_bp.route("/api/widget/<widget_id>/history")
def get_widget_history(widget_id):
    widget = _find_widget(widget_id)
    if widget is None or not widget.get("key") or not widget.get("source"):
        return jsonify({"error": "not_found"}), 404
    try:
        hours = min(168.0, max(0.05, float(request.args.get("hours", widget.get("hours") or 24))))
    except ValueError:
        hours = 24.0

    try:
        source = current_app.datasources.get(widget["source"])
        raw_points = source.get_history(widget["key"], hours)
    except Exception:
        return jsonify({"points": [], "error": "unavailable"})

    attribute = widget.get("attribute")
    points = []
    for ts, raw in raw_points:
        state = _drill(raw, attribute) if attribute and not isinstance(raw, dict) else raw
        number = _to_number(state)
        if number is not None:
            points.append([int(ts), number])
    if len(points) > _MAX_HISTORY_POINTS:
        step = len(points) / _MAX_HISTORY_POINTS
        points = [points[int(i * step)] for i in range(_MAX_HISTORY_POINTS)]
    return jsonify({"points": points})


def _button_spec(source_name, button):
    """Turn one configured button into the dict a source's run_action
    expects. Everything comes from the saved widget config, never from the
    request - the client only ever says WHICH button (by index), so nothing
    a caller sends can name an arbitrary service or topic."""
    if source_name == "home_assistant":
        service = str(button.get("service") or "")
        if not _HA_IDENT.match(service):
            raise ValueError("invalid service")
        domain, name = service.split(".", 1)
        data = button.get("data") or {}
        if isinstance(data, str):
            data = json.loads(data) if data.strip() else {}
        if not isinstance(data, dict):
            raise ValueError("data must be an object")
        entity_id = button.get("entity_id")
        if entity_id:
            if not _HA_IDENT.match(str(entity_id)):
                raise ValueError("invalid entity_id")
            data = {"entity_id": entity_id, **data}
        return {"domain": domain, "service": name, "data": data}
    if source_name == "mqtt":
        topic = str(button.get("topic") or "")
        if not topic or "#" in topic or "+" in topic:
            raise ValueError("invalid topic")
        return {"topic": topic, "payload": str(button.get("payload") or ""), "retain": bool(button.get("retain"))}
    raise ValueError("unsupported source")


@widgets_bp.route("/api/widget/<widget_id>/action", methods=["POST"])
def run_widget_action(widget_id):
    widget = _find_widget(widget_id)
    if widget is None or widget.get("type") != "buttons":
        return jsonify({"error": "not_found"}), 404
    # Pressing a button changes the real world (lights, locks, ...) - by
    # default that needs a login, even if the widget itself is visible to
    # everyone. A widget can opt out explicitly ("allow_anonymous").
    if not widget.get("allow_anonymous") and current_user(current_app.config) is None:
        return jsonify({"error": "not_authenticated"}), 401

    body = request.get_json(silent=True) or {}
    buttons = widget.get("buttons") or []
    index = body.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(buttons):
        return jsonify({"error": "invalid_button"}), 400

    try:
        spec = _button_spec(widget.get("source"), buttons[index])
    except (ValueError, TypeError):
        return jsonify({"error": "invalid_button_config"}), 400

    try:
        current_app.datasources.get(widget["source"]).run_action(spec)
    except Exception:
        return jsonify({"error": "action_failed"}), 502
    return jsonify({"ok": True})
