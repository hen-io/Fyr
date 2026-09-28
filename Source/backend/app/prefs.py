import json
import os

# Kept separate from users.json (which only ever holds credentials) so a
# backup/restore of "who can log in" and "what they've customized" stay
# cleanly separable, and so a preferences bug can never touch a password
# hash.


def _prefs_path(config):
    return os.path.join(config["DATA_DIR"], "prefs.json")


def load_all_prefs(config):
    path = _prefs_path(config)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_all_prefs(all_prefs, config):
    path = _prefs_path(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_prefs, f, indent=2)


def get_prefs(username, config):
    return load_all_prefs(config).get(username, {})


def set_prefs(username, prefs, config):
    all_prefs = load_all_prefs(config)
    all_prefs[username] = prefs
    save_all_prefs(all_prefs, config)
