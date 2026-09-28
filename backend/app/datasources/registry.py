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

    def get(self, name):
        source = self._sources.get(name)
        if not source:
            raise KeyError(f"Unknown data source '{name}'")
        return source
