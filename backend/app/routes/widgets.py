from flask import Blueprint, current_app, jsonify, request

from ..auth import require_role
from .config import _load_yaml, _save_yaml, _layout_path

widgets_bp = Blueprint("widgets", __name__)

DEFAULT_GRID = {"columns": 12, "row_height": 90}
DEFAULT_LAUNCHER_WIDGET = {"id": "launcher", "type": "launcher", "x": 0, "y": 0, "w": 12, "h": 6}


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
        "x": _num(widget.get("x"), 0),
        "y": _num(widget.get("y"), 0),
        "w": max(1, _num(widget.get("w"), 1)),
        "h": max(1, _num(widget.get("h"), 1)),
    }


def _dashboard(cfg):
    """The dashboard is one grid (ui.conf: "grid" for its dimensions,
    "widgets" for what's placed in it and where) - the app-launcher is
    itself just a widget (type: "launcher") in that same list, not a
    separate fixed section. A "launcher" widget must always exist
    somewhere: rather than a migration step, an install with none
    configured yet (or upgrading from before this existed) just gets one
    synthesized at the top - unsaved until something else is - so the
    dashboard is never accidentally launcher-less."""
    data = _load_yaml(_layout_path(cfg), {})
    grid = {**DEFAULT_GRID, **(data.get("grid") or {})}
    widgets = [_normalize_geometry(w) for w in (data.get("widgets") or [])]
    if not any(w.get("type") == "launcher" for w in widgets):
        widgets = [DEFAULT_LAUNCHER_WIDGET, *widgets]
    return grid, widgets


@widgets_bp.route("/api/widgets", methods=["GET"])
def list_widgets():
    grid, widgets = _dashboard(current_app.config)
    return jsonify({"grid": grid, "widgets": widgets})


@widgets_bp.route("/api/widgets", methods=["PUT"])
@require_role("admin")
def put_widgets():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("widgets"), list):
        return jsonify({"error": "invalid_body"}), 400
    path = _layout_path(current_app.config)
    existing = _load_yaml(path, {})
    existing["widgets"] = body["widgets"]
    if isinstance(body.get("grid"), dict):
        existing["grid"] = body["grid"]
    _save_yaml(path, existing)
    return jsonify({"ok": True})


@widgets_bp.route("/api/widget/<widget_id>")
def get_widget_value(widget_id):
    _, widgets = _dashboard(current_app.config)
    widget = next((w for w in widgets if w.get("id") == widget_id), None)
    # Only "gauge" widgets have a live polled value - launcher/calendar/etc.
    # fetch their own data through their own endpoints.
    if not widget or widget.get("type") != "gauge":
        return jsonify({"error": "not_found"}), 404

    try:
        source = current_app.datasources.get(widget["source"])
        raw = source.get_value(widget["key"])
        # HomeAssistantSource returns the full state payload ({state, attributes,
        # ...}); MqttSource returns the raw payload string directly.
        state = raw.get("state") if isinstance(raw, dict) else raw
        value = float(state)
    except Exception:
        return jsonify({"value": None, "error": "unavailable"}), 502

    return jsonify({"value": value})
