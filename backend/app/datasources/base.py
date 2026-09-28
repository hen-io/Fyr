from abc import ABC, abstractmethod


class DataSource(ABC):
    """A named source of live values (one Home Assistant connection, one
    MQTT broker connection, etc). Callers ask for a specific key (an HA
    entity_id, an MQTT topic) - the source decides how to fetch/cache it.
    Adding a new source type later means implementing this interface and
    registering it in registry.py - nothing else needs to change."""

    name: str

    @abstractmethod
    def get_value(self, key):
        """Return the current value for `key`, or raise on failure."""
