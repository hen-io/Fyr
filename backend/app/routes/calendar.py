from datetime import datetime, timedelta, timezone

import re

from flask import Blueprint, current_app, jsonify

from .widgets import _find_widget

calendar_bp = Blueprint("calendar", __name__)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _flatten(point):
    # HA's calendar API returns each start/end as {"dateTime": "..."} for a
    # timed event or {"date": "..."} for an all-day one - flatten both to a
    # single ISO string so the frontend doesn't need to know the difference.
    if not isinstance(point, dict):
        return None
    return point.get("dateTime") or point.get("date")


_CALENDAR_ID = re.compile(r"^calendar\.[a-z0-9_]+$")


def _collect(entities, days, limit):
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=days)
    ha = current_app.datasources.get("home_assistant")

    normalized = []
    any_succeeded = False
    for entity in entities:
        try:
            events = ha.list_calendar_events(entity, _iso(now), _iso(window_end))
        except Exception:
            # One bad/unreachable calendar shouldn't take the others down.
            continue
        any_succeeded = True
        for e in events:
            if not isinstance(e, dict):
                continue
            start = _flatten(e.get("start"))
            if not start:
                continue
            normalized.append({"title": e.get("summary", ""), "start": start, "end": _flatten(e.get("end")), "calendar": entity})

    if not any_succeeded:
        return None
    normalized.sort(key=lambda e: e["start"])
    return normalized[:limit]


@calendar_bp.route("/api/calendar/upcoming")
def upcoming():
    # HA_CALENDAR_ENTITY is comma-separated - one or many calendar.* entities.
    entities = [e.strip() for e in current_app.config["HA_CALENDAR_ENTITY"].split(",") if e.strip()]
    if not entities:
        return jsonify({"error": "calendar_not_configured"}), 404
    result = _collect(entities, 14, 5)
    if result is None:
        return jsonify({"error": "calendar_unavailable"}), 502
    return jsonify(result)


@calendar_bp.route("/api/widget/<widget_id>/events")
def widget_events(widget_id):
    """Events for a calendar widget, from the calendars chosen in that
    widget's saved config (falling back to HA_CALENDAR_ENTITY). The client
    never names entities - only the saved config does."""
    widget = _find_widget(widget_id)
    if widget is None or widget.get("type") != "calendar":
        return jsonify({"error": "not_found"}), 404

    configured = widget.get("calendars")
    if not isinstance(configured, list) or not configured:
        configured = [e.strip() for e in current_app.config["HA_CALENDAR_ENTITY"].split(",") if e.strip()]
    entities = [e for e in configured if isinstance(e, str) and _CALENDAR_ID.match(e)][:12]
    if not entities:
        return jsonify({"error": "calendar_not_configured"}), 404

    def bounded(name, default, lo, hi):
        try:
            return min(hi, max(lo, int(widget.get(name) or default)))
        except (TypeError, ValueError):
            return default

    result = _collect(entities, bounded("days", 14, 1, 60), bounded("count", 8, 1, 30))
    if result is None:
        return jsonify({"error": "calendar_unavailable"}), 502
    return jsonify(result)
