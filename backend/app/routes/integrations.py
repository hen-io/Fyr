import re

from flask import Blueprint, current_app, jsonify, request, session

from .. import audit, connections
from ..auth import require_role
from ..datasources.registry import CATALOG_BY_ID

integrations_bp = Blueprint("integrations", __name__)

_URL = re.compile(r"^https?://[^\s/]+[^\s]*$")
_MAX_TEXT = 500


def _entry(integration_id, with_status=True):
    """Admin view of one integration: its form schema, the current values
    (secrets are never sent back - only whether one is set) and its status."""
    cls = CATALOG_BY_ID[integration_id]
    registry = current_app.datasources
    enabled, values = registry.settings(integration_id)
    fields = []
    for field in cls.FIELDS:
        item = {k: v for k, v in field.items()}
        if field["kind"] == "password":
            item["has_value"] = bool(values.get(field["name"]))
        else:
            item["value"] = values.get(field["name"], field.get("default", ""))
        fields.append(item)
    entry = {
        "id": cls.id,
        "label": cls.label,
        "category": cls.category,
        "icon": cls.icon,
        "description": cls.description,
        "enabled": enabled,
        "fields": fields,
        "widgets": list(cls.WIDGETS),
    }
    if with_status:
        entry["status"] = registry.check_all().get(cls.id)
    return entry


@integrations_bp.route("/api/integrations", methods=["GET"])
@require_role("admin")
def list_integrations():
    status = current_app.datasources.check_all()
    entries = []
    for integration_id in CATALOG_BY_ID:
        entry = _entry(integration_id, with_status=False)
        entry["status"] = status.get(integration_id)
        entries.append(entry)
    return jsonify(entries)


@integrations_bp.route("/api/integrations/<integration_id>", methods=["PUT"])
@require_role("admin")
def update_integration(integration_id):
    cls = CATALOG_BY_ID.get(integration_id)
    body = request.get_json(silent=True)
    if cls is None:
        return jsonify({"error": "not_found"}), 404
    if not isinstance(body, dict):
        return jsonify({"error": "invalid_body"}), 400

    data_dir = current_app.config["DATA_DIR"]
    registry = current_app.datasources
    saved = connections.load(data_dir, integration_id)
    incoming = body.get("values") if isinstance(body.get("values"), dict) else {}
    clear = set(body.get("clear") or []) if isinstance(body.get("clear"), list) else set()

    for field in cls.FIELDS:
        name = field["name"]
        kind = field["kind"]
        if name in clear and kind == "password":
            saved[name] = ""
            continue
        if name not in incoming:
            continue
        value = incoming[name]
        if kind == "password":
            if value in (None, ""):
                continue  # blank = keep the stored secret
            if not isinstance(value, str) or len(value) > _MAX_TEXT:
                return jsonify({"error": "invalid_value", "field": name}), 400
            saved[name] = value
        elif kind == "number":
            try:
                number = int(value)
            except (TypeError, ValueError):
                return jsonify({"error": "invalid_value", "field": name}), 400
            if not field.get("min", 0) <= number <= field.get("max", 65535):
                return jsonify({"error": "invalid_value", "field": name}), 400
            saved[name] = number
        elif kind == "bool":
            saved[name] = bool(value)
        else:
            if value is None:
                value = ""
            if not isinstance(value, str) or len(value) > _MAX_TEXT:
                return jsonify({"error": "invalid_value", "field": name}), 400
            value = value.strip()
            if kind == "url":
                value = value.rstrip("/")
                if value and not _URL.match(value):
                    return jsonify({"error": "invalid_url", "field": name}), 400
            saved[name] = value

    if "enabled" in body:
        saved["enabled"] = bool(body["enabled"])
    connections.save(data_dir, integration_id, saved)
    registry.reload(integration_id)
    # (which fields were sent, never what they hold)
    audit.record("integration_saved", integration=integration_id, enabled=bool(saved.get("enabled")), fields=", ".join(sorted(set(incoming) | clear)) or "-", by=session["username"])
    return jsonify(_entry(integration_id))
