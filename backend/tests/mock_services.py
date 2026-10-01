"""Stand-ins for the services Fyr integrates with, for tests and for trying
widgets out without the real thing. One small HTTP server; every service lives
under its own path prefix and answers with the shapes the real API uses.

    python tests/mock_services.py [port]        (default 9500)

then point an integration at  http://127.0.0.1:9500/<prefix>:
    ha  sonarr  radarr  qbit  backrest  jellyfin  immich  adguard  seerr
    prowlarr  frigate  proxmox  kuma           and  /rss/feed.xml, /rss/atom.xml
Any API key / token / password is accepted, except the literal "wrong".
"""

import base64
import json
import math
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

START = time.time()
_state = {"light.stue": "on", "switch.kaffe": "off", "light.kjokken": "off", "qbit_paused": False}


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _basic_password(handler):
    """The password of an HTTP Basic Authorization header, or None."""
    value = handler.headers.get("Authorization", "")
    if not value.startswith("Basic "):
        return None
    try:
        return base64.b64decode(value[6:]).decode("utf-8").split(":", 1)[1]
    except (ValueError, IndexError):
        return None


def _wave(period, low, high, phase=0.0, at=None):
    t = (time.time() if at is None else at) / period * 2 * math.pi + phase
    return low + (high - low) * (0.5 + 0.5 * math.sin(t))


# --- Home Assistant -------------------------------------------------------------


def _ha_entities(at=None):
    def sensor(entity, name, value, unit):
        return {"entity_id": entity, "state": str(value), "attributes": {"friendly_name": name, "unit_of_measurement": unit}, "last_changed": _iso(_now())}

    return [
        sensor("sensor.stue_temperatur", "Stue temperatur", round(_wave(3600, 20.2, 23.4, at=at), 1), "°C"),
        sensor("sensor.ute_temperatur", "Ute temperatur", round(_wave(5400, -2.0, 9.5, 1.0, at=at), 1), "°C"),
        sensor("sensor.effekt", "Strømforbruk", round(_wave(900, 480, 3900, 2.0, at=at)), "W"),
        sensor("sensor.luftfuktighet", "Luftfuktighet", round(_wave(4000, 34, 58, 0.5, at=at)), "%"),
        sensor("sensor.disk_bruk", "Disk brukt", 71.5, "%"),
        sensor("sensor.batteri_telefon", "Telefon batteri", 18, "%"),
        {"entity_id": "sensor.status", "state": "Alt i orden", "attributes": {"friendly_name": "Status"}},
        {"entity_id": "light.stue", "state": _state["light.stue"], "attributes": {"friendly_name": "Stuelys", "brightness": 180}},
        {"entity_id": "light.kjokken", "state": _state["light.kjokken"], "attributes": {"friendly_name": "Kjøkkenlys"}},
        {"entity_id": "switch.kaffe", "state": _state["switch.kaffe"], "attributes": {"friendly_name": "Kaffetrakter"}},
        {"entity_id": "input_select.hjem_modus", "state": "Hjemme", "attributes": {"friendly_name": "Hjem-modus"}},
        {
            "entity_id": "weather.home",
            "state": "partlycloudy",
            "attributes": {
                "friendly_name": "Hjemme",
                "temperature": 12.3,
                "temperature_unit": "°C",
                "apparent_temperature": 10.1,
                "humidity": 64,
                "wind_speed": 4.2,
                "wind_speed_unit": "m/s",
                "pressure": 1012,
                "pressure_unit": "hPa",
            },
        },
        {"entity_id": "calendar.familie", "state": "off", "attributes": {"friendly_name": "Familie"}},
        {"entity_id": "calendar.jobb", "state": "off", "attributes": {"friendly_name": "Jobb"}},
    ]


def _ha(handler, path, query, body):
    if handler.headers.get("Authorization", "") == "Bearer wrong":
        return 401, {"message": "Unauthorized"}
    if path == "/api/config":
        return 200, {"version": "2026.9.2", "location_name": "Hjemme"}
    if path == "/api/states":
        return 200, _ha_entities()
    if path.startswith("/api/states/"):
        wanted = path[len("/api/states/") :]
        found = next((e for e in _ha_entities() if e["entity_id"] == wanted), None)
        return (200, found) if found else (404, {"message": "Entity not found."})
    if path.startswith("/api/history/period/"):
        entity = (query.get("filter_entity_id") or [""])[0]
        start = datetime.fromisoformat(path[len("/api/history/period/") :].replace("Z", "+00:00")).timestamp()
        end = time.time()
        points = []
        steps = 120
        for i in range(steps + 1):
            at = start + (end - start) * i / steps
            state = next((e["state"] for e in _ha_entities(at) if e["entity_id"] == entity), None)
            if state is None:
                return 200, []
            points.append({"state": state, "last_changed": _iso(datetime.fromtimestamp(at, timezone.utc))})
        return 200, [points]
    if path.startswith("/api/calendars/"):
        today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        entity = path.rsplit("/", 1)[1]
        if entity == "calendar.jobb":
            return 200, [{"summary": "Ukesmøte", "start": {"dateTime": _iso(today + timedelta(days=1, hours=8))}, "end": {"dateTime": _iso(today + timedelta(days=1, hours=9))}}]
        return 200, [
            {"summary": "Høstferie", "start": {"date": (today - timedelta(days=2)).strftime("%Y-%m-%d")}, "end": {"date": (today + timedelta(days=3)).strftime("%Y-%m-%d")}},
            {"summary": "Middag hos bestemor", "start": {"dateTime": _iso(today + timedelta(hours=17))}, "end": {"dateTime": _iso(today + timedelta(hours=19))}},
            {"summary": "Fotballtrening", "start": {"dateTime": _iso(today + timedelta(days=1, hours=16, minutes=30))}, "end": {"dateTime": _iso(today + timedelta(days=1, hours=18))}},
            {"summary": "Bursdag: Ola", "start": {"date": (today + timedelta(days=4)).strftime("%Y-%m-%d")}, "end": {"date": (today + timedelta(days=5)).strftime("%Y-%m-%d")}},
        ]
    if path == "/api/services/weather/get_forecasts":
        # Like Home Assistant since 2024.4: the forecast is only available from this service.
        if "return_response" not in query:
            return 400, {"message": "Service call requires responses but caller did not ask for responses."}
        forecast = [
            {"datetime": _iso(_now() + timedelta(days=i)), "condition": c, "temperature": t, "templow": t - 6, "precipitation": p}
            for i, (c, t, p) in enumerate([("partlycloudy", 14, 0), ("rainy", 11, 6.4), ("sunny", 16, 0), ("cloudy", 12, 0.2), ("snowy", 2, 3.1)], start=1)
        ]
        return 200, {"changed_states": [], "service_response": {(body or {}).get("entity_id"): {"forecast": forecast}}}
    if path.startswith("/api/services/"):
        entity = (body or {}).get("entity_id")
        if entity in _state:
            _state[entity] = "off" if _state[entity] == "on" else "on"
        return 200, []
    return 404, {"message": "not found"}


# --- Sonarr / Radarr ------------------------------------------------------------


def _arr(kind):
    def handle(handler, path, query, body):
        if handler.headers.get("X-Api-Key") in (None, "", "wrong"):
            return 401, {"error": "Unauthorized"}
        path = path[len("/api/v3") :] if path.startswith("/api/v3") else path
        now = _now()
        if path == "/system/status":
            return 200, {"version": "4.0.9.2244" if kind == "sonarr" else "5.11.0.9244", "appName": kind.title()}
        if path == "/health":
            return 200, [{"type": "warning", "message": "Indexer unavailable"}]
        if path == "/diskspace":
            return 200, [{"path": "/data", "label": "data", "freeSpace": 812e9, "totalSpace": 4000e9}, {"path": "/", "label": "", "freeSpace": 31e9, "totalSpace": 120e9}]
        if path == "/wanted/missing":
            return 200, {"page": 1, "pageSize": 1, "totalRecords": 7, "records": []}
        if kind == "sonarr":
            if path == "/series":
                return 200, [{"title": f"Serie {i}", "monitored": i % 3 != 0, "statistics": {"episodeFileCount": 10 + i}} for i in range(24)]
            if path == "/calendar":
                shows = [("Severance", 2, 4, "Attila"), ("Slow Horses", 5, 1, "Bad Dates"), ("The Bear", 4, 3, "Sundae"), ("Foundation", 3, 7, "Foundation's End")]
                return 200, [
                    {"seriesId": i, "title": title, "seasonNumber": s, "episodeNumber": e, "airDateUtc": _iso(now + timedelta(days=i, hours=3 * i + 2)), "hasFile": False, "series": {"title": show}}
                    for i, (show, s, e, title) in enumerate(shows)
                ]
            if path == "/queue":
                records = [
                    {"title": "Severance.S02E04.2160p", "size": 6.2e9, "sizeleft": 1.4e9, "status": "downloading", "timeleft": "00:12:40", "protocol": "torrent", "series": {"title": "Severance"}, "episode": {"seasonNumber": 2, "episodeNumber": 4, "title": "Attila"}},
                    {"title": "Slow.Horses.S05E01.1080p", "size": 2.1e9, "sizeleft": 2.0e9, "status": "queued", "timeleft": "", "protocol": "usenet", "series": {"title": "Slow Horses"}, "episode": {"seasonNumber": 5, "episodeNumber": 1, "title": "Bad Dates"}},
                ]
                return 200, {"page": 1, "totalRecords": len(records), "records": records}
        else:
            if path == "/movie":
                return 200, [{"title": f"Film {i}", "monitored": True, "hasFile": i % 4 != 0} for i in range(140)]
            if path == "/calendar":
                return 200, [
                    {"title": "Dune: Part Three", "year": 2026, "inCinemas": _iso(now + timedelta(days=9)), "hasFile": False},
                    {"title": "The Brutalist", "year": 2025, "digitalRelease": _iso(now + timedelta(days=2)), "hasFile": False},
                    {"title": "Mickey 17", "year": 2025, "physicalRelease": _iso(now + timedelta(days=20)), "hasFile": True},
                ]
            if path == "/queue":
                records = [{"title": "The.Brutalist.2025.2160p", "size": 24e9, "sizeleft": 9e9, "status": "downloading", "timeleft": "01:04:10", "protocol": "torrent", "movie": {"title": "The Brutalist", "year": 2025}}]
                return 200, {"page": 1, "totalRecords": 1, "records": records}
        return 404, {"error": "not found"}

    return handle


# --- qBittorrent ----------------------------------------------------------------


def _qbit(handler, path, query, body):
    path = path[len("/api/v2") :] if path.startswith("/api/v2") else path
    if path == "/auth/login":
        ok = (body or {}).get("password") != "wrong"
        return 200, ("Ok." if ok else "Fails."), {"Set-Cookie": "SID=mock-session; HttpOnly; path=/"} if ok else {}
    if path == "/app/version":
        return 200, "v5.0.3"
    paused = _state["qbit_paused"]
    torrents = [
        {"name": "ubuntu-26.04-desktop-amd64.iso", "progress": 0.62, "state": "pausedDL" if paused else "downloading", "dlspeed": 0 if paused else 8.4e6, "upspeed": 1.1e5, "eta": 540, "size": 5.9e9},
        {"name": "debian-13.1.0-amd64-netinst.iso", "progress": 1.0, "state": "pausedUP" if paused else "uploading", "dlspeed": 0, "upspeed": 0 if paused else 6.2e5, "eta": 8640000, "size": 6.6e8},
        {"name": "archlinux-2026.09.01-x86_64.iso", "progress": 0.18, "state": "pausedDL" if paused else "downloading", "dlspeed": 0 if paused else 2.3e6, "upspeed": 0, "eta": 2400, "size": 1.3e9},
        {"name": "Fedora-Workstation-Live-44.iso", "progress": 1.0, "state": "stalledUP", "dlspeed": 0, "upspeed": 0, "eta": 8640000, "size": 2.4e9},
    ]
    if path == "/transfer/info":
        return 200, {"dl_info_speed": sum(t["dlspeed"] for t in torrents), "up_info_speed": sum(t["upspeed"] for t in torrents), "dl_info_data": 48.2e9, "up_info_data": 112.9e9}
    if path == "/torrents/info":
        return 200, torrents
    if path == "/sync/maindata":
        return 200, {"server_state": {"free_space_on_disk": 812e9, "global_ratio": "2.34"}}
    if path in ("/torrents/stop", "/torrents/pause"):
        _state["qbit_paused"] = True
        return 200, ""
    if path in ("/torrents/start", "/torrents/resume"):
        _state["qbit_paused"] = False
        return 200, ""
    return 404, ""


# --- Backrest -------------------------------------------------------------------


def _backrest(handler, path, query, body):
    now_ms = int(time.time() * 1000)
    if path.endswith("/GetSummaryDashboard"):
        return 200, {
            "repoSummaries": [{"id": "nas", "protectedBytes": str(int(1.8e12)), "totalSnapshots": "412"}],
            "planSummaries": [
                {"id": "dokumenter", "backupsSuccessLast30days": "30", "backupsWarningLast30days": "0", "backupsFailed30days": "0", "totalSnapshots": "210", "nextBackupTimeMs": str(now_ms + 3 * 3600 * 1000), "bytesAddedLast30days": str(int(4.2e9))},
                {"id": "bilder", "backupsSuccessLast30days": "27", "backupsWarningLast30days": "2", "backupsFailed30days": "1", "totalSnapshots": "202", "nextBackupTimeMs": str(now_ms + 9 * 3600 * 1000), "bytesAddedLast30days": str(int(61e9))},
            ],
        }
    if path.endswith("/GetOperations"):
        return 200, {
            "operations": [
                {"planId": "dokumenter", "status": "STATUS_SUCCESS", "unixTimeStartMs": str(now_ms - 2 * 3600 * 1000), "operationBackup": {}},
                {"planId": "bilder", "status": "STATUS_ERROR", "unixTimeStartMs": str(now_ms - 5 * 3600 * 1000), "displayMessage": "repository locked", "operationBackup": {}},
                {"planId": "bilder", "status": "STATUS_INPROGRESS", "unixTimeStartMs": str(now_ms - 600 * 1000), "operationPrune": {}},
            ]
        }
    return 404, {"code": "not_found"}


# --- Jellyfin -------------------------------------------------------------------


def _jellyfin(handler, path, query, body):
    token = handler.headers.get("X-Emby-Token") or ""
    if "wrong" in token or "wrong" in handler.headers.get("Authorization", ""):
        return 401, ""
    if path == "/System/Info":
        return 200, {"Version": "10.10.7", "ServerName": "knetflix"}
    if path == "/Items/Counts":
        return 200, {"MovieCount": 412, "SeriesCount": 58, "EpisodeCount": 2144, "ArtistCount": 0, "SongCount": 5120, "AlbumCount": 388, "BookCount": 12}
    if path == "/Sessions":
        return 200, [
            {
                "UserName": "henrik",
                "Client": "Jellyfin Web",
                "DeviceName": "Firefox",
                "NowPlayingItem": {"Name": "Attila", "SeriesName": "Severance", "ParentIndexNumber": 2, "IndexNumber": 4, "Type": "Episode", "RunTimeTicks": 31_200_000_000},
                "PlayState": {"IsPaused": False, "PositionTicks": 12_480_000_000, "PlayMethod": "DirectPlay"},
            },
            {
                "UserName": "kari",
                "Client": "Android TV",
                "DeviceName": "Stue-TV",
                "NowPlayingItem": {"Name": "Dune: Part Two", "Type": "Movie", "ProductionYear": 2024, "RunTimeTicks": 99_600_000_000},
                "PlayState": {"IsPaused": True, "PositionTicks": 66_000_000_000, "PlayMethod": "Transcode"},
            },
            {"UserName": "ola", "Client": "Jellyfin iOS", "DeviceName": "iPhone", "PlayState": {}},
        ]
    return 404, ""


# --- Immich ---------------------------------------------------------------------


def _immich(handler, path, query, body):
    if handler.headers.get("x-api-key") in (None, "", "wrong"):
        return 401, {"message": "Invalid API key"}
    if path in ("/api/server/about", "/api/server-info/about"):
        return 200, {"version": "v1.142.1"}
    if path in ("/api/server/statistics", "/api/server-info/statistics"):
        return 200, {"photos": 48213, "videos": 3120, "usage": 412_000_000_000, "usageByUser": [{"userName": "henrik", "photos": 30000, "videos": 2000, "usage": 280_000_000_000}]}
    if path in ("/api/server/storage", "/api/server-info/storage"):
        return 200, {"diskSizeRaw": 4_000_000_000_000, "diskUseRaw": 2_920_000_000_000, "diskAvailableRaw": 1_080_000_000_000, "diskUsagePercentage": 73.0}
    return 404, {"message": "not found"}


# --- AdGuard Home ---------------------------------------------------------------


def _adguard(handler, path, query, body):
    if _basic_password(handler) == "wrong":
        return 401, ""
    if path == "/control/status":
        return 200, {"version": "v0.107.63", "running": True, "protection_enabled": True, "dns_port": 53}
    if path == "/control/stats":
        return 200, {"num_dns_queries": 148_230, "num_blocked_filtering": 21_944, "num_replaced_safebrowsing": 12, "num_replaced_parental": 0, "avg_processing_time": 0.0183, "time_units": "hours"}
    return 404, ""


# --- Jellyseerr / Overseerr -----------------------------------------------------


def _seerr(handler, path, query, body):
    if handler.headers.get("X-Api-Key") in (None, "", "wrong"):
        return 403, {"message": "forbidden"}
    if path == "/api/v1/status":
        return 200, {"version": "2.7.3"}
    if path == "/api/v1/request/count":
        return 200, {"total": 214, "movie": 131, "tv": 83, "pending": 3, "approved": 9, "declined": 4, "processing": 6, "available": 192}
    return 404, {"message": "not found"}


# --- Prowlarr -------------------------------------------------------------------


def _prowlarr(handler, path, query, body):
    if handler.headers.get("X-Api-Key") in (None, "", "wrong"):
        return 401, {"error": "Unauthorized"}
    if path == "/api/v1/system/status":
        return 200, {"version": "1.37.0.5076"}
    if path == "/api/v1/health":
        return 200, []
    if path == "/api/v1/indexer":
        return 200, [{"id": i, "name": f"Indexer {i}", "enable": i != 3} for i in range(1, 9)]
    if path == "/api/v1/indexerstats":
        return 200, {"indexers": [{"indexerId": i, "numberOfQueries": 400 + 37 * i, "numberOfGrabs": 20 + i, "numberOfFailedQueries": i % 3} for i in range(1, 9)]}
    return 404, {"error": "not found"}


# --- Frigate --------------------------------------------------------------------


def _frigate(handler, path, query, body):
    if path == "/api/version":
        return 200, "0.16.1-abc1234"
    if path == "/api/stats":
        return 200, {
            "cameras": {
                "inngang": {"camera_fps": 5.0, "process_fps": 5.0, "detection_fps": 0.4, "detection_enabled": True},
                "garasje": {"camera_fps": 5.1, "process_fps": 5.0, "detection_fps": 0.0, "detection_enabled": True},
                "hage": {"camera_fps": 0.0, "process_fps": 0.0, "detection_fps": 0.0, "detection_enabled": True},
            },
            "detectors": {"coral": {"inference_speed": 8.6, "detection_start": 0.0, "pid": 311}},
            "service": {"uptime": 512_340, "version": "0.16.1-abc1234", "storage": {"/media/frigate/recordings": {"total": 1_900_000.0, "used": 1_240_000.0, "free": 660_000.0}}},
            "cpu_usages": {"frigate.full_system": {"cpu": "14.2", "mem": "31.0"}},
        }
    if path == "/api/events":
        now = time.time()
        return 200, [
            {"id": "e1", "camera": "inngang", "label": "person", "start_time": now - 420, "end_time": now - 380, "top_score": 0.91},
            {"id": "e2", "camera": "garasje", "label": "car", "start_time": now - 3100, "end_time": now - 3050, "top_score": 0.84},
            {"id": "e3", "camera": "inngang", "label": "cat", "start_time": now - 9200, "end_time": now - 9150, "top_score": 0.77},
        ]
    return 404, ""


# --- Proxmox VE -----------------------------------------------------------------


def _proxmox(handler, path, query, body):
    if "wrong" in handler.headers.get("Authorization", "") or not handler.headers.get("Authorization", "").startswith("PVEAPIToken="):
        return 401, {"data": None}
    if path == "/api2/json/version":
        return 200, {"data": {"version": "8.4.1", "release": "8.4"}}
    if path == "/api2/json/cluster/resources":
        gb = 1024**3
        return 200, {
            "data": [
                {"type": "node", "node": "pve1", "status": "online", "cpu": 0.21, "maxcpu": 16, "mem": 41 * gb, "maxmem": 64 * gb, "uptime": 2_400_000},
                {"type": "node", "node": "pve2", "status": "online", "cpu": 0.07, "maxcpu": 8, "mem": 9 * gb, "maxmem": 32 * gb, "uptime": 1_100_000},
                {"type": "qemu", "vmid": 100, "name": "homeassistant", "status": "running", "node": "pve1", "cpu": 0.04, "mem": 3 * gb, "maxmem": 4 * gb},
                {"type": "qemu", "vmid": 101, "name": "windows", "status": "stopped", "node": "pve1", "cpu": 0, "mem": 0, "maxmem": 8 * gb},
                {"type": "lxc", "vmid": 200, "name": "docker", "status": "running", "node": "pve1", "cpu": 0.11, "mem": 12 * gb, "maxmem": 24 * gb},
                {"type": "lxc", "vmid": 201, "name": "pihole", "status": "running", "node": "pve2", "cpu": 0.01, "mem": gb // 4, "maxmem": gb},
                {"type": "storage", "storage": "local-zfs", "node": "pve1", "status": "available", "disk": 380 * gb, "maxdisk": 900 * gb},
            ]
        }
    return 404, {"data": None}


# --- Uptime Kuma ----------------------------------------------------------------

_KUMA = """# HELP monitor_status Monitor Status (1 = UP, 0= DOWN, 2= PENDING, 3= MAINTENANCE)
# TYPE monitor_status gauge
monitor_status{monitor_name="Home Assistant",monitor_type="http",monitor_url="http://ha.lan",monitor_hostname="null",monitor_port="null"} 1
monitor_status{monitor_name="Immich",monitor_type="http",monitor_url="http://immich.lan",monitor_hostname="null",monitor_port="null"} 1
monitor_status{monitor_name="NAS",monitor_type="ping",monitor_url="null",monitor_hostname="nas.lan",monitor_port="null"} 0
monitor_status{monitor_name="Router",monitor_type="ping",monitor_url="null",monitor_hostname="192.168.1.1",monitor_port="null"} 1
monitor_status{monitor_name="Backup-server",monitor_type="port",monitor_url="null",monitor_hostname="bk.lan",monitor_port="22"} 3
# HELP monitor_response_time Monitor Response Time (ms)
# TYPE monitor_response_time gauge
monitor_response_time{monitor_name="Home Assistant",monitor_type="http",monitor_url="http://ha.lan",monitor_hostname="null",monitor_port="null"} 41
monitor_response_time{monitor_name="Immich",monitor_type="http",monitor_url="http://immich.lan",monitor_hostname="null",monitor_port="null"} 118
monitor_response_time{monitor_name="NAS",monitor_type="ping",monitor_url="null",monitor_hostname="nas.lan",monitor_port="null"} -1
monitor_response_time{monitor_name="Router",monitor_type="ping",monitor_url="null",monitor_hostname="192.168.1.1",monitor_port="null"} 2
"""


def _kuma(handler, path, query, body):
    if path == "/metrics":
        if _basic_password(handler) == "wrong":
            return 401, ""
        return 200, _KUMA
    return 404, ""


# --- feeds ----------------------------------------------------------------------


def _rss(handler, path, query, body):
    now = _now()
    if path == "/feed.xml":
        items = "".join(
            f"<item><title>{title}</title><link>https://example.test/nyhet/{i}</link><pubDate>{(now - timedelta(hours=3 * i + 1)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate><description>Kort ingress for sak {i}.</description></item>"
            for i, title in enumerate(["Ny versjon av Home Assistant er ute", "Slik sikrer du hjemmeserveren", "Test: fem NAS-er for hjemmebruk", "Strømprisen faller i helgen", "Open source-prosjekt får støtte &amp; nytt navn"])
        )
        return 200, f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Teknologinytt</title><link>https://example.test</link>{items}</channel></rss>', {"Content-Type": "application/rss+xml; charset=utf-8"}
    if path == "/atom.xml":
        entries = "".join(
            f'<entry><title>{title}</title><link rel="alternate" href="https://blog.example.test/{i}"/><updated>{(now - timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}</updated></entry>'
            for i, title in enumerate(["Release notes 3.2", "A look at the new dashboard", "Migrating to containers"])
        )
        return 200, f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Prosjektbloggen</title>{entries}</feed>', {"Content-Type": "application/atom+xml; charset=utf-8"}
    if path == "/bomb.xml":
        return 200, '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]><rss><channel><item><title>&lol2;</title></item></channel></rss>', {"Content-Type": "application/xml"}
    if path == "/redirect":
        return 302, "", {"Location": "/rss/feed.xml"}
    return 404, ""


SERVICES = {
    "ha": _ha,
    "sonarr": _arr("sonarr"),
    "radarr": _arr("radarr"),
    "qbit": _qbit,
    "backrest": _backrest,
    "jellyfin": _jellyfin,
    "immich": _immich,
    "adguard": _adguard,
    "seerr": _seerr,
    "prowlarr": _prowlarr,
    "frigate": _frigate,
    "proxmox": _proxmox,
    "kuma": _kuma,
    "rss": _rss,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet
        pass

    def _serve(self):
        parsed = urlparse(self.path)
        parts = unquote(parsed.path).lstrip("/").split("/", 1)
        service = SERVICES.get(parts[0])
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body = None
        if raw:
            if "json" in (self.headers.get("Content-Type") or ""):
                try:
                    body = json.loads(raw.decode("utf-8"))
                except ValueError:
                    body = None
            else:
                body = {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
        if service is None:
            result = (404, {"error": "unknown service"})
        else:
            result = service(self, "/" + (parts[1] if len(parts) > 1 else ""), parse_qs(parsed.query, keep_blank_values=True), body)
        status, payload = result[0], result[1]
        headers = result[2] if len(result) > 2 else {}
        if isinstance(payload, (dict, list)):
            data = json.dumps(payload).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        else:
            data = str(payload).encode("utf-8")
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = _serve


def start(port=0):
    """Starts the mock server on a background thread; returns (server, base_url)."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9500
    _server, base = start(port)
    print(f"mock services on {base}/<{'|'.join(SERVICES)}>", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
