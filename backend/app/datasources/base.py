from abc import ABC, abstractmethod


class DataSource(ABC):
    """A named source of live values (one Home Assistant connection, one
    MQTT broker connection, etc). Callers ask for a specific key (an HA
    entity_id, an MQTT topic) - the source decides how to fetch/cache it.
    Adding a new source type later means implementing this interface and
    registering it in registry.py - nothing else needs to change."""

    name: str

    @abstractmethod
    def get_value(self, key, max_age=None):
        """Return the current value for `key`, or raise on failure.
        `max_age` (seconds) lets a caller ask for a fresher value than the
        source's default cache window - sources without a cache ignore it."""

    def is_configured(self):
        """False when the source exists but can't work yet (e.g. Home
        Assistant with no URL/token) - lets the editor say so."""
        return True

    def check(self):
        """Live connectivity probe for the admin panel:
        {"connected": bool, "detail": str|None, "latency_ms": int|None}."""
        return {"connected": True, "detail": None, "latency_ms": None}

    def list_keys(self):
        """Known keys for editor autocompletion: [{"key", "name", "unit"}].
        Optional; a source that can't enumerate returns nothing."""
        return []

    def run_action(self, spec):
        """Do something (call an HA service, publish an MQTT message).
        `spec` is a dict already validated by the caller - each source
        documents the keys it understands. Optional: sources that can only
        be read leave this unimplemented."""
        raise NotImplementedError(f"{self.name} does not support actions")

    def get_history(self, key, hours):
        """Return [(unix_ts, raw_value), ...] for the last `hours` hours,
        oldest first. Optional, like run_action."""
        raise NotImplementedError(f"{self.name} does not provide history")
