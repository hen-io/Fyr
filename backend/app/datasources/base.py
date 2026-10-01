import collections
import threading
import time
from abc import ABC, abstractmethod


class DataSource(ABC):
    """An integration: a named source of live values (Home Assistant, an MQTT
    broker, Sonarr, ...). Callers ask for a specific key (an HA entity_id, an
    MQTT topic, a Sonarr metric) - the source decides how to fetch/cache it.

    What an integration can provide:
      * data     get_value / list_keys / get_history - readable by every
                 existing data widget (sensor, gauge, chip, graph, list ...)
      * widgets  WIDGETS - widget types whose data it serves itself through
                 widget_data() (a download queue, a release calendar, ...)
      * actions  ACTIONS - named, side-effecting operations a widget may
                 trigger through run_widget_action()
      * config   FIELDS - the settings the admin fills in (rendered as a form)

    Adding an integration = one subclass registered in registry.CATALOG."""

    id: str = ""
    label: str = ""
    category: str = "system"  # smarthome | media | downloads | system - how the admin panel groups them
    icon: str = "puzzle"  # mdi icon name
    description: str = ""
    FIELDS: list = []  # [{name, label, kind: text|url|password|number|bool, ...}]
    WIDGETS: tuple = ()
    ACTIONS: tuple = ()
    default_enabled = False

    @classmethod
    def env_defaults(cls, config):
        """First-run values from the environment (.env); saved settings win."""
        return {}

    @classmethod
    def from_values(cls, values, config):
        raise NotImplementedError

    @abstractmethod
    def get_value(self, key, max_age=None):
        """Return the current value for `key`, or raise on failure.
        `max_age` (seconds) lets a caller ask for a fresher value than the
        source's default cache window - sources without a cache ignore it."""

    def is_configured(self):
        """False when the source exists but can't work yet (e.g. no URL)."""
        return True

    def check(self):
        """Live connectivity probe for the admin panel:
        {"connected": bool, "detail": str|None, "latency_ms": int|None}."""
        return {"connected": True, "detail": None, "latency_ms": None}

    def list_keys(self):
        """Known keys for editor autocompletion: [{"key", "name", "unit"}]."""
        return []

    def run_action(self, spec):
        """Do something (call an HA service, publish an MQTT message).
        `spec` is a dict already validated by the caller."""
        raise NotImplementedError(f"{self.label} does not support actions")

    def get_history(self, key, hours):
        """Return [(unix_ts, raw_value), ...] for the last `hours` hours,
        oldest first."""
        raise NotImplementedError(f"{self.label} does not provide history")

    def widget_data(self, widget_type, widget):
        """JSON for one of this integration's own widget types. `widget` is
        the SAVED widget config - never client input."""
        raise NotImplementedError

    def run_widget_action(self, action, widget):
        raise NotImplementedError

    def stop(self):
        """Release connections/threads before being replaced."""


class MetricSource(DataSource):
    """Base for integrations that expose a handful of named numbers (queue
    length, download speed, ...) rather than arbitrary entities. Subclasses
    implement fetch_metrics() -> {key: (value, unit, name)}; values are then
    served in the same shape Home Assistant entities use, so every existing
    widget can display them, and a short in-memory history is recorded for
    graph widgets."""

    METRICS_TTL = 15  # seconds a fetched set of metrics is reused
    HISTORY_LEN = 600
    HISTORY_MIN_GAP = 20

    def __init__(self):
        self._metrics = {}
        self._metrics_at = 0.0
        self._history = {}
        self._lock = threading.Lock()

    def fetch_metrics(self):
        raise NotImplementedError

    def _current(self, max_age=None):
        ttl = self.METRICS_TTL if max_age is None else min(self.METRICS_TTL, max_age)
        now = time.time()
        with self._lock:
            fresh = self._metrics and now - self._metrics_at < ttl
            if fresh:
                return self._metrics
        metrics = self.fetch_metrics()
        with self._lock:
            self._metrics, self._metrics_at = metrics, now
            for key, (value, _unit, _name) in metrics.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                series = self._history.setdefault(key, collections.deque(maxlen=self.HISTORY_LEN))
                if not series or now - series[-1][0] >= self.HISTORY_MIN_GAP:
                    series.append((now, str(value)))
        return metrics

    def get_value(self, key, max_age=None):
        metrics = self._current(max_age)
        if key not in metrics:
            raise KeyError(f"Unknown {self.label} metric '{key}'")
        value, unit, name = metrics[key]
        attributes = {"friendly_name": name}
        if unit:
            attributes["unit_of_measurement"] = unit
        return {"entity_id": key, "state": str(value), "attributes": attributes}

    def list_keys(self):
        try:
            metrics = self._current()
        except Exception:
            return [{"key": k, "name": n, "unit": u} for k, (u, n) in self.KNOWN_METRICS.items()] if hasattr(self, "KNOWN_METRICS") else []
        return [{"key": key, "name": name, "unit": unit} for key, (_v, unit, name) in sorted(metrics.items())]

    def get_history(self, key, hours):
        cutoff = time.time() - hours * 3600
        with self._lock:
            return [(ts, value) for ts, value in self._history.get(key, ()) if ts >= cutoff]


class RestSource(MetricSource):
    """Base for the common case: a service at a URL, reached with an API key,
    a token or a username/password, that exposes numbers to show. A subclass
    states its FIELDS, how to authenticate (headers()), how to prove the
    connection works (probe()) and what to read (fetch_metrics())."""

    AUTH_ERROR = "Ugyldig API-nøkkel"
    VERIFY_FIELD = {"name": "verify_tls", "label": "Kontroller TLS-sertifikatet (slå av for selvsignert)", "kind": "bool", "default": True}

    def __init__(self, values):
        super().__init__()
        self.values = dict(values or {})
        self.url = (self.values.get("url") or "").rstrip("/")
        self.verify = self.values.get("verify_tls", True) is not False

    @classmethod
    def from_values(cls, values, config):
        return cls(values)

    def is_configured(self):
        return bool(self.url) and all(self.values.get(f["name"]) for f in self.FIELDS if f.get("required"))

    def headers(self):
        return {}

    def _url(self, path, params=None):
        from urllib.parse import urlencode

        return self.url + path + (f"?{urlencode(params)}" if params else "")

    def get(self, path, params=None, **kwargs):
        from . import http

        if not self.is_configured():
            raise RuntimeError(f"{self.label} is not configured")
        return http.get_json(self._url(path, params), headers=self.headers(), verify=self.verify, **kwargs)

    def get_text(self, path, params=None, **kwargs):
        from . import http

        if not self.is_configured():
            raise RuntimeError(f"{self.label} is not configured")
        return http.get_text(self._url(path, params), headers=self.headers(), verify=self.verify, **kwargs)

    def probe(self):
        """Talk to the service once; return a short description (name and
        version) or raise."""
        raise NotImplementedError

    def check(self):
        from . import http

        if not self.is_configured():
            return {"connected": False, "detail": "URL/API-nøkkel mangler", "latency_ms": None}
        started = time.time()
        try:
            detail = self.probe()
        except Exception as err:
            return {"connected": False, "detail": http.describe_failure(err, self.AUTH_ERROR), "latency_ms": None}
        return {"connected": True, "detail": detail, "latency_ms": int((time.time() - started) * 1000)}


def clamp_int(value, default, lo, hi):
    try:
        return min(hi, max(lo, int(value if value not in (None, "") else default)))
    except (TypeError, ValueError):
        return default


def list_item(title, subtitle=None, value=None, level=None, progress=None, icon=None, state=None):
    """One row of the generic list widget (frontend: types/list.jsx).
    level: ok | warn | bad | run | off - shown as a coloured dot.
    state: down | pending | maintenance | stopped | paused - a word the
    frontend shows in the viewer's language when there is no `value`."""
    return {"title": str(title), "subtitle": subtitle, "value": value, "level": level, "progress": progress, "icon": icon, "state": state}
