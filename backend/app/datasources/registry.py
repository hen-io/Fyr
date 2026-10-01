import threading

from .. import connections
from .arr import RadarrSource, SonarrSource
from .backrest import BackrestSource
from .home_assistant import HomeAssistantSource
from .infra import AdGuardSource, FrigateSource, ProwlarrSource, ProxmoxSource, UptimeKumaSource
from .media import ImmichSource, JellyfinSource, SeerrSource
from .mqtt import MqttSource
from .qbittorrent import QBittorrentSource
from .system import SystemSource

# Every integration the app knows about. Adding one = write a DataSource
# subclass (see base.py for what it can provide) and list it here; the admin
# panel form, the source pickers and the widget editor all derive from it.
CATALOG = (
    HomeAssistantSource,
    MqttSource,
    SystemSource,
    SonarrSource,
    RadarrSource,
    ProwlarrSource,
    QBittorrentSource,
    JellyfinSource,
    SeerrSource,
    ImmichSource,
    FrigateSource,
    AdGuardSource,
    UptimeKumaSource,
    ProxmoxSource,
    BackrestSource,
)
CATALOG_BY_ID = {cls.id: cls for cls in CATALOG}
# Widget types that an integration serves itself (through widget_data()).
INTEGRATION_WIDGETS = frozenset(widget for cls in CATALOG for widget in cls.WIDGETS)


class DataSourceRegistry:
    """id -> live integration instance, for every enabled integration.
    Settings come from the environment (first-run defaults) overlaid with
    what the admin saved in the UI (connections.json)."""

    def __init__(self, app_config, data_dir):
        self._config = app_config
        self._data_dir = data_dir
        self._sources = {}
        self._lock = threading.Lock()
        self.reload()

    def settings(self, integration_id):
        """(enabled, values) for one integration: env defaults + saved."""
        cls = CATALOG_BY_ID[integration_id]
        saved = connections.load(self._data_dir, integration_id)
        env = cls.env_defaults(self._config)
        values = {**env, **{k: v for k, v in saved.items() if k != "enabled"}}
        enabled = saved.get("enabled", env.get("enabled", cls.default_enabled))
        return bool(enabled), values

    def reload(self, only=None):
        """(Re)build integrations from current settings - all of them, or
        just `only`. Routes look sources up per request, so swapping the
        entry is enough; a replaced source is stopped afterwards."""
        for cls in CATALOG:
            if only and cls.id != only:
                continue
            enabled, values = self.settings(cls.id)
            new = None
            if enabled:
                try:
                    new = cls.from_values(values, self._config)
                except Exception:
                    new = None
            with self._lock:
                old = self._sources.pop(cls.id, None)
                if new is not None:
                    self._sources[cls.id] = new
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    pass

    def describe(self):
        """Every integration and whether it is usable - for the widget
        editor (source pickers, "not enabled" warnings)."""
        with self._lock:
            live = dict(self._sources)
        return {
            cls.id: {
                "label": cls.label,
                "icon": cls.icon,
                "enabled": cls.id in live,
                "configured": cls.id in live and live[cls.id].is_configured(),
                "widgets": list(cls.WIDGETS),
            }
            for cls in CATALOG
        }

    def check_all(self):
        with self._lock:
            live = dict(self._sources)
        out = {}
        for cls in CATALOG:
            if cls.id not in live:
                out[cls.id] = {"label": cls.label, "enabled": False}
                continue
            try:
                out[cls.id] = {"label": cls.label, "enabled": True, **live[cls.id].check()}
            except Exception as err:
                out[cls.id] = {"label": cls.label, "enabled": True, "connected": False, "detail": str(err)[:120], "latency_ms": None}
        return out

    def get(self, name):
        with self._lock:
            source = self._sources.get(name)
        if not source:
            raise KeyError(f"Unknown data source '{name}'")
        return source
