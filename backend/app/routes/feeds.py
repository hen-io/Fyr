import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from flask import Blueprint, jsonify, request

from ..auth import require_role
from ..datasources import http
from .widgets import _find_widget

feeds_bp = Blueprint("feeds", __name__)

# News feeds for the "feed" widget. The browser never names a URL: the
# endpoint only fetches what is saved in the widget's own config (set by an
# admin), so it cannot be used to make the server fetch arbitrary addresses.
_TTL = 600
_MAX_BYTES = 2 * 1024 * 1024
_cache = {}
_lock = threading.Lock()


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _text(node, *names):
    for child in node:
        if _local(child.tag) in names and (child.text or "").strip():
            return child.text.strip()
    return None


def _when(value):
    """An RSS (RFC 822) or Atom (ISO 8601) date -> epoch milliseconds, or None."""
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _link(node):
    for child in node:
        if _local(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href and child.attrib.get("rel", "alternate") == "alternate":
            return href
        if (child.text or "").strip():
            return child.text.strip()
    return None


def parse_feed(payload):
    """(feed title, [{"title", "link", "time_ms"}]) from RSS 2.0 or Atom."""
    # A document type declaration is where entity-expansion ("billion laughs")
    # and external-entity tricks live; no real feed needs one.
    head = payload[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in payload.lower():
        raise ValueError("feed declares a DTD")
    root = ET.fromstring(payload)
    channel = root
    if _local(root.tag) == "rss":
        channel = next((c for c in root if _local(c.tag) == "channel"), root)
    title = _text(channel, "title")
    items = []
    for node in channel.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        link = _link(node)
        if link and not link.lower().startswith(("http://", "https://")):
            link = None  # never hand the page a javascript: or data: address
        items.append({"title": (_text(node, "title") or "").strip()[:300], "link": link, "time_ms": _when(_text(node, "pubdate", "published", "updated", "date"))})
    return title, [item for item in items if item["title"]]


def _fetch(url):
    now = time.time()
    with _lock:
        hit = _cache.get(url)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    _status, _headers, payload = http.request(url, headers={"User-Agent": "Fyr feed widget", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}, timeout=8, follow_redirects=True, max_body=_MAX_BYTES)
    parsed = parse_feed(payload)
    with _lock:
        if len(_cache) > 64:
            _cache.clear()
        _cache[url] = (now, parsed)
    return parsed


@feeds_bp.route("/api/widget/<widget_id>/feed")
def widget_feed(widget_id):
    widget = _find_widget(widget_id)
    if widget is None or widget.get("type") != "feed":
        return jsonify({"error": "not_found"}), 404
    return _feed_response(widget)


@feeds_bp.route("/api/feed-preview", methods=["POST"])
@require_role("admin")
def preview_feed():
    """The editor's live preview of a feed widget that is not saved yet."""
    widget = request.get_json(silent=True)
    if not isinstance(widget, dict):
        return jsonify({"error": "invalid_body"}), 400
    return _feed_response(widget)


def _feed_response(widget):
    urls = []
    for entry in widget.get("feeds") or []:
        url = entry.get("url") if isinstance(entry, dict) else entry
        if isinstance(url, str) and url.strip().lower().startswith(("http://", "https://")):
            urls.append((url.strip(), entry.get("name") if isinstance(entry, dict) else None))
    if not urls:
        return jsonify({"error": "feed_not_configured"}), 404
    try:
        count = min(40, max(1, int(widget.get("count") or 8)))
    except (TypeError, ValueError):
        count = 8

    items, failed = [], 0
    for url, name in urls[:8]:
        try:
            title, entries = _fetch(url)
        except Exception:
            failed += 1
            continue
        for entry in entries:
            items.append({**entry, "source": name or title})
    if failed == len(urls[:8]):
        return jsonify({"error": "feed_unavailable"}), 502
    items.sort(key=lambda item: item["time_ms"] or 0, reverse=True)
    return jsonify({"items": items[:count]})
