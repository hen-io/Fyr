"""Small helpers every route shares for reading a request safely."""

from flask import current_app, request

_LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def client_address():
    """The address the request really came from, for rate limiting.

    The backend only ever listens on loopback behind the container's own
    nginx, which appends the address it saw to X-Forwarded-For. With
    TRUSTED_PROXIES=1 (the default) that last entry is used. If another
    reverse proxy sits in front of the container, set TRUSTED_PROXIES=2 so the
    entry before it - the address THAT proxy saw - is used instead. Entries
    further left are supplied by the client and are never trusted. A request
    that does not arrive over loopback has no proxy in front at all, so its
    own peer address is used and the header is ignored."""
    peer = request.remote_addr or "-"
    if peer not in _LOOPBACK:
        return peer
    hops = [h.strip() for h in (request.headers.get("X-Forwarded-For") or "").split(",") if h.strip()]
    trusted = max(1, int(current_app.config.get("TRUSTED_PROXIES", 1)))
    if len(hops) >= trusted:
        return hops[-trusted][:64]
    return hops[0][:64] if hops else peer


def json_object():
    """The request body as a dict, or {} for anything else (no body, a list, a
    string, invalid JSON) - so routes never index into the wrong type."""
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def text(body, name, limit=500):
    """A string field from a JSON body: stripped, or "" when it is missing,
    not a string, or longer than `limit`."""
    value = body.get(name) if isinstance(body, dict) else None
    if not isinstance(value, str) or len(value) > limit:
        return ""
    return value.strip()


def secret(body, name, limit=1024):
    """A password-like field: returned exactly as sent (never stripped), or ""
    when it is missing, not a string or absurdly long."""
    value = body.get(name) if isinstance(body, dict) else None
    return value if isinstance(value, str) and len(value) <= limit else ""
