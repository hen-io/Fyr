import re

from flask import Blueprint, current_app, jsonify, request

from .. import connections
from ..auth import require_role

connections_bp = Blueprint("connections", __name__)

_URL = re.compile(r"^https?://[^\s/]+[^\s]*$")
_HOST = re.compile(r"^[A-Za-z0-9._-]{1,253}$")


def _view():
    eff = connections.effective(current_app.config, current_app.config["DATA_DIR"])
    return {
        "ha_url": eff.HA_URL,
        "ha_token_set": bool(eff.HA_TOKEN),
        "mqtt_enabled": eff.MQTT_ENABLED,
        "mqtt_host": eff.MQTT_HOST,
        "mqtt_port": eff.MQTT_PORT,
        "mqtt_user": eff.MQTT_USER or "",
        "mqtt_pass_set": bool(eff.MQTT_PASS),
    }


@connections_bp.route("/api/connections", methods=["GET"])
@require_role("admin")
def get_connections():
    return jsonify({**_view(), "status": current_app.datasources.check_all()})


@connections_bp.route("/api/connections", methods=["PUT"])
@require_role("admin")
def put_connections():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "invalid_body"}), 400

    data_dir = current_app.config["DATA_DIR"]
    values = connections.load(data_dir)

    url = str(body.get("ha_url", values.get("ha_url", "")) or "").strip().rstrip("/")
    if url and not _URL.match(url):
        return jsonify({"error": "invalid_ha_url"}), 400
    host = str(body.get("mqtt_host", values.get("mqtt_host", "")) or "").strip()
    if host and not _HOST.match(host):
        return jsonify({"error": "invalid_mqtt_host"}), 400
    try:
        port = int(body.get("mqtt_port", values.get("mqtt_port", 1883)) or 1883)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_mqtt_port"}), 400
    if not 1 <= port <= 65535:
        return jsonify({"error": "invalid_mqtt_port"}), 400

    values.update(
        ha_url=url,
        mqtt_enabled=bool(body.get("mqtt_enabled", values.get("mqtt_enabled", False))),
        mqtt_host=host,
        mqtt_port=port,
        mqtt_user=str(body.get("mqtt_user", values.get("mqtt_user", "")) or "").strip(),
    )
    # A secret is only replaced when a new value is sent (the UI never gets
    # the old one back); an explicit clear flag removes it.
    for field in connections.SECRETS:
        if body.get(f"clear_{field}"):
            values[field] = ""
        elif body.get(field):
            values[field] = str(body[field])

    connections.save(data_dir, values)
    current_app.datasources.reload(connections.effective(current_app.config, data_dir))
    return jsonify({**_view(), "status": current_app.datasources.check_all()})
