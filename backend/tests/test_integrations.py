"""Every integration, talking real HTTP to the stand-in services in
mock_services.py (which answer with the shapes the real APIs use)."""

import pytest

import mock_services
from app.datasources.arr import RadarrSource, SonarrSource
from app.datasources.backrest import BackrestSource
from app.datasources.home_assistant import HomeAssistantSource
from app.datasources.infra import AdGuardSource, FrigateSource, ProwlarrSource, ProxmoxSource, UptimeKumaSource
from app.datasources.media import ImmichSource, JellyfinSource, SeerrSource
from app.datasources.qbittorrent import QBittorrentSource
from app.datasources.registry import CATALOG, INTEGRATION_WIDGETS
from app.datasources.system import SystemSource
from app.routes.feeds import parse_feed


@pytest.fixture(scope="module")
def base():
    server, url = mock_services.start()
    yield url
    server.shutdown()


def _source(cls, base, prefix, **values):
    return cls.from_values({"url": f"{base}/{prefix}", **values}, {"WEATHER_CACHE_TTL": 300})


CASES = [
    (SonarrSource, "sonarr", {"api_key": "k"}, {"queue": 2, "missing": 7, "series": 24, "health_issues": 1, "upcoming_7d": 4}),
    (RadarrSource, "radarr", {"api_key": "k"}, {"queue": 1, "movies": 140, "downloaded": 105}),
    (ProwlarrSource, "prowlarr", {"api_key": "k"}, {"indexers": 8, "indexers_enabled": 7, "health_issues": 0}),
    (QBittorrentSource, "qbit", {"username": "u", "password": "p"}, {"total": 4, "ratio": 2.34, "free_space": 812.0}),
    (JellyfinSource, "jellyfin", {"api_key": "k"}, {"movies": 412, "series": 58, "sessions": 3, "playing": 2, "transcoding": 1}),
    (SeerrSource, "seerr", {"api_key": "k"}, {"pending": 3, "total": 214, "available": 192}),
    (ImmichSource, "immich", {"api_key": "k"}, {"photos": 48213, "videos": 3120, "usage_gb": 412.0, "disk_percent": 73.0}),
    (FrigateSource, "frigate", {}, {"cameras": 3, "cameras_online": 2, "inference_ms": 8.6, "storage_percent": 65.3, "cpu_percent": 14.2}),
    (AdGuardSource, "adguard", {"username": "admin", "password": "p"}, {"queries": 148230, "blocked": 21944, "blocked_percent": 14.8, "avg_ms": 18.3, "protection": 1}),
    (UptimeKumaSource, "kuma", {"api_key": "k"}, {"up": 3, "down": 1, "maintenance": 1, "total": 5}),
    (ProxmoxSource, "proxmox", {"token_id": "fyr@pve!dash", "token_secret": "s"}, {"nodes": 2, "nodes_online": 2, "vms": 2, "vms_running": 1, "containers_running": 2}),
    (BackrestSource, "backrest", {}, {"plans": 2, "backups_failed": 1, "snapshots": 412}),
]


@pytest.mark.parametrize("cls,prefix,values,expected", CASES, ids=[c[0].id for c in CASES])
def test_integration_connects_and_reads(base, cls, prefix, values, expected):
    source = _source(cls, base, prefix, **values)
    assert source.is_configured()
    status = source.check()
    assert status["connected"], status
    metrics = source.fetch_metrics()
    for key, value in expected.items():
        assert metrics[key][0] == value, (key, metrics[key])
    # every metric reads like a Home Assistant entity, so any data widget can show it
    key = next(iter(metrics))
    read = source.get_value(key)
    assert read["state"] == str(metrics[key][0]) and read["attributes"]["friendly_name"]
    assert {k["key"] for k in source.list_keys()} == set(metrics)


BAD_AUTH = [
    (SonarrSource, "sonarr", {"api_key": "wrong"}),
    (JellyfinSource, "jellyfin", {"api_key": "wrong"}),
    (ImmichSource, "immich", {"api_key": "wrong"}),
    (SeerrSource, "seerr", {"api_key": "wrong"}),
    (ProwlarrSource, "prowlarr", {"api_key": "wrong"}),
    (AdGuardSource, "adguard", {"username": "admin", "password": "wrong"}),
    (UptimeKumaSource, "kuma", {"api_key": "wrong"}),
    (ProxmoxSource, "proxmox", {"token_id": "a@pve!b", "token_secret": "wrong"}),
    (QBittorrentSource, "qbit", {"username": "u", "password": "wrong"}),
]


@pytest.mark.parametrize("cls,prefix,values", BAD_AUTH, ids=[c[0].id for c in BAD_AUTH])
def test_wrong_credentials_are_reported_not_raised(base, cls, prefix, values):
    status = _source(cls, base, prefix, **values).check()
    assert status["connected"] is False and status["detail"]


def test_unreachable_service_is_reported(base):
    status = SonarrSource.from_values({"url": "http://127.0.0.1:9", "api_key": "k"}, {}).check()
    assert status["connected"] is False


def test_home_assistant(base):
    ha = _source(HomeAssistantSource, base, "ha", token="t")
    assert ha.check()["connected"]
    assert float(ha.get_value("sensor.stue_temperatur")["state"]) > 0
    assert any(k["key"] == "light.stue" for k in ha.list_keys())
    assert len(ha.get_history("sensor.effekt", 2)) > 50
    assert len(ha.list_calendar_events("calendar.familie", "2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z")) == 4
    before = ha.get_value("light.stue", max_age=0)["state"]
    ha.run_action({"domain": "light", "service": "toggle", "data": {"entity_id": "light.stue"}})
    assert ha.get_value("light.stue", max_age=0)["state"] != before
    assert HomeAssistantSource.from_values({"url": f"{base}/ha", "token": "wrong"}, {"WEATHER_CACHE_TTL": 1}).check()["detail"] == "Ugyldig token"


# --- the integrations' own widgets -------------------------------------------------


def _rows(data):
    assert isinstance(data["items"], list) and data["items"]
    for item in data["items"]:
        assert item["title"]
    return data["items"]


def test_list_widgets(base):
    sessions = _rows(_source(JellyfinSource, base, "jellyfin", api_key="k").widget_data("media_sessions", {}))
    assert len(sessions) == 2 and sessions[0]["title"].startswith("Severance · S02E04") and sessions[0]["progress"] == 40.0
    assert sessions[1]["level"] == "off"  # paused

    guests = _rows(_source(ProxmoxSource, base, "proxmox", token_id="a@pve!b", token_secret="s").widget_data("proxmox_guests", {}))
    assert [g["title"] for g in guests[:2]] == ["pve1", "pve2"] and any(g["title"] == "windows" and g["level"] == "off" for g in guests)
    running = _source(ProxmoxSource, base, "proxmox", token_id="a@pve!b", token_secret="s").widget_data("proxmox_guests", {"show": "running"})["items"]
    assert all(g["level"] == "ok" for g in running)

    monitors = _rows(_source(UptimeKumaSource, base, "kuma", api_key="k").widget_data("kuma_monitors", {}))
    assert monitors[0]["title"] == "Backup-server" or monitors[0]["level"] in ("bad", "off")  # anything not up comes first
    assert next(m for m in monitors if m["title"] == "NAS")["level"] == "bad"
    assert next(m for m in monitors if m["title"] == "Home Assistant")["value"] == "41 ms"
    assert [m["title"] for m in _source(UptimeKumaSource, base, "kuma", api_key="k").widget_data("kuma_monitors", {"show": "down"})["items"]] == ["Backup-server", "NAS"]

    events = _rows(_source(FrigateSource, base, "frigate").widget_data("frigate_events", {"count": 2}))
    assert len(events) == 2 and events[0]["title"] == "Person" and events[0]["subtitle"] == "inngang" and events[0]["score"] == 91

    assert len(_source(SonarrSource, base, "sonarr", api_key="k").widget_data("arr_calendar", {})["items"]) == 4
    assert _source(RadarrSource, base, "radarr", api_key="k").widget_data("arr_queue", {})["items"][0]["progress"] == 62.5
    torrents = _source(QBittorrentSource, base, "qbit", username="u", password="p")
    assert len(torrents.widget_data("qbit_torrents", {"filter": "all"})["items"]) == 4
    torrents.run_widget_action("pause_all", {})
    assert torrents.widget_data("qbit_torrents", {"filter": "paused"})["matching"] >= 3
    torrents.run_widget_action("resume_all", {})


def test_system_source():
    system = SystemSource.from_values({"paths": "/"}, {})
    assert system.check()["connected"]
    snapshot = system.widget_data("system_resources", {})
    assert snapshot["uptime"] > 0 and snapshot["disks"] and 0 <= snapshot["disks"][0]["percent"] <= 100
    assert snapshot["memory"] is None or 0 < snapshot["memory"]["percent"] <= 100
    metrics = system.fetch_metrics()
    assert "uptime_hours" in metrics and "disk_1_percent" in metrics


def test_every_integration_widget_has_a_provider():
    provided = {widget for cls in CATALOG for widget in cls.WIDGETS}
    assert provided == set(INTEGRATION_WIDGETS)
    assert len({cls.id for cls in CATALOG}) == len(CATALOG)
    for cls in CATALOG:
        assert cls.label and cls.icon and cls.description, cls
        assert all(field["kind"] in ("text", "url", "password", "number", "bool") for field in cls.FIELDS), cls


# --- feeds -----------------------------------------------------------------------


def test_feed_parsing(base):
    from app.datasources import http

    _s, _h, rss = http.request(f"{base}/rss/feed.xml")
    title, items = parse_feed(rss)
    assert title == "Teknologinytt" and len(items) == 5
    assert items[0]["link"] == "https://example.test/nyhet/0" and items[0]["time_ms"] > 0
    assert items[4]["title"] == "Open source-prosjekt får støtte & nytt navn"
    _s, _h, atom = http.request(f"{base}/rss/atom.xml")
    title, items = parse_feed(atom)
    assert title == "Prosjektbloggen" and items[0]["link"] == "https://blog.example.test/0"
    _s, _h, bomb = http.request(f"{base}/rss/bomb.xml")
    with pytest.raises(ValueError):
        parse_feed(bomb)
    title, items = parse_feed(b'<rss><channel><item><title>x</title><link>javascript:alert(1)</link></item></channel></rss>')
    assert items[0]["link"] is None


def test_feed_preview_is_admin_only(base, admin, visitor):
    widget = {"type": "feed", "count": 3, "feeds": [{"url": f"{base}/rss/feed.xml"}]}
    assert visitor.post("/api/feed-preview", json=widget).status_code == 403
    assert len(admin.post("/api/feed-preview", json=widget).get_json()["items"]) == 3
    assert admin.post("/api/feed-preview", json=[1]).status_code == 400
    assert admin.post("/api/feed-preview", json={"feeds": [{"url": "file:///etc/passwd"}]}).status_code == 404


# --- weather: the forecast comes from a service call ---------------------------------


def test_weather_widget_reads_the_forecast_service(base, admin, anon, visitor):
    ha = _source(HomeAssistantSource, base, "ha", token="t")
    assert "forecast" not in ha.get_value("weather.home")["attributes"]  # like Home Assistant 2024.4+
    forecast = ha.get_forecast("weather.home")
    assert len(forecast) == 5 and forecast[1]["condition"] == "rainy"

    assert admin.put("/api/integrations/home_assistant", json={"enabled": True, "values": {"url": f"{base}/ha", "token": "t"}}).status_code == 200
    widgets = [{"id": "wx", "type": "weather", "key": "weather.home", "x": 0, "y": 0, "w": 3, "h": 2}]
    assert admin.put("/api/widgets", json={"widgets": widgets, "grid": {}}).status_code == 200
    body = anon.get("/api/widget/wx/weather").get_json()
    assert body["condition"] == "partlycloudy" and body["temperature"] == 12.3
    assert [day["condition"] for day in body["forecast"]] == ["partlycloudy", "rainy", "sunny", "cloudy", "snowy"]
    assert body["forecast"][1]["templow"] == 5 and body["forecast"][1]["precipitation"] == 6.4

    assert visitor.post("/api/weather-preview", json={"key": "weather.home"}).status_code == 403
    assert len(admin.post("/api/weather-preview", json={"key": "weather.home"}).get_json()["forecast"]) == 5
    assert admin.post("/api/weather-preview", json={"key": "sensor.x"}).status_code == 400
    admin.put("/api/integrations/home_assistant", json={"enabled": True, "values": {"url": "", "token": ""}, "clear": ["token"]})
    admin.put("/api/widgets", json={"widgets": [], "grid": {}})
    # with Home Assistant not set up the old endpoints answer "not configured", never a crash
    assert anon.get("/api/weather").status_code == 404 and anon.get("/api/home").status_code == 404


# --- app status in one answer ----------------------------------------------------------


def test_status_summary_lists_only_what_the_caller_may_see(base, admin, anon):
    apps = [
        {"title": "Up", "url": f"{base}/ha/api/config"},
        {"title": "Down", "url": "http://127.0.0.1:9/nothing"},
        {"title": "Members", "url": "https://m.example", "internalUrl": f"{base}/frigate/api/version", "visibility": "authenticated"},
        {"title": "Odd", "url": "ftp://files.example"},
    ]
    assert admin.put("/api/apps", json={"apps": apps[:3], "default_mode": "window", "categories": {}}).status_code == 200
    mine = admin.get("/api/status/summary").get_json()
    assert mine["total"] == 3 and mine["up"] == 2 and mine["down"] == 1
    assert {item["title"]: item["status"] for item in mine["items"]} == {"Up": "up", "Down": "down", "Members": "up"}
    public = anon.get("/api/status/summary").get_json()
    assert [item["title"] for item in public["items"]] == ["Up", "Down"] and public["total"] == 2
    assert all(set(item) == {"title", "status", "ms"} for item in public["items"])  # never the internal address
    admin.put("/api/apps", json={"apps": [], "default_mode": "window", "categories": {}})
    assert anon.get("/api/status/summary").get_json() == {"items": [], "up": 0, "down": 0, "total": 0}


def test_list_rows_carry_states_not_translated_text(base):
    monitors = _source(UptimeKumaSource, base, "kuma", api_key="k").widget_data("kuma_monitors", {})
    states = {m["title"]: m["state"] for m in monitors["items"]}
    assert states == {"Backup-server": "maintenance", "NAS": "down", "Home Assistant": None, "Immich": None, "Router": None}
    assert (monitors["up"], monitors["down"], monitors["total"]) == (3, 1, 5)
    guests = _source(ProxmoxSource, base, "proxmox", token_id="a@pve!b", token_secret="s").widget_data("proxmox_guests", {})["items"]
    assert next(g for g in guests if g["title"] == "windows")["state"] == "stopped"
    sessions = _source(JellyfinSource, base, "jellyfin", api_key="k").widget_data("media_sessions", {})["items"]
    assert [s["transcoding"] for s in sessions] == [False, True]


def test_feed_widget_endpoint(base, admin, anon):
    widgets = [
        {"id": "news", "type": "feed", "x": 0, "y": 0, "w": 4, "h": 3, "count": 6, "feeds": [{"url": f"{base}/rss/redirect", "name": "Nyheter"}, {"url": f"{base}/rss/atom.xml"}, {"url": "ftp://x/y"}]},
        {"id": "dead", "type": "feed", "x": 4, "y": 0, "w": 4, "h": 3, "feeds": [{"url": "http://127.0.0.1:9/none.xml"}]},
        {"id": "empty", "type": "feed", "x": 8, "y": 0, "w": 4, "h": 3},
    ]
    assert admin.put("/api/widgets", json={"widgets": widgets, "grid": {}}).status_code == 200
    body = anon.get("/api/widget/news/feed").get_json()
    assert len(body["items"]) == 6
    assert {item["source"] for item in body["items"]} == {"Nyheter", "Prosjektbloggen"}
    assert body["items"] == sorted(body["items"], key=lambda item: item["time_ms"], reverse=True)
    assert anon.get("/api/widget/dead/feed").status_code == 502
    assert anon.get("/api/widget/empty/feed").status_code == 404
    admin.put("/api/widgets", json={"widgets": [], "grid": {}})
