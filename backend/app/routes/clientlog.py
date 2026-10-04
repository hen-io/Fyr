"""What browsers report about their own use of the page: a visit, an app
opened, a dashboard page shown, an error in the page. One line each on the
backend's log, marked CLIENT - the Logs tab shows them as "Frontend".

Anyone who can load the page can post here, so: a fixed list of events and
fields, every value clipped and escaped (audit._clean), and a ceiling per
address so the log cannot be flooded."""

import threading
import time

from flask import Blueprint, jsonify, session

from .. import audit
from ..reqtools import client_address, json_object, text

clientlog_bp = Blueprint("clientlog", __name__)

_EVENTS = {
    "visit": ("screen", "language", "mode"),
    "app_opened": ("app", "how"),
    "page_shown": ("page",),
    "panel_opened": ("panel",),
    "command": ("command",),
    "error": ("message", "where"),
}
_PER_MINUTE = 40
_MAX_TRACKED = 5000
_lock = threading.Lock()
_seen = {}  # address -> [times of its recent reports]


def _allowed(address):
    now = time.monotonic()
    with _lock:
        recent = [t for t in _seen.get(address, ()) if now - t < 60]
        if len(recent) >= _PER_MINUTE or (address not in _seen and len(_seen) >= _MAX_TRACKED):
            _seen[address] = recent
            return False
        recent.append(now)
        _seen[address] = recent
        if len(_seen) >= _MAX_TRACKED:
            for key in [k for k, stamps in _seen.items() if not stamps or now - stamps[-1] >= 60]:
                del _seen[key]
        return True


@clientlog_bp.route("/api/client-log", methods=["POST"])
def client_log():
    body = json_object()
    event = text(body, "event", 40)
    if event not in _EVENTS:
        return jsonify({"error": "invalid_event"}), 400
    address = client_address()
    if not _allowed(address):
        return jsonify({"error": "too_many"}), 429
    fields = {name: text(body, name, 300) for name in _EVENTS[event]}
    audit.record_client(event, user=session.get("username") or "-", addr=address, **{name: value for name, value in fields.items() if value})
    return jsonify({"ok": True})
