import threading
import time

from . import http
from .base import MetricSource

_DOWNLOADING = {"downloading", "forcedDL", "metaDL", "forcedMetaDL", "stalledDL", "queuedDL", "checkingDL", "allocating"}
_SEEDING = {"uploading", "forcedUP", "stalledUP", "queuedUP", "checkingUP"}
_PAUSED = {"pausedDL", "pausedUP", "stoppedDL", "stoppedUP"}
_ERRORED = {"error", "missingFiles"}
_FILTERS = ("all", "downloading", "seeding", "paused", "active", "errored")


class QBittorrentSource(MetricSource):
    """qBittorrent through its WebUI API v2. Logs in with the WebUI user and
    keeps the session cookie; a 403 (expired session) triggers one re-login.
    Provides speed / count metrics for the ordinary data widgets, a torrent
    list widget, and pause-all / resume-all actions."""

    id = "qbittorrent"
    category = "downloads"
    label = "qBittorrent"
    icon = "download-network"
    description = "Nedlastinger: hastighet, antall torrenter og en torrentliste."
    METRICS_TTL = 5
    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "http://qbittorrent:8080"},
        {"name": "username", "label": "Brukernavn (valgfritt)", "kind": "text"},
        {"name": "password", "label": "Passord (valgfritt)", "kind": "password"},
    ]
    WIDGETS = ("qbit_torrents",)
    ACTIONS = ("pause_all", "resume_all")

    def __init__(self, url, username, password):
        super().__init__()
        self.url = (url or "").rstrip("/")
        self.username = username or ""
        self.password = password or ""
        self._sid = None
        self._login_lock = threading.Lock()

    @classmethod
    def from_values(cls, values, config):
        return cls(values.get("url"), values.get("username"), values.get("password"))

    def is_configured(self):
        # Username and password are optional: qBittorrent can be set to skip
        # authentication for localhost / trusted subnets, in which case Fyr
        # simply calls the API without logging in.
        return bool(self.url)

    def _uses_login(self):
        return bool(self.username)

    # --- session ------------------------------------------------------------

    def _headers(self):
        headers = {"Referer": self.url, "Origin": self.url}
        if self._sid:
            headers["Cookie"] = self._sid
        return headers

    def _login(self):
        with self._login_lock:
            _status, headers, body = http.request(
                http.join(self.url, "/api/v2/auth/login"),
                headers={"Referer": self.url, "Origin": self.url},
                form={"username": self.username, "password": self.password},
                method="POST",
            )
            cookie = headers.get("Set-Cookie", "")
            if body.strip() != b"Ok." or "=" not in cookie:
                raise http.HttpError(401, "login failed")
            self._sid = cookie.split(";", 1)[0]

    def _call(self, path, *, params=None, form=None, method=None):
        if not self.is_configured():
            raise RuntimeError("qBittorrent is not configured")
        url = http.join(self.url, f"/api/v2{path}")
        if params:
            from urllib.parse import urlencode

            url += f"?{urlencode(params)}"
        for attempt in (0, 1):
            if not self._sid and self._uses_login():
                self._login()
            try:
                status, _headers, body = http.request(url, headers=self._headers(), form=form, method=method)
                return body
            except http.HttpError as err:
                if err.status == 403 and attempt == 0:
                    self._sid = None
                    continue
                raise

    def _json(self, path, **kwargs):
        import json

        body = self._call(path, **kwargs)
        return json.loads(body.decode("utf-8")) if body else None

    def check(self):
        if not self.is_configured():
            return {"connected": False, "detail": "URL mangler", "latency_ms": None}
        started = time.time()
        try:
            self._sid = None
            version = self._call("/app/version").decode("utf-8", "replace").strip()
        except http.HttpError as err:
            return {"connected": False, "detail": ("Feil brukernavn/passord" if self._uses_login() else "Krever innlogging – fyll inn brukernavn og passord") if err.status in (401, 403) else str(err), "latency_ms": None}
        except Exception as err:
            return {"connected": False, "detail": str(getattr(err, "reason", err))[:120], "latency_ms": None}
        return {"connected": True, "detail": f"qBittorrent {version}", "latency_ms": int((time.time() - started) * 1000)}

    # --- data ---------------------------------------------------------------

    def fetch_metrics(self):
        info = self._json("/transfer/info") or {}
        torrents = self._json("/torrents/info") or []
        maindata = self._json("/sync/maindata") or {}
        server = maindata.get("server_state") or {}
        states = [t.get("state") for t in torrents]
        metrics = {
            "download_speed": (round((info.get("dl_info_speed") or 0) / 1e6, 2), "MB/s", "Nedlastingshastighet"),
            "upload_speed": (round((info.get("up_info_speed") or 0) / 1e6, 2), "MB/s", "Opplastingshastighet"),
            "downloading": (sum(1 for s in states if s in _DOWNLOADING), None, "Laster ned"),
            "seeding": (sum(1 for s in states if s in _SEEDING), None, "Seeder"),
            "paused": (sum(1 for s in states if s in _PAUSED), None, "Pauset"),
            "errored": (sum(1 for s in states if s in _ERRORED), None, "Feil"),
            "total": (len(torrents), None, "Torrenter totalt"),
            "downloaded_total": (round((info.get("dl_info_data") or 0) / 1e9, 1), "GB", "Lastet ned (økt)"),
            "uploaded_total": (round((info.get("up_info_data") or 0) / 1e9, 1), "GB", "Lastet opp (økt)"),
        }
        if server.get("free_space_on_disk") is not None:
            metrics["free_space"] = (round(server["free_space_on_disk"] / 1e9, 1), "GB", "Ledig plass")
        ratio = server.get("global_ratio")
        if ratio not in (None, ""):
            try:
                metrics["ratio"] = (round(float(ratio), 2), None, "Delingsforhold")
            except (TypeError, ValueError):
                pass
        return metrics

    def widget_data(self, widget_type, widget):
        if widget_type != "qbit_torrents":
            raise NotImplementedError(widget_type)
        try:
            count = min(40, max(1, int(widget.get("count") or 8)))
        except (TypeError, ValueError):
            count = 8
        wanted = widget.get("filter") if widget.get("filter") in _FILTERS else "active"
        torrents = self._json("/torrents/info", params={"sort": "added_on", "reverse": "true"}) or []

        def keep(t):
            state = t.get("state")
            if wanted == "downloading":
                return state in _DOWNLOADING
            if wanted == "seeding":
                return state in _SEEDING
            if wanted == "paused":
                return state in _PAUSED
            if wanted == "errored":
                return state in _ERRORED
            if wanted == "active":
                return (t.get("dlspeed") or 0) > 0 or (t.get("upspeed") or 0) > 0 or state in ("downloading", "forcedDL", "metaDL")
            return True

        shown = [t for t in torrents if keep(t)]
        shown.sort(key=lambda t: ((t.get("dlspeed") or 0) + (t.get("upspeed") or 0)), reverse=True)
        info = self._json("/transfer/info") or {}
        return {
            "download_speed": info.get("dl_info_speed") or 0,
            "upload_speed": info.get("up_info_speed") or 0,
            "total": len(torrents),
            "matching": len(shown),
            "items": [
                {
                    "name": t.get("name") or "?",
                    "progress": round((t.get("progress") or 0) * 100, 1),
                    "state": t.get("state") or "",
                    "dlspeed": t.get("dlspeed") or 0,
                    "upspeed": t.get("upspeed") or 0,
                    "eta": t.get("eta") if (t.get("eta") or 0) < 8640000 else None,
                    "size": t.get("size") or 0,
                }
                for t in shown[:count]
            ],
        }

    def run_widget_action(self, action, widget):
        if action == "pause_all":
            paths = ("/torrents/pause", "/torrents/stop")  # v5 renamed pause -> stop
        elif action == "resume_all":
            paths = ("/torrents/resume", "/torrents/start")
        else:
            raise NotImplementedError(action)
        for path in paths:
            try:
                self._call(path, form={"hashes": "all"}, method="POST")
                return
            except http.HttpError as err:
                if err.status != 404:
                    raise
        raise http.HttpError(404, "no pause/resume endpoint")
