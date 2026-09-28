from flask import Blueprint, current_app, jsonify, request

from ..auth import require_role
from .config import _load_yaml, _save_yaml, _layout_path

widgets_bp = Blueprint("widgets", __name__)


def _widgets(cfg):
    data = _load_yaml(_layout_path(cfg), {"widgets": []})
    return data.get("widgets", [])


@widgets_bp.route("/api/widgets", methods=["GET"])
def list_widgets():
    return jsonify(_widgets(current_app.config))


@widgets_bp.route("/api/widgets", methods=["PUT"])
@require_role("admin")
def put_widgets():
    body = request.get_json(silent=True)
    if not isinstance(body, list):
        return jsonify({"error": "invalid_body"}), 400
    # ui.conf also holds "layout" as a sibling key - read-modify-write, same
    # reasoning as put_layout in config.py.
    path = _layout_path(current_app.config)
    existing = _load_yaml(path, {})
    existing["widgets"] = body
    _save_yaml(path, existing)
    return jsonify({"ok": True})


@widgets_bp.route("/api/widget/<widget_id>")
def get_widget_value(widget_id):
    widget = next((w for w in _widgets(current_app.config) if w.get("id") == widget_id), None)
    if not widget:
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
