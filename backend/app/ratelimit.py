import threading
import time

# A simple in-memory sliding-window limiter for login attempts. Keyed by
# username (not IP) so one account can't be hammered from many addresses,
# and one address failing many different usernames doesn't lock out a
# legitimate user on a shared connection. In-memory is fine as long as this
# runs as a single worker process (see the Dockerfile's gunicorn command,
# no -w flag - one worker); scaling to multiple workers would need a shared
# store (e.g. Redis) for this to stay effective across all of them.

_lock = threading.Lock()
_attempts = {}  # username -> [timestamps of recent failed attempts]

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 minutes


def is_locked_out(username):
    with _lock:
        now = time.time()
        recent = [t for t in _attempts.get(username, []) if now - t < WINDOW_SECONDS]
        _attempts[username] = recent
        return len(recent) >= MAX_ATTEMPTS


def record_failure(username):
    with _lock:
        _attempts.setdefault(username, []).append(time.time())


def record_success(username):
    with _lock:
        _attempts.pop(username, None)
