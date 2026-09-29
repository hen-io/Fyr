import json
import os
from types import SimpleNamespace

# Connection settings an admin edits in the UI live in DATA_DIR (runtime
# state, not hand-edited config) and take precedence over the environment
# variables, which remain the first-run defaults.
FIELDS = ("ha_url", "ha_token", "mqtt_enabled", "mqtt_host", "mqtt_port", "mqtt_user", "mqtt_pass")
SECRETS = ("ha_token", "mqtt_pass")


def _path(data_dir):
    return os.path.join(data_dir, "connections.json")


def load(data_dir):
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            data = json.load(f)
        return {k: data[k] for k in FIELDS if k in data} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data_dir, values):
    os.makedirs(data_dir, exist_ok=True)
    tmp = _path(data_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(values, f)
    os.replace(tmp, _path(data_dir))
    try:
        os.chmod(_path(data_dir), 0o600)
    except OSError:
        pass


def effective(config, data_dir):
    """Env defaults overlaid with saved admin settings, as the attribute
    object DataSourceRegistry expects."""
    saved = load(data_dir)

    def env(name):
        return config[name] if isinstance(config, dict) or hasattr(config, "keys") else getattr(config, name)

    port = saved.get("mqtt_port", env("MQTT_PORT"))
    try:
        port = int(port) or 1883
    except (TypeError, ValueError):
        port = 1883
    return SimpleNamespace(
        HA_URL=str(saved.get("ha_url", env("HA_URL")) or "").rstrip("/"),
        HA_TOKEN=saved.get("ha_token", env("HA_TOKEN")) or "",
        WEATHER_CACHE_TTL=env("WEATHER_CACHE_TTL"),
        MQTT_ENABLED=bool(saved.get("mqtt_enabled", env("MQTT_ENABLED"))),
        MQTT_HOST=saved.get("mqtt_host", env("MQTT_HOST")) or "",
        MQTT_PORT=port,
        MQTT_USER=saved.get("mqtt_user", env("MQTT_USER")) or None,
        MQTT_PASS=saved.get("mqtt_pass", env("MQTT_PASS")) or None,
    )
