import fnmatch
import ssl
from collections import deque
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, request

from .config import _apps_path, _flatten_apps, _hidden_categories, _load_yaml, _viewer

# Runs the up/down check server-side instead of in the browser. Two reasons:
# 1. The browser version could only tell "up" from "down" for cross-origin
#    targets via opaque no-cors probes with retries - slow and unreliable.
#    A server-side GET just reads the real status code.
# 2. A browser on an https:// page can't fetch an http:// target at all
#    (mixed content) - the backend has no such restriction, so that whole
#    "unknown" case from the old client-side hook goes away.
#
# The one thing this endpoint must never become is an open URL fetcher: this
# container has network_mode: host, i.e. full LAN access, so a request to
# fetch an arbitrary attacker-supplied URL would be a real SSRF risk. It only
# checks URLs that are on the dashboard (exactly as configured), plus any host
# explicitly opened up with STATUS_ALLOWED_HOSTS - see config.py.

status_bp = Blueprint("status", __name__)


def _hostname_allowed(hostname, patterns):
    hostname = (hostname or "").lower()
    return any(fnmatch.fnmatch(hostname, pattern.lower()) for pattern in patterns)


def _configured_urls():
    """The exact URLs an admin put on the dashboard (a tile's url or its
    internal status-check url) that the caller is allowed to see. Checking
    these needs no entry in STATUS_ALLOWED_HOSTS. Only these exact URLs - not
    other paths on the same host - or the endpoint would be a way to send a
    GET to any path of an internal service and learn whether it answered.
    Apps the caller may not see (hidden category / logged-in-only) are left
    out, so status can't be used to probe them either."""
    data = _load_yaml(_apps_path(current_app.config), {})
    viewer = _viewer()
    hidden = _hidden_categories(data, viewer)
    urls = set()
    for app in _flatten_apps(data):
        if app.get("category") in hidden or (viewer == "anonymous" and app.get("visibility") == "authenticated"):
            continue
        for key in ("internalUrl", "url"):
            value = app.get(key)
            if isinstance(value, str) and value.strip():
                urls.add(value.strip())
    return urls


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urlopen follows redirects by default - which would let an allow-
    listed URL redirect to an arbitrary internal address and have this
    endpoint silently fetch THAT instead, completely bypassing the
    hostname check above. Refusing to follow closes that hole; a 3xx is
    still treated as "the server answered" (up), just without chasing it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)

# Every tile asks about its own URL, all at once on page load and again every
# minute per browser - a short cache means several browsers (or a refresh)
# share one real request instead of hammering each app.
_CACHE_TTL = 20
_HISTORY = 20  # how many past checks are kept per address (for "up 19 of the last 20")
_cache = {}  # address -> (time, result dict)
_history = {}  # address -> deque of 1 (up) / 0 (down), oldest first
_cache_lock = threading.Lock()


def _allowed(target):
    return target in _configured_urls() or _hostname_allowed(urlparse(target).hostname, current_app.config["STATUS_ALLOWED_HOSTS"])


def _valid(target):
    try:
        parsed = urlparse(target)
        parsed.port  # noqa: B018 - raises ValueError for a malformed port
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname) and len(target) <= 2000


@status_bp.route("/api/status")
def check_status():
    """Is this app up, how fast did it answer, how has it done lately - and,
    with ?frame=<the address a window would load>, whether that address lets
    itself be shown inside another page."""
    target = request.args.get("url", "").strip()
    if not _valid(target):
        return jsonify({"status": "unknown", "error": "invalid_url"}), 400
    if not _allowed(target):
        return jsonify({"status": "unknown", "error": "host_not_allowed"}), 403

    answer = dict(_probe(target))
    frame = request.args.get("frame", "").strip()
    if frame and _valid(frame) and _allowed(frame):
        answer["frame"] = _probe(frame)["frame"]
    answer["frame"] = _framing(answer.get("frame"), request.host)
    return jsonify(answer)


def _framing(policy, own_host):
    """"blocked" when the app's headers forbid showing it in a window on this
    site, else "ok" (None when the app did not answer). `policy` is what
    _probe read: {"xfo": ..., "ancestors": [...]}."""
    if policy is None:
        return None
    own = (own_host or "").lower()
    ancestors = policy.get("ancestors")
    if ancestors is not None:  # frame-ancestors, when present, is what browsers go by
        for source in ancestors:
            source = source.strip("'\"").lower()
            if source in ("*", "http:", "https:"):
                return "ok"
            host = source.split("://", 1)[-1].rstrip("/")
            if host and own and (fnmatch.fnmatch(own, host) or fnmatch.fnmatch(own.split(":")[0], host)):
                return "ok"
        return "blocked"
    xfo = (policy.get("xfo") or "").lower()
    if "deny" in xfo:
        return "blocked"
    if "sameorigin" in xfo:
        return "ok" if policy.get("host", "").lower() == own else "blocked"
    return "ok"


def _frame_policy(headers, target):
    ancestors = None
    for value in headers.get_all("Content-Security-Policy") or []:
        for directive in value.split(";"):
            parts = directive.split()
            if parts and parts[0].lower() == "frame-ancestors":
                ancestors = parts[1:]
    return {"xfo": headers.get("X-Frame-Options"), "ancestors": ancestors, "host": urlparse(target).netloc}


def _probe(target):
    """{"status", "ms", "history", "frame"} for one already-approved URL,
    through the shared cache. `frame` is the raw framing policy (see _framing)."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(target)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    policy = None
    started = time.perf_counter()
    try:
        req = urllib.request.Request(target, method="GET", headers={"User-Agent": "fyr-status-check"})
        with _opener.open(req, timeout=5) as resp:
            up = resp.status == 200
            policy = _frame_policy(resp.headers, target)
    except urllib.error.HTTPError as e:
        # A redirect refused by _NoRedirect surfaces as an HTTPError with
        # the original 3xx code - the target answered, it just wanted to
        # send us somewhere else we won't follow, which still counts as
        # "up" (matches the original browser-based check, which silently
        # followed such redirects to the same conclusion). A genuine
        # 4xx/5xx is "down", same as a plain status == 200 check would
        # have treated it.
        up = 300 <= e.code < 400
        policy = _frame_policy(e.headers, target)
    except urllib.error.URLError as e:
        # A self-signed / internal-CA certificate (common for local addresses)
        # still means the host answered - it is up, just not publicly trusted.
        up = isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError)
    except Exception:
        up = False
    elapsed = round((time.perf_counter() - started) * 1000)

    with _cache_lock:
        if len(_cache) > 512:
            _cache.clear()
            _history.clear()
        past = _history.setdefault(target, deque(maxlen=_HISTORY))
        past.append(1 if up else 0)
        result = {"status": "up" if up else "down", "ms": elapsed if up else None, "history": list(past), "frame": policy}
        _cache[target] = (now, result)
    return result


@status_bp.route("/api/status/summary")
def status_summary():
    """Every app the caller may see, with its status, in one answer - for the
    "Appstatus" widget (one request instead of one per app). Uses the same
    cache as the per-tile checks, so it costs the apps nothing extra."""
    data = _load_yaml(_apps_path(current_app.config), {})
    viewer = _viewer()
    hidden = _hidden_categories(data, viewer)
    apps = []
    for app in _flatten_apps(data):
        if app.get("category") in hidden or (viewer == "anonymous" and app.get("visibility") == "authenticated"):
            continue
        target = next((app[key].strip() for key in ("internalUrl", "url") if isinstance(app.get(key), str) and app[key].strip()), None)
        if not target or urlparse(target).scheme not in ("http", "https"):
            continue
        apps.append((str(app.get("title") or target), target))
    apps = apps[:200]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda entry: _probe(entry[1]), apps))
    items = [{"title": title, "status": result["status"], "ms": result["ms"]} for (title, _target), result in zip(apps, results, strict=True)]
    states = [result["status"] for result in results]
    return jsonify({"items": items, "up": states.count("up"), "down": states.count("down"), "total": len(items)})


@status_bp.route("/api/status/framing")
def framing_summary():
    """{app title: "blocked" | "ok"} for the apps the caller may see: which of
    them refuse to be shown in a window (the admin panel's Apps tab)."""
    data = _load_yaml(_apps_path(current_app.config), {})
    viewer = _viewer()
    hidden = _hidden_categories(data, viewer)
    apps = []
    for app in _flatten_apps(data):
        if app.get("category") in hidden or (viewer == "anonymous" and app.get("visibility") == "authenticated"):
            continue
        target = app.get("url").strip() if isinstance(app.get("url"), str) else ""
        if _valid(target):
            apps.append((str(app.get("title") or target), target))
    apps = apps[:200]
    own = request.host
    with ThreadPoolExecutor(max_workers=8) as pool:
        verdicts = list(pool.map(lambda entry: _probe(entry[1])["frame"], apps))
    return jsonify({title: _framing(policy, own) for (title, _target), policy in zip(apps, verdicts, strict=True) if policy is not None})
