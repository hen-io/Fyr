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


def _write_atomic(path, write, mode=None):
    """`mode` (e.g. 0o600) is for files that hold secrets: the file is created
    with those permissions from the start - it is never readable by other
    accounts, not even for the moment between writing and a later chmod."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666 if mode is None else mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        write(f)
        f.flush()
        try:
            os.fsync(f.fileno())  # on disk before it replaces the old file: a crash leaves the old or the new, never an empty one
        except OSError:
            pass
    if mode is not None:
        try:
            os.chmod(tmp, mode)  # a leftover tmp file from a crash keeps its old permissions otherwise
        except OSError:
            pass
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


def save_json(path, data, indent=2, mode=None):
    _write_atomic(path, lambda f: json.dump(data, f, indent=indent), mode)
