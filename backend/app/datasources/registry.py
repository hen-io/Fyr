from .home_assistant import HomeAssistantSource
from .mqtt import MqttSource


class DataSourceRegistry:
    """name -> DataSource instance. Built once at app startup from Config.
    Adding a third source type means adding one branch here."""

    def __init__(self, config):
        self._sources = {
            "home_assistant": HomeAssistantSource(
                config.HA_URL, config.HA_TOKEN, cache_ttl=config.WEATHER_CACHE_TTL
            ),
        }

        if config.MQTT_ENABLED:
            mqtt_source = MqttSource(config.MQTT_HOST, config.MQTT_PORT, config.MQTT_USER, config.MQTT_PASS)
            mqtt_source.start()
            self._sources["mqtt"] = mqtt_source

    def describe(self):
        """Which sources exist and whether they're usable - for the widget
        editor to warn ("MQTT is not enabled") instead of letting an admin
        build a widget that can never show anything."""
        return {
            name: {"enabled": name in self._sources, "configured": name in self._sources and self._sources[name].is_configured()}
            for name in ("home_assistant", "mqtt")
        }

    def check_all(self):
        out = {}
        for name in ("home_assistant", "mqtt"):
            if name not in self._sources:
                out[name] = {"enabled": False}
                continue
            try:
                out[name] = {"enabled": True, **self._sources[name].check()}
            except Exception as err:
                out[name] = {"enabled": True, "connected": False, "detail": str(err)[:120], "latency_ms": None}
        return out

    def get(self, name):
        source = self._sources.get(name)
        if not source:
            raise KeyError(f"Unknown data source '{name}'")
        return source
