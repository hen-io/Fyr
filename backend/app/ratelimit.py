import threading
import time

# In-memory sliding-window limiter for failed logins (and failed "current
# password" checks). Three windows are counted for every failure:
#
#   pair  (address, username)  a few tries      - someone guessing one account
#   addr  (address)            a few dozen      - one address trying many accounts
#   user  (username)           a few dozen      - many addresses on one account
#
# The pair limit is the one that normally trips. Because it is per address, a
# stranger failing against your username does not lock YOU out from your own
# address; the wider `user` limit only steps in against a distributed attack.
#
# In-memory is fine as long as this runs as a single worker process
# (docker/supervisord.conf starts gunicorn with --workers 1 and several
# threads); several worker processes would need a shared store.

WINDOW_SECONDS = 300  # 5 minutes
LIMITS = {"pair": 5, "addr": 20, "user": 30}
# Login is unauthenticated, so every key is attacker-chosen: without a ceiling
# a flood of unique names/addresses would grow this dict without bound.
MAX_TRACKED = 20000

_lock = threading.Lock()
_attempts = {}  # (kind, key) -> [timestamps of recent failures]


def _keys(username, address):
    username = str(username)[:128]
    address = str(address or "-")[:64]
    return (("pair", f"{address}|{username}"), ("addr", address), ("user", username))


def _recent(key, now):
    stamps = [t for t in _attempts.get(key, ()) if now - t < WINDOW_SECONDS]
    if stamps:
        _attempts[key] = stamps
    else:
        _attempts.pop(key, None)
    return stamps


def _prune(now):
    for key in [k for k, stamps in _attempts.items() if not stamps or now - stamps[-1] >= WINDOW_SECONDS]:
        del _attempts[key]


def is_locked_out(username, address=None):
    with _lock:
        now = time.time()
        return any(len(_recent(key, now)) >= LIMITS[key[0]] for key in _keys(username, address))


def record_failure(username, address=None):
    with _lock:
        now = time.time()
        if len(_attempts) >= MAX_TRACKED:
            _prune(now)
        for key in _keys(username, address):
            if len(_attempts) >= MAX_TRACKED and key not in _attempts:
                continue  # saturated with live lockouts: refuse to track more
            _attempts.setdefault(key, []).append(now)


def record_success(username, address=None):
    """A correct password clears this address's strikes against the account
    (not the address-wide or account-wide counters: one good login must not
    wipe the trail of an attack that is still going on)."""
    with _lock:
        _attempts.pop(_keys(username, address)[0], None)


def reset():
    """Forget everything (tests)."""
    with _lock:
        _attempts.clear()
