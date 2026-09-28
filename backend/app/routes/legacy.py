from flask import Blueprint, current_app, jsonify

# Reproduces the original weather_proxy.py's /api/weather and /api/home
# response shape exactly, so the frontend's existing usePolledFetch calls
# need zero changes. Only the plumbing underneath (a cached HomeAssistantSource
# instead of a single hardcoded dict) is new.

legacy_bp = Blueprint("legacy", __name__)

CONDITION_ICONS = {
    "clear-night": "🌙",
    "cloudy": "☁️",
    "exceptional": "⚠️",
    "fog": "🌫️",
    "hail": "🌨️",
    "lightning": "⛈️",
    "lightning-rainy": "⛈️",
    "partlycloudy": "⛅",
    "pouring": "🌧️",
    "rainy": "🌧️",
    "snowy": "❄️",
    "snowy-rainy": "🌨️",
    "sunny": "☀️",
    "windy": "💨",
    "windy-variant": "💨",
}


@legacy_bp.route("/api/health")
def health():
    return jsonify({"ok": True})


@legacy_bp.route("/api/weather")
def weather():
    ha = current_app.datasources.get("home_assistant")
    try:
        payload = ha.get_value(current_app.config["HA_WEATHER_ENTITY"])
    except Exception:
        return jsonify({"error": "weather_unavailable"}), 502

    condition = payload.get("state", "unknown")
    attrs = payload.get("attributes", {})
    return jsonify(
        {
            "condition": condition,
            "icon": CONDITION_ICONS.get(condition, "🌡️"),
            "temperature": attrs.get("temperature"),
            "temperature_unit": attrs.get("temperature_unit", "°C"),
            "humidity": attrs.get("humidity"),
        }
    )


@legacy_bp.route("/api/home")
def home_status():
    ha = current_app.datasources.get("home_assistant")
    mode = None
    indoor_temp = None
    try:
        mode_entity = current_app.config["HA_HOME_MODE_ENTITY"]
        if mode_entity:
            mode = ha.get_value(mode_entity).get("state")

        temp_entity = current_app.config["HA_INDOOR_TEMP_ENTITY"]
        if temp_entity:
            raw = ha.get_value(temp_entity).get("state")
            try:
                indoor_temp = round(float(raw), 1)
            except (TypeError, ValueError):
                indoor_temp = None
    except Exception:
        return jsonify({"error": "home_status_unavailable"}), 502

    return jsonify({"mode": mode, "indoor_temperature": indoor_temp})
