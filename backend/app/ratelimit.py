import threading
import time

# A simple in-memory sliding-window limiter for login attempts. Keyed by
# username (not IP) so one account can't be hammered from many addresses,
# and one address failing many different usernames doesn't lock out a
# legitimate user on a shared connection. In-memory is fine as long as this
# runs as a single worker process (docker/supervisord.conf starts gunicorn
# with --workers 1 and several threads); scaling to multiple worker
# processes would need a shared store (e.g. Redis) for this to stay
# effective across all of them.

_lock = threading.Lock()
_attempts = {}  # username -> [timestamps of recent failed attempts]

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 minutes
# Login is unauthenticated, so the username is attacker-chosen: without a
# ceiling a flood of unique names would grow this dict without bound.
MAX_TRACKED = 5000


def _prune(now):
    for name in [n for n, stamps in _attempts.items() if not stamps or now - stamps[-1] >= WINDOW_SECONDS]:
        del _attempts[name]


def is_locked_out(username):
    with _lock:
        now = time.time()
        recent = [t for t in _attempts.get(username, []) if now - t < WINDOW_SECONDS]
        if recent:
            _attempts[username] = recent
        else:
            _attempts.pop(username, None)
        return len(recent) >= MAX_ATTEMPTS


def record_failure(username):
    with _lock:
        now = time.time()
        if len(_attempts) >= MAX_TRACKED:
            _prune(now)
        if len(_attempts) >= MAX_TRACKED and username not in _attempts:
            return  # saturated with live lockouts: refuse to track more names
        _attempts.setdefault(username, []).append(now)


def record_success(username):
    with _lock:
        _attempts.pop(username, None)
