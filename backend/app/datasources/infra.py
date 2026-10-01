import re
import time

from . import http
from .base import RestSource, clamp_int, list_item


class AdGuardSource(RestSource):
    """AdGuard Home: how much DNS traffic there is and how much of it is blocked."""

    id = "adguard"
    category = "system"
    label = "AdGuard Home"
    icon = "shield-check"
    description = "DNS-filter: antall spørringer, andel blokkert og svartid."
    METRICS_TTL = 20
    AUTH_ERROR = "Feil brukernavn/passord"
    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "http://adguard:3000"},
        {"name": "username", "label": "Brukernavn", "kind": "text"},
        {"name": "password", "label": "Passord", "kind": "password"},
        RestSource.VERIFY_FIELD,
    ]

    def headers(self):
        if self.values.get("username"):
            return http.basic_auth(self.values["username"], self.values.get("password") or "")
        return {}

    def probe(self):
        return f"AdGuard Home {(self.get('/control/status') or {}).get('version', '')}".strip()

    def fetch_metrics(self):
        stats = self.get("/control/stats") or {}
        status = self.get("/control/status") or {}
        queries = stats.get("num_dns_queries") or 0
        blocked = stats.get("num_blocked_filtering") or 0
        return {
            "queries": (queries, None, "DNS-spørringer"),
            "blocked": (blocked, None, "Blokkert"),
            "blocked_percent": (round(blocked / queries * 100, 1) if queries else 0, "%", "Andel blokkert"),
            "avg_ms": (round((stats.get("avg_processing_time") or 0) * 1000, 1), "ms", "Svartid"),
            "protection": (1 if status.get("protection_enabled") else 0, None, "Beskyttelse på (1 = ja)"),
        }


class ProwlarrSource(RestSource):
    """Prowlarr: how many indexers there are and how they are doing."""

    id = "prowlarr"
    category = "downloads"
    label = "Prowlarr"
    icon = "radar"
    description = "Indeksere: antall, søk, treff og feil."
    METRICS_TTL = 60
    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "http://prowlarr:9696"},
        {"name": "api_key", "label": "API-nøkkel", "kind": "password", "required": True},
        RestSource.VERIFY_FIELD,
    ]

    def headers(self):
        return {"X-Api-Key": self.values.get("api_key") or ""}

    def probe(self):
        return f"Prowlarr {(self.get('/api/v1/system/status') or {}).get('version', '')}".strip()

    def fetch_metrics(self):
        indexers = self.get("/api/v1/indexer") or []
        stats = (self.get("/api/v1/indexerstats") or {}).get("indexers") or []
        health = self.get("/api/v1/health") or []
        total = lambda key: sum(int(s.get(key) or 0) for s in stats)  # noqa: E731
        return {
            "indexers": (len(indexers), None, "Indeksere"),
            "indexers_enabled": (sum(1 for i in indexers if i.get("enable")), None, "Aktive indeksere"),
            "queries": (total("numberOfQueries"), None, "Søk"),
            "grabs": (total("numberOfGrabs"), None, "Treff hentet"),
            "failed_queries": (total("numberOfFailedQueries"), None, "Mislykkede søk"),
            "health_issues": (len(health), None, "Helseproblemer"),
        }


class FrigateSource(RestSource):
    """Frigate NVR: cameras, detection load, recording disk and the latest
    detections. (Frigate's own API has no key; put it behind your network.)"""

    id = "frigate"
    category = "smarthome"
    label = "Frigate"
    icon = "cctv"
    description = "Kameraer: status, deteksjoner, lagring og siste hendelser."
    METRICS_TTL = 15
    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "http://frigate:5000"},
        RestSource.VERIFY_FIELD,
    ]
    WIDGETS = ("frigate_events",)

    def probe(self):
        return f"Frigate {self.get_text('/api/version').strip()[:40]}"

    def fetch_metrics(self):
        stats = self.get("/api/stats") or {}
        cameras = stats.get("cameras") or {}
        detectors = stats.get("detectors") or {}
        service = stats.get("service") or {}
        metrics = {
            "cameras": (len(cameras), None, "Kameraer"),
            "cameras_online": (sum(1 for c in cameras.values() if (c.get("camera_fps") or 0) > 0), None, "Kameraer i drift"),
            "detection_fps": (round(sum(c.get("detection_fps") or 0 for c in cameras.values()), 1), "fps", "Deteksjoner per sekund"),
            "uptime_hours": (round((service.get("uptime") or 0) / 3600, 1), "t", "Oppetid"),
        }
        speeds = [d.get("inference_speed") for d in detectors.values() if d.get("inference_speed") is not None]
        if speeds:
            metrics["inference_ms"] = (round(sum(speeds) / len(speeds), 1), "ms", "Inferenstid")
        system = (stats.get("cpu_usages") or {}).get("frigate.full_system") or {}
        try:
            metrics["cpu_percent"] = (round(float(system.get("cpu")), 1), "%", "Prosessor")
        except (TypeError, ValueError):
            pass
        for path, usage in (service.get("storage") or {}).items():
            if "recordings" in path and usage.get("total"):
                metrics["storage_percent"] = (round(usage.get("used", 0) / usage["total"] * 100, 1), "%", "Opptaksdisk brukt")
        return metrics

    def widget_data(self, widget_type, widget):
        if widget_type != "frigate_events":
            raise NotImplementedError(widget_type)
        count = clamp_int(widget.get("count"), 8, 1, 40)
        events = self.get("/api/events", {"limit": count}) or []
        items = []
        for event in events[:count]:
            score = event.get("top_score")
            if score is None:
                score = (event.get("data") or {}).get("top_score")
            items.append(
                list_item(
                    str(event.get("label") or "?").capitalize(),
                    subtitle=event.get("camera"),
                    value=None,
                    level="run" if not event.get("end_time") else None,
                    icon={"person": "walk", "car": "car", "cat": "cat", "dog": "dog", "bird": "bird"}.get(event.get("label"), "motion-sensor"),
                )
                | {"time_ms": int((event.get("start_time") or 0) * 1000), "score": round(score * 100) if isinstance(score, (int, float)) else None}
            )
        return {"items": items}


class ProxmoxSource(RestSource):
    """Proxmox VE through an API token (Datacenter -> Permissions -> API
    Tokens; the PVEAuditor role is enough): nodes, virtual machines and
    containers."""

    id = "proxmox"
    category = "system"
    label = "Proxmox VE"
    icon = "server-network"
    description = "Noder, virtuelle maskiner og containere: status, prosessor og minne."
    METRICS_TTL = 15
    AUTH_ERROR = "Ugyldig API-token"
    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "https://proxmox:8006"},
        {"name": "token_id", "label": "Token-ID", "kind": "text", "required": True, "placeholder": "fyr@pve!dashboard"},
        {"name": "token_secret", "label": "Token-hemmelighet", "kind": "password", "required": True},
        {**RestSource.VERIFY_FIELD, "default": False},
    ]
    WIDGETS = ("proxmox_guests",)

    def __init__(self, values):
        super().__init__(values)
        # Proxmox ships with a self-signed certificate: unchecked unless switched on.
        self.verify = self.values.get("verify_tls") is True

    def headers(self):
        return {"Authorization": f"PVEAPIToken={self.values.get('token_id')}={self.values.get('token_secret')}"}

    def probe(self):
        return f"Proxmox VE {((self.get('/api2/json/version') or {}).get('data') or {}).get('version', '')}".strip()

    def _resources(self):
        return [r for r in ((self.get("/api2/json/cluster/resources") or {}).get("data") or []) if isinstance(r, dict)]

    def fetch_metrics(self):
        resources = self._resources()
        nodes = [r for r in resources if r.get("type") == "node"]
        online = [n for n in nodes if n.get("status") == "online"]
        vms = [r for r in resources if r.get("type") == "qemu"]
        lxc = [r for r in resources if r.get("type") == "lxc"]
        cores = sum(n.get("maxcpu") or 0 for n in online)
        memory = sum(n.get("maxmem") or 0 for n in online)
        return {
            "nodes": (len(nodes), None, "Noder"),
            "nodes_online": (len(online), None, "Noder oppe"),
            "vms": (len(vms), None, "Virtuelle maskiner"),
            "vms_running": (sum(1 for v in vms if v.get("status") == "running"), None, "VM-er i drift"),
            "containers": (len(lxc), None, "Containere"),
            "containers_running": (sum(1 for c in lxc if c.get("status") == "running"), None, "Containere i drift"),
            "cpu_percent": (round(sum((n.get("cpu") or 0) * (n.get("maxcpu") or 0) for n in online) / cores * 100, 1) if cores else 0, "%", "Prosessor (klynge)"),
            "memory_percent": (round(sum(n.get("mem") or 0 for n in online) / memory * 100, 1) if memory else 0, "%", "Minne (klynge)"),
        }

    def widget_data(self, widget_type, widget):
        if widget_type != "proxmox_guests":
            raise NotImplementedError(widget_type)
        count = clamp_int(widget.get("count"), 12, 1, 60)
        wanted = widget.get("show") if widget.get("show") in ("all", "running", "nodes") else "all"
        resources = self._resources()
        rows = []
        for r in resources:
            kind = r.get("type")
            if kind not in ("node", "qemu", "lxc"):
                continue
            running = r.get("status") in ("running", "online")
            if wanted == "running" and not running:
                continue
            if wanted == "nodes" and kind != "node":
                continue
            memory = round((r.get("mem") or 0) / r["maxmem"] * 100) if r.get("maxmem") else None
            name = r.get("node") if kind == "node" else r.get("name") or str(r.get("vmid"))
            rows.append(
                (
                    {"node": 0, "qemu": 1, "lxc": 2}[kind],
                    not running,
                    str(name).lower(),
                    list_item(
                        name,
                        subtitle={"node": "node", "qemu": f"VM {r.get('vmid')}", "lxc": f"CT {r.get('vmid')}"}[kind],
                        value=f"{round((r.get('cpu') or 0) * 100)} % · {memory} %" if running and memory is not None else None,
                        level="ok" if running else "off",
                        progress=memory if running else None,
                        icon={"node": "server", "qemu": "monitor", "lxc": "cube-outline"}[kind],
                        state=None if running else "stopped",
                    ),
                )
            )
        rows.sort(key=lambda row: row[:3])
        return {"items": [row[3] for row in rows[:count]]}


_PROM_LINE = re.compile(r"^(\w+)\{(.*)\}\s+(-?[0-9.eE+]+)\s*$")
_PROM_LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


class UptimeKumaSource(RestSource):
    """Uptime Kuma through its /metrics endpoint (Settings -> API Keys): which
    monitors are up and how fast they answer."""

    id = "uptime_kuma"
    category = "system"
    label = "Uptime Kuma"
    icon = "heart-pulse"
    description = "Overvåking: hvor mange tjenester som er oppe/nede, og en liste med svartid."
    METRICS_TTL = 20
    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "http://uptime-kuma:3001"},
        {"name": "api_key", "label": "API-nøkkel", "kind": "password", "required": True},
        RestSource.VERIFY_FIELD,
    ]
    WIDGETS = ("kuma_monitors",)
    _STATUS = {0: "bad", 1: "ok", 2: "warn", 3: "off"}

    def headers(self):
        return http.basic_auth("", self.values.get("api_key") or "")

    def _monitors(self):
        """{name: {"status": 0-3, "ms": float|None}} parsed from the Prometheus text."""
        monitors = {}
        for line in self.get_text("/metrics").splitlines():
            match = _PROM_LINE.match(line)
            if not match or match.group(1) not in ("monitor_status", "monitor_response_time"):
                continue
            labels = dict(_PROM_LABEL.findall(match.group(2)))
            name = labels.get("monitor_name")
            if not name:
                continue
            entry = monitors.setdefault(name, {"status": None, "ms": None})
            value = float(match.group(3))
            if match.group(1) == "monitor_status":
                entry["status"] = int(value)
            elif value >= 0:
                entry["ms"] = value
        return monitors

    def probe(self):
        return f"Uptime Kuma ({len(self._monitors())} monitorer)"

    def fetch_metrics(self):
        statuses = [m["status"] for m in self._monitors().values()]
        return {
            "up": (statuses.count(1), None, "Oppe"),
            "down": (statuses.count(0), None, "Nede"),
            "pending": (statuses.count(2), None, "Venter"),
            "maintenance": (statuses.count(3), None, "Vedlikehold"),
            "total": (len(statuses), None, "Monitorer"),
        }

    def widget_data(self, widget_type, widget):
        if widget_type != "kuma_monitors":
            raise NotImplementedError(widget_type)
        count = clamp_int(widget.get("count"), 12, 1, 60)
        only_down = widget.get("show") == "down"
        rows = []
        monitors = self._monitors()
        for name, monitor in monitors.items():
            if only_down and monitor["status"] == 1:
                continue
            ms = monitor["ms"]
            state = {0: "down", 2: "pending", 3: "maintenance"}.get(monitor["status"])
            rows.append(
                (
                    monitor["status"] == 1,
                    name.lower(),
                    list_item(name, value=f"{round(ms)} ms" if ms is not None and state is None else None, level=self._STATUS.get(monitor["status"], "off"), state=state),
                )
            )
        rows.sort(key=lambda row: row[:2])
        statuses = [m["status"] for m in monitors.values()]
        return {"items": [row[2] for row in rows[:count]], "up": statuses.count(1), "down": statuses.count(0), "total": len(statuses), "checked_at": int(time.time())}
