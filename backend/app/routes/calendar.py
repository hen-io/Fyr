from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify

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


@calendar_bp.route("/api/calendar/upcoming")
def upcoming():
    # HA_CALENDAR_ENTITY is comma-separated - one or many calendar.* entities.
    entities = [e.strip() for e in current_app.config["HA_CALENDAR_ENTITY"].split(",") if e.strip()]
    if not entities:
        return jsonify({"error": "calendar_not_configured"}), 404

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=14)
    ha = current_app.datasources.get("home_assistant")

    normalized = []
    any_succeeded = False
    for entity in entities:
        try:
            events = ha.list_calendar_events(entity, _iso(now), _iso(window_end))
        except Exception:
            # One bad/unreachable calendar shouldn't take the others down -
            # skip it and keep going with whatever else responds.
            continue
        any_succeeded = True
        for e in events:
            if not isinstance(e, dict):
                continue
            start = _flatten(e.get("start"))
            if not start:
                continue
            normalized.append(
                {
                    "title": e.get("summary", ""),
                    "start": start,
                    "end": _flatten(e.get("end")),
                    "calendar": entity,
                }
            )

    if not any_succeeded:
        return jsonify({"error": "calendar_unavailable"}), 502

    normalized.sort(key=lambda e: e["start"])
    return jsonify(normalized[:5])
