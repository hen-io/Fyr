import copy
import json
import os
import threading

import yaml

# Requests are served by several threads, so files that are rewritten
# (users, prefs, ui.conf, apps.config) are replaced atomically - a reader
# never sees a half-written file - and parsed results are cached by
# modification time, so polling widgets don't re-parse YAML every few seconds.
_lock = threading.Lock()
_cache = {}


def _signature(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _cached(path, parse, default):
    sig = _signature(path)
    if sig is None:
        return copy.deepcopy(default)
    with _lock:
        hit = _cache.get(path)
    if hit and hit[0] == sig:
        return copy.deepcopy(hit[1])
    with open(path, "r", encoding="utf-8") as f:
        value = parse(f)
    with _lock:
        _cache[path] = (sig, value)
    return copy.deepcopy(value)


def _write_atomic(path, write):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        write(f)
    os.replace(tmp, path)
    with _lock:
        _cache.pop(path, None)


def load_yaml(path, default):
    value = _cached(path, yaml.safe_load, None)
    return value if value else default


def save_yaml(path, data):
    _write_atomic(path, lambda f: yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True))


def load_json(path, default):
    value = _cached(path, json.load, None)
    return default if value is None else value


def save_json(path, data, indent=2):
    _write_atomic(path, lambda f: json.dump(data, f, indent=indent))
