import fnmatch
import ssl
import threading
import time
import urllib.error
import urllib.request
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
# fetch an arbitrary attacker-supplied URL would be a real SSRF risk. It
# only ever checks the HOSTNAME of the requested URL against
# STATUS_ALLOWED_HOSTS - see config.py.

status_bp = Blueprint("status", __name__)


def _hostname_allowed(hostname, patterns):
    hostname = (hostname or "").lower()
    return any(fnmatch.fnmatch(hostname, pattern.lower()) for pattern in patterns)


def _origin(url):
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    return (parsed.scheme, parsed.hostname.lower(), port)


def _configured_origins():
    """Origins (scheme, host, port) of the apps the admin configured - the
    tile's url or its internal (status-check) url. Checking these needs no
    entry in STATUS_ALLOWED_HOSTS: they were entered by an admin, so the
    endpoint can only ever probe addresses that are already on the dashboard.
    Apps the caller may not see (hidden category / logged-in-only) are left
    out, so status can't be used to probe them."""
    data = _load_yaml(_apps_path(current_app.config), {})
    viewer = _viewer()
    hidden = _hidden_categories(data, viewer)
    origins = set()
    for app in _flatten_apps(data):
        if app.get("category") in hidden or (viewer == "anonymous" and app.get("visibility") == "authenticated"):
            continue
        for key in ("internalUrl", "url"):
            origin = _origin(app.get(key))
            if origin:
                origins.add(origin)
    return origins


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
_cache = {}
_cache_lock = threading.Lock()


@status_bp.route("/api/status")
def check_status():
    target = request.args.get("url", "")
    parsed = urlparse(target)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return jsonify({"status": "unknown", "error": "invalid_url"}), 400

    if not (
        _hostname_allowed(parsed.hostname, current_app.config["STATUS_ALLOWED_HOSTS"])
        or _origin(target) in _configured_origins()
    ):
        return jsonify({"status": "unknown", "error": "host_not_allowed"}), 403

    now = time.time()
    with _cache_lock:
        hit = _cache.get(target)
    if hit and now - hit[0] < _CACHE_TTL:
        return jsonify({"status": hit[1]})

    try:
        req = urllib.request.Request(target, method="GET", headers={"User-Agent": "fyr-status-check"})
        with _opener.open(req, timeout=5) as resp:
            up = resp.status == 200
    except urllib.error.HTTPError as e:
        # A redirect refused by _NoRedirect surfaces as an HTTPError with
        # the original 3xx code - the target answered, it just wanted to
        # send us somewhere else we won't follow, which still counts as
        # "up" (matches the original browser-based check, which silently
        # followed such redirects to the same conclusion). A genuine
        # 4xx/5xx is "down", same as a plain status == 200 check would
        # have treated it.
        up = 300 <= e.code < 400
    except urllib.error.URLError as e:
        # A self-signed / internal-CA certificate (common for local addresses)
        # still means the host answered - it is up, just not publicly trusted.
        up = isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError)
    except Exception:
        up = False

    result = "up" if up else "down"
    with _cache_lock:
        if len(_cache) > 512:
            _cache.clear()
        _cache[target] = (now, result)
    return jsonify({"status": result})
