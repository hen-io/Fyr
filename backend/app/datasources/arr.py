import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from . import http
from .base import MetricSource


def _clamp(value, default, lo, hi):
    try:
        return min(hi, max(lo, int(value if value not in (None, "") else default)))
    except (TypeError, ValueError):
        return default


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ArrSource(MetricSource):
    """Shared code for Sonarr and Radarr - both speak the same v3 REST API
    with an X-Api-Key header. Subclasses add the app-specific metrics and
    normalise their calendar / queue records."""

    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "http://sonarr:8989"},
        {"name": "api_key", "label": "API-nøkkel", "kind": "password", "required": True},
    ]
    WIDGETS = ("arr_calendar", "arr_queue")
    API = "/api/v3"

    def __init__(self, url, api_key):
        super().__init__()
        self.url = (url or "").rstrip("/")
        self.api_key = api_key or ""

    @classmethod
    def from_values(cls, values, config):
        return cls(values.get("url"), values.get("api_key"))

    def is_configured(self):
        return bool(self.url and self.api_key)

    def _get(self, path, params=None):
        if not self.is_configured():
            raise RuntimeError(f"{self.label} is not configured")
        query = f"?{urlencode(params)}" if params else ""
        return http.get_json(http.join(self.url, f"{self.API}{path}{query}"), headers={"X-Api-Key": self.api_key})

    def check(self):
        if not self.is_configured():
            return {"connected": False, "detail": "URL/API-nøkkel mangler", "latency_ms": None}
        started = time.time()
        try:
            status = self._get("/system/status")
        except http.HttpError as err:
            return {"connected": False, "detail": "Ugyldig API-nøkkel" if err.status in (401, 403) else str(err), "latency_ms": None}
        except Exception as err:
            return {"connected": False, "detail": str(getattr(err, "reason", err))[:120], "latency_ms": None}
        return {
            "connected": True,
            "detail": f"{self.label} {(status or {}).get('version', '')}".strip(),
            "latency_ms": int((time.time() - started) * 1000),
        }

    # --- shared metrics -----------------------------------------------------

    def _common_metrics(self):
        metrics = {}
        queue = self._get("/queue", {"page": 1, "pageSize": 1})
        metrics["queue"] = ((queue or {}).get("totalRecords", 0), None, "I kø")
        missing = self._get("/wanted/missing", {"page": 1, "pageSize": 1})
        metrics["missing"] = ((missing or {}).get("totalRecords", 0), None, "Mangler")
        health = self._get("/health") or []
        metrics["health_issues"] = (len(health), None, "Helseproblemer")
        for i, disk in enumerate((self._get("/diskspace") or [])[:6]):
            total = disk.get("totalSpace") or 0
            free = disk.get("freeSpace") or 0
            label = disk.get("label") or disk.get("path") or f"disk {i + 1}"
            metrics[f"disk_free_{i + 1}"] = (round(free / 1e9, 1), "GB", f"Ledig plass {label}")
            if total:
                metrics[f"disk_used_{i + 1}"] = (round((total - free) / total * 100, 1), "%", f"Brukt plass {label}")
        return metrics

    def widget_data(self, widget_type, widget):
        if widget_type == "arr_calendar":
            return {"items": self.calendar(_clamp(widget.get("days"), 14, 1, 60), _clamp(widget.get("count"), 10, 1, 40))}
        if widget_type == "arr_queue":
            return {"items": self.queue(_clamp(widget.get("count"), 8, 1, 40))}
        raise NotImplementedError(widget_type)

    def calendar(self, days, count):
        raise NotImplementedError

    def queue(self, count):
        raise NotImplementedError

    @staticmethod
    def _queue_item(record, title, subtitle):
        size = record.get("size") or 0
        left = record.get("sizeleft") or 0
        progress = round((size - left) / size * 100, 1) if size else 0
        return {
            "title": title,
            "subtitle": subtitle,
            "progress": max(0, min(100, progress)),
            "status": record.get("status") or record.get("trackedDownloadState") or "",
            "timeleft": record.get("timeleft") or "",
            "protocol": record.get("protocol") or "",
        }


class SonarrSource(ArrSource):
    id = "sonarr"
    label = "Sonarr"
    icon = "television-classic"
    description = "TV-serier: kø, mangler, kommende episoder og diskplass."

    def fetch_metrics(self):
        metrics = self._common_metrics()
        series = self._get("/series") or []
        metrics["series"] = (len(series), None, "Serier")
        metrics["monitored"] = (sum(1 for s in series if s.get("monitored")), None, "Overvåkede serier")
        metrics["episodes"] = (sum((s.get("statistics") or {}).get("episodeFileCount", 0) for s in series), None, "Episoder")
        now = datetime.now(timezone.utc)
        upcoming = self._get("/calendar", {"start": _iso(now), "end": _iso(now + timedelta(days=7))}) or []
        metrics["upcoming_7d"] = (len(upcoming), None, "Kommende (7 dager)")
        return metrics

    def calendar(self, days, count):
        now = datetime.now(timezone.utc)
        records = self._get("/calendar", {"start": _iso(now), "end": _iso(now + timedelta(days=days)), "includeSeries": "true"}) or []
        items = []
        for r in records:
            when = r.get("airDateUtc") or r.get("airDate")
            if not when:
                continue
            series = (r.get("series") or {}).get("title") or r.get("title") or "?"
            code = f"S{int(r.get('seasonNumber') or 0):02d}E{int(r.get('episodeNumber') or 0):02d}"
            items.append({"title": series, "subtitle": f"{code} {r.get('title') or ''}".strip(), "date": when, "has_file": bool(r.get("hasFile"))})
        items.sort(key=lambda i: i["date"])
        return items[:count]

    def queue(self, count):
        data = self._get("/queue", {"page": 1, "pageSize": count, "includeSeries": "true", "includeEpisode": "true"}) or {}
        out = []
        for r in data.get("records", [])[:count]:
            ep = r.get("episode") or {}
            code = f"S{int(ep.get('seasonNumber') or 0):02d}E{int(ep.get('episodeNumber') or 0):02d}" if ep else ""
            title = (r.get("series") or {}).get("title") or r.get("title") or "?"
            out.append(self._queue_item(r, title, f"{code} {ep.get('title') or ''}".strip()))
        return out


class RadarrSource(ArrSource):
    id = "radarr"
    label = "Radarr"
    icon = "movie-open"
    description = "Filmer: kø, mangler, kommende utgivelser og diskplass."

    def fetch_metrics(self):
        metrics = self._common_metrics()
        movies = self._get("/movie") or []
        metrics["movies"] = (len(movies), None, "Filmer")
        metrics["monitored"] = (sum(1 for m in movies if m.get("monitored")), None, "Overvåkede filmer")
        metrics["downloaded"] = (sum(1 for m in movies if m.get("hasFile")), None, "Lastet ned")
        now = datetime.now(timezone.utc)
        upcoming = self._get("/calendar", {"start": _iso(now), "end": _iso(now + timedelta(days=30))}) or []
        metrics["upcoming_30d"] = (len(upcoming), None, "Kommende (30 dager)")
        return metrics

    def calendar(self, days, count):
        now = datetime.now(timezone.utc)
        records = self._get("/calendar", {"start": _iso(now), "end": _iso(now + timedelta(days=days))}) or []
        items = []
        for r in records:
            when = r.get("digitalRelease") or r.get("physicalRelease") or r.get("inCinemas")
            if not when:
                continue
            kind = "digital" if r.get("digitalRelease") else "fysisk" if r.get("physicalRelease") else "kino"
            year = f" ({r['year']})" if r.get("year") else ""
            items.append({"title": f"{r.get('title') or '?'}{year}", "subtitle": kind, "date": when, "has_file": bool(r.get("hasFile"))})
        items.sort(key=lambda i: i["date"])
        return items[:count]

    def queue(self, count):
        data = self._get("/queue", {"page": 1, "pageSize": count, "includeMovie": "true"}) or {}
        out = []
        for r in data.get("records", [])[:count]:
            movie = r.get("movie") or {}
            out.append(self._queue_item(r, movie.get("title") or r.get("title") or "?", str(movie.get("year") or "")))
        return out
