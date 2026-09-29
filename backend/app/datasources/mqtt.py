import collections
import threading
import time

from .base import DataSource


class MqttSource(DataSource):
    """Keeps a live {topic: last_payload} cache, updated by the MQTT
    client's own background thread as messages arrive. Deliberately does
    NOT subscribe to "#" (everything) on connect - that would pull in every
    device's traffic on the broker whether anything here needs it or not.
    Instead it subscribes lazily, one topic at a time, the first time
    something asks for that topic (get_value or a widget config naming it).

    Also keeps a short in-memory history per subscribed topic (for graph
    widgets) - it starts filling from the moment a topic is first asked
    for, and is lost on restart, unlike Home Assistant's own recorder."""

    name = "mqtt"
    HISTORY_LEN = 400
    HISTORY_MIN_GAP = 5  # seconds - a chatty topic must not evict useful history

    def __init__(self, host, port, username=None, password=None, client_id="fyr-backend"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id
        self._values = {}
        self._history = {}
        self._subscribed = set()
        self._lock = threading.Lock()
        self._client = None
        self._connected = False

    def start(self):
        import paho.mqtt.client as mqtt

        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
        except AttributeError:  # paho-mqtt 1.x has no CallbackAPIVersion
            client = mqtt.Client(client_id=self.client_id)
        if self.username:
            client.username_pw_set(self.username, self.password)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        # connect_async + loop_start: a broker that's down (or slow) at
        # startup must not stop the whole app from booting - the client
        # thread just keeps retrying in the background until it's reachable.
        client.connect_async(self.host, self.port, keepalive=60)
        client.loop_start()
        self._client = client

    # *args: paho 1.x passes (client, userdata, flags, rc), 2.x passes
    # (client, userdata, flags, reason_code, properties) - only `client` is used.
    def _on_disconnect(self, *args):
        self._connected = False

    def _on_connect(self, client, userdata, flags, *args):
        self._connected = True
        with self._lock:
            topics = list(self._subscribed)
        for topic in topics:
            client.subscribe(topic)

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace")
        now = time.time()
        with self._lock:
            self._values[msg.topic] = payload
            history = self._history.setdefault(msg.topic, collections.deque(maxlen=self.HISTORY_LEN))
            if not history or now - history[-1][0] >= self.HISTORY_MIN_GAP:
                history.append((now, payload))

    def ensure_subscribed(self, topic):
        # Wildcards would subscribe to a whole tree of traffic - exactly the
        # firehose this source is designed to avoid.
        if not topic or "#" in topic or "+" in topic:
            raise ValueError("MQTT wildcards are not allowed in widget topics")
        with self._lock:
            if topic in self._subscribed:
                return
            self._subscribed.add(topic)
        if self._client:
            self._client.subscribe(topic)

    def get_value(self, key, max_age=None):
        self.ensure_subscribed(key)
        with self._lock:
            if key not in self._values:
                raise KeyError(f"No message received yet for MQTT topic '{key}'")
            return self._values[key]

    def stop(self):
        if self._client:
            self._client.loop_stop()
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def check(self):
        detail = f"{self.host}:{self.port}"
        if self._connected:
            return {"connected": True, "detail": detail, "latency_ms": None}
        return {"connected": False, "detail": f"Ingen forbindelse til {detail}", "latency_ms": None}

    def list_keys(self):
        # Only topics something has already asked for (and heard back on) are
        # known - there is deliberately no wildcard subscription to discover
        # the rest. Good enough to autocomplete topics already in use.
        with self._lock:
            return [{"key": topic, "name": None, "unit": None} for topic in sorted(self._values)]

    def get_history(self, key, hours):
        self.ensure_subscribed(key)
        cutoff = time.time() - hours * 3600
        with self._lock:
            return [(ts, value) for ts, value in self._history.get(key, ()) if ts >= cutoff]

    def run_action(self, spec):
        """spec: {"topic": str, "payload": str, "retain": bool}"""
        if not self._client:
            raise RuntimeError("MQTT client is not running")
        info = self._client.publish(spec["topic"], spec.get("payload", ""), retain=bool(spec.get("retain")))
        if info.rc != 0:
            raise RuntimeError(f"MQTT publish failed (rc={info.rc})")
