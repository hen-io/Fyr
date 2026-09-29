import os

from .fileio import load_json, save_json

# Integration settings an admin edits in the UI live in DATA_DIR (runtime
# state, not hand-edited config) and take precedence over the environment
# variables, which remain first-run defaults for Home Assistant and MQTT.
#
# connections.json:  { "<integration id>": { "enabled": bool, "<field>": value, ... }, ... }
# (An older flat layout - ha_url, ha_token, mqtt_* - is migrated on read.)

_LEGACY = {
    "home_assistant": {"ha_url": "url", "ha_token": "token"},
    "mqtt": {"mqtt_enabled": "enabled", "mqtt_host": "host", "mqtt_port": "port", "mqtt_user": "user", "mqtt_pass": "password"},
}


def _path(data_dir):
    return os.path.join(data_dir, "connections.json")


def load_all(data_dir):
    data = load_json(_path(data_dir), {})
    if not isinstance(data, dict):
        return {}
    if any(key in data for legacy in _LEGACY.values() for key in legacy):
        migrated = {k: v for k, v in data.items() if isinstance(v, dict)}
        for integration, mapping in _LEGACY.items():
            entry = dict(migrated.get(integration, {}))
            for old, new in mapping.items():
                if old in data:
                    entry.setdefault(new, data[old])
            if entry:
                migrated[integration] = entry
        return migrated
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def load(data_dir, integration_id):
    return dict(load_all(data_dir).get(integration_id, {}))


def save(data_dir, integration_id, values):
    everything = load_all(data_dir)
    everything[integration_id] = values
    save_json(_path(data_dir), everything)
    try:
        os.chmod(_path(data_dir), 0o600)  # holds tokens and passwords
    except OSError:
        pass
