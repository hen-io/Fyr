import os

from .fileio import load_json, save_json

# Kept separate from users.json (which only ever holds credentials) so a
# backup/restore of "who can log in" and "what they've customized" stay
# cleanly separable, and so a preferences bug can never touch a password
# hash.


def _prefs_path(config):
    return os.path.join(config["DATA_DIR"], "prefs.json")


def load_all_prefs(config):
    return load_json(_prefs_path(config), {})


def save_all_prefs(all_prefs, config):
    save_json(_prefs_path(config), all_prefs)


def get_prefs(username, config):
    return load_all_prefs(config).get(username, {})


def set_prefs(username, prefs, config):
    all_prefs = load_all_prefs(config)
    all_prefs[username] = prefs
    save_all_prefs(all_prefs, config)


def clear_prefs(config, username=None):
    """Drop one user's saved prefs, or everyone's when username is None."""
    if username is None:
        save_all_prefs({}, config)
        return
    all_prefs = load_all_prefs(config)
    if all_prefs.pop(username, None) is not None:
        save_all_prefs(all_prefs, config)


# --- reset epoch ------------------------------------------------------------
# Personal settings live in each browser's localStorage (and, for logged-in
# users, here). Wiping the server-side copy alone can't reach a browser that
# already has its own overrides cached - so "reset everyone" also bumps this
# epoch, and every browser compares the epoch it last saw against the
# current one on load and drops its local overrides when they differ.


def _epoch_path(config):
    return os.path.join(config["DATA_DIR"], "prefs_epoch")


def get_epoch(config):
    try:
        with open(_epoch_path(config), "r", encoding="utf-8") as f:
            return f.read().strip() or "0"
    except OSError:
        return "0"


def bump_epoch(config):
    import time

    epoch = str(int(time.time() * 1000))
    os.makedirs(os.path.dirname(_epoch_path(config)), exist_ok=True)
    with open(_epoch_path(config), "w", encoding="utf-8") as f:
        f.write(epoch)
    return epoch
