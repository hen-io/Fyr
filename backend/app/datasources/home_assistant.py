import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .base import DataSource


class HomeAssistantSource(DataSource):
    """Wraps Home Assistant's REST API. get_value(entity_id) returns that
    entity's full state payload (same shape HA itself returns), cached
    per-entity for cache_ttl seconds - so unrelated entities don't share a
    single cache slot the way the original weather_proxy.py did. Callers
    that need fresher data than the default window (dashboard widgets poll
    every few seconds) pass a smaller max_age."""

    name = "home_assistant"

    def __init__(self, url, token, cache_ttl=300, timeout=8):
        self.url = url
        self.token = token
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self._cache = {}  # entity_id -> (value, fetched_at)

    def _require_configured(self):
        if not self.url or not self.token:
            raise RuntimeError("Home Assistant is not configured (HA_URL/HA_TOKEN)")

    def _request(self, path, data=None):
        self._require_configured()
        headers = {"Authorization": f"Bearer {self.token}"}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(f"{self.url}{path}", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None

    def is_configured(self):
        return bool(self.url and self.token)

    def check(self):
        if not self.is_configured():
            return {"connected": False, "detail": "HA_URL/HA_TOKEN er ikke satt", "latency_ms": None}
        started = time.time()
        try:
            body = self._request("/api/config") or {}
        except urllib.error.HTTPError as err:
            detail = "Ugyldig token" if err.code == 401 else f"HTTP {err.code}"
            return {"connected": False, "detail": detail, "latency_ms": None}
        except Exception as err:
            return {"connected": False, "detail": str(getattr(err, "reason", err))[:120], "latency_ms": None}
        return {
            "connected": True,
            "detail": f"Home Assistant {body.get('version', '')}".strip(),
            "latency_ms": int((time.time() - started) * 1000),
        }

    def list_keys(self):
        states = self._request("/api/states") or []
        keys = [
            {
                "key": s["entity_id"],
                "name": (s.get("attributes") or {}).get("friendly_name"),
                "unit": (s.get("attributes") or {}).get("unit_of_measurement"),
            }
            for s in states
            if isinstance(s, dict) and "entity_id" in s
        ]
        return sorted(keys, key=lambda k: k["key"])[:3000]

    def get_value(self, key, max_age=None):
        ttl = self.cache_ttl if max_age is None else max_age
        cached = self._cache.get(key)
        now = time.time()
        if cached and (now - cached[1]) < ttl:
            return cached[0]
        value = self._request(f"/api/states/{urllib.parse.quote(key, safe='._')}")
        self._cache[key] = (value, now)
        return value

    def run_action(self, spec):
        """spec: {"domain": "light", "service": "toggle", "data": {...}} ->
        POST /api/services/<domain>/<service>. The cached state for the
        targeted entity is dropped so the next read reflects the change."""
        entity_id = (spec.get("data") or {}).get("entity_id")
        self._request(
            f"/api/services/{urllib.parse.quote(spec['domain'], safe='_')}/{urllib.parse.quote(spec['service'], safe='_')}",
            spec.get("data") or {},
        )
        if isinstance(entity_id, str):
            self._cache.pop(entity_id, None)

    def get_history(self, key, hours):
        start = datetime.now(timezone.utc) - timedelta(hours=hours)
        path = (
            f"/api/history/period/{urllib.parse.quote(start.strftime('%Y-%m-%dT%H:%M:%S+00:00'))}"
            f"?filter_entity_id={urllib.parse.quote(key, safe='._')}&minimal_response&no_attributes"
        )
        result = self._request(path) or []
        points = []
        for item in result[0] if result else []:
            stamp = item.get("last_changed") or item.get("last_updated")
            if not stamp:
                continue
            ts = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            points.append((ts, item.get("state")))
        return points

    def list_calendar_events(self, entity_id, start_iso, end_iso):
        """HA calendars: GET /api/calendars/<entity_id>?start=<ISO8601>&end=<ISO8601>."""
        query = urllib.parse.urlencode({"start": start_iso, "end": end_iso})
        return self._request(f"/api/calendars/{urllib.parse.quote(entity_id, safe='._')}?{query}")
