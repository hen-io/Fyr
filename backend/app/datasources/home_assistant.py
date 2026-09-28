import json
import time
import urllib.error
import urllib.request

from .base import DataSource


class HomeAssistantSource(DataSource):
    """Wraps Home Assistant's REST API. get_value(entity_id) returns that
    entity's full state payload (same shape HA itself returns), cached
    per-entity for cache_ttl seconds - so unrelated entities don't share a
    single cache slot the way the original weather_proxy.py did."""

    name = "home_assistant"

    def __init__(self, url, token, cache_ttl=300, timeout=8):
        self.url = url
        self.token = token
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self._cache = {}  # entity_id -> (value, fetched_at)

    def get_value(self, key):
        cached = self._cache.get(key)
        now = time.time()
        if cached and (now - cached[1]) < self.cache_ttl:
            return cached[0]
        value = self._fetch_state(key)
        self._cache[key] = (value, now)
        return value

    def _fetch_state(self, entity_id):
        if not self.url or not self.token:
            raise RuntimeError("Home Assistant is not configured (HA_URL/HA_TOKEN)")
        req = urllib.request.Request(
            f"{self.url}/api/states/{entity_id}",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def list_calendar_events(self, entity_id, start_iso, end_iso):
        """HA calendars: GET /api/calendars/<entity_id>?start=<ISO8601>&end=<ISO8601>."""
        if not self.url or not self.token:
            raise RuntimeError("Home Assistant is not configured (HA_URL/HA_TOKEN)")
        req = urllib.request.Request(
            f"{self.url}/api/calendars/{entity_id}?start={start_iso}&end={end_iso}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
