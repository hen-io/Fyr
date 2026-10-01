from .base import RestSource, clamp_int, list_item


def _clock(ticks):
    """Jellyfin counts time in ticks of 100 ns."""
    seconds = int((ticks or 0) / 10_000_000)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class JellyfinSource(RestSource):
    """Jellyfin (and Emby, which shares this part of the API): library sizes
    and who is watching what right now."""

    id = "jellyfin"
    category = "media"
    label = "Jellyfin"
    icon = "play-box-multiple"
    description = "Mediebibliotek: antall filmer/serier/episoder og hva som spilles nå."
    METRICS_TTL = 10
    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "http://jellyfin:8096"},
        {"name": "api_key", "label": "API-nøkkel", "kind": "password", "required": True},
        RestSource.VERIFY_FIELD,
    ]
    WIDGETS = ("media_sessions",)

    def headers(self):
        return {"X-Emby-Token": self.values.get("api_key") or ""}

    def probe(self):
        info = self.get("/System/Info") or {}
        return f"{self.label} {info.get('Version', '')}".strip()

    def _sessions(self):
        return [s for s in (self.get("/Sessions") or []) if isinstance(s, dict)]

    def fetch_metrics(self):
        counts = self.get("/Items/Counts") or {}
        sessions = self._sessions()
        playing = [s for s in sessions if s.get("NowPlayingItem")]
        return {
            "movies": (counts.get("MovieCount", 0), None, "Filmer"),
            "series": (counts.get("SeriesCount", 0), None, "Serier"),
            "episodes": (counts.get("EpisodeCount", 0), None, "Episoder"),
            "songs": (counts.get("SongCount", 0), None, "Sanger"),
            "albums": (counts.get("AlbumCount", 0), None, "Album"),
            "sessions": (len(sessions), None, "Tilkoblede enheter"),
            "playing": (len(playing), None, "Spiller nå"),
            "transcoding": (sum(1 for s in playing if (s.get("PlayState") or {}).get("PlayMethod") == "Transcode"), None, "Transkoder"),
        }

    def widget_data(self, widget_type, widget):
        if widget_type != "media_sessions":
            raise NotImplementedError(widget_type)
        count = clamp_int(widget.get("count"), 6, 1, 30)
        items = []
        for session in self._sessions():
            item = session.get("NowPlayingItem")
            if not item:
                continue
            state = session.get("PlayState") or {}
            title = item.get("Name") or "?"
            if item.get("SeriesName"):
                code = f"S{int(item.get('ParentIndexNumber') or 0):02d}E{int(item.get('IndexNumber') or 0):02d}"
                title = f"{item['SeriesName']} · {code} {title}"
            elif item.get("ProductionYear"):
                title = f"{title} ({item['ProductionYear']})"
            runtime = item.get("RunTimeTicks") or 0
            position = state.get("PositionTicks") or 0
            who = " · ".join(x for x in (session.get("UserName"), session.get("DeviceName")) if x)
            items.append(
                list_item(
                    title,
                    subtitle=who,
                    value=f"{_clock(position)} / {_clock(runtime)}" if runtime else None,
                    level="off" if state.get("IsPaused") else "run",
                    progress=round(position / runtime * 100, 1) if runtime else None,
                    icon="pause" if state.get("IsPaused") else "play",
                )
                | {"transcoding": state.get("PlayMethod") == "Transcode"}
            )
        return {"items": items[:count]}


class ImmichSource(RestSource):
    """Immich: how many photos and videos, and how full the disk is. Needs an
    API key from an admin account."""

    id = "immich"
    category = "media"
    label = "Immich"
    icon = "image-multiple"
    description = "Bildearkiv: antall bilder og videoer, lagringsbruk og diskplass."
    METRICS_TTL = 60
    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "http://immich:2283"},
        {"name": "api_key", "label": "API-nøkkel (admin)", "kind": "password", "required": True},
        RestSource.VERIFY_FIELD,
    ]

    def headers(self):
        return {"x-api-key": self.values.get("api_key") or "", "Accept": "application/json"}

    def _server(self, name):
        """Newer servers answer under /api/server/..., older under /api/server-info/..."""
        from . import http

        try:
            return self.get(f"/api/server/{name}") or {}
        except http.HttpError as err:
            if err.status != 404:
                raise
            return self.get(f"/api/server-info/{name}") or {}

    def probe(self):
        return f"Immich {self._server('about').get('version', '')}".strip()

    def fetch_metrics(self):
        stats = self._server("statistics")
        metrics = {
            "photos": (stats.get("photos", 0), None, "Bilder"),
            "videos": (stats.get("videos", 0), None, "Videoer"),
            "usage_gb": (round((stats.get("usage") or 0) / 1e9, 1), "GB", "Lagring brukt av biblioteket"),
            "users": (len(stats.get("usageByUser") or []), None, "Brukere"),
        }
        try:
            storage = self._server("storage")
        except Exception:
            storage = {}
        if storage.get("diskSizeRaw"):
            metrics["disk_percent"] = (round(float(storage.get("diskUsagePercentage") or 0), 1), "%", "Disk brukt")
            metrics["disk_free_gb"] = (round((storage.get("diskAvailableRaw") or 0) / 1e9, 1), "GB", "Ledig plass")
        return metrics


class SeerrSource(RestSource):
    """Jellyseerr / Overseerr: how many requests are waiting, being fetched
    and done."""

    id = "seerr"
    category = "media"
    label = "Jellyseerr / Overseerr"
    icon = "movie-search"
    description = "Medieønsker: ventende, godkjente, under behandling og tilgjengelige."
    METRICS_TTL = 30
    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "http://jellyseerr:5055"},
        {"name": "api_key", "label": "API-nøkkel", "kind": "password", "required": True},
        RestSource.VERIFY_FIELD,
    ]

    def headers(self):
        return {"X-Api-Key": self.values.get("api_key") or ""}

    def probe(self):
        version = (self.get("/api/v1/status") or {}).get("version", "")
        self.get("/api/v1/request/count")  # the status page is public; this proves the key works
        return f"{self.label} {version}".strip()

    def fetch_metrics(self):
        counts = self.get("/api/v1/request/count") or {}
        names = {
            "pending": "Venter på godkjenning",
            "approved": "Godkjent",
            "processing": "Under behandling",
            "available": "Tilgjengelig",
            "declined": "Avslått",
            "total": "Ønsker totalt",
            "movie": "Filmønsker",
            "tv": "Serieønsker",
        }
        return {key: (counts.get(key, 0), None, name) for key, name in names.items()}
