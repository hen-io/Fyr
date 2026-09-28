import threading

from .base import DataSource


class MqttSource(DataSource):
    """Keeps a live {topic: last_payload} cache, updated by the MQTT
    client's own background thread as messages arrive. Deliberately does
    NOT subscribe to "#" (everything) on connect - that would pull in every
    device's traffic on the broker whether anything here needs it or not.
    Instead it subscribes lazily, one topic at a time, the first time
    something asks for that topic (get_value or a widget config naming it)."""

    name = "mqtt"

    def __init__(self, host, port, username=None, password=None, client_id="fyr-backend"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id
        self._values = {}
        self._subscribed = set()
        self._lock = threading.Lock()
        self._client = None

    def start(self):
        import paho.mqtt.client as mqtt

        client = mqtt.Client(client_id=self.client_id)
        if self.username:
            client.username_pw_set(self.username, self.password)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.connect(self.host, self.port, keepalive=60)
        client.loop_start()
        self._client = client

    def _on_connect(self, client, userdata, flags, rc):
        with self._lock:
            topics = list(self._subscribed)
        for topic in topics:
            client.subscribe(topic)

    def _on_message(self, client, userdata, msg):
        with self._lock:
            self._values[msg.topic] = msg.payload.decode("utf-8", errors="replace")

    def ensure_subscribed(self, topic):
        with self._lock:
            if topic in self._subscribed:
                return
            self._subscribed.add(topic)
        if self._client:
            self._client.subscribe(topic)

    def get_value(self, key):
        self.ensure_subscribed(key)
        with self._lock:
            if key not in self._values:
                raise KeyError(f"No message received yet for MQTT topic '{key}'")
            return self._values[key]
