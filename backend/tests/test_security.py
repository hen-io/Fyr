"""Cross-cutting protections: who may call what, forged requests, bad input."""

import logging
import os

import pytest

from conftest import SAME_ORIGIN, VISITOR

ADMIN_ONLY = [
    ("get", "/api/users", None),
    ("post", "/api/users", {"username": "x1", "password": "longenough1"}),
    ("delete", f"/api/users/{VISITOR[0]}", None),
    ("put", f"/api/users/{VISITOR[0]}/role", {"role": "admin"}),
    ("put", f"/api/users/{VISITOR[0]}/password", {"password": "longenough1"}),
    ("put", "/api/apps", {"apps": []}),
    ("put", "/api/layout", {}),
    ("put", "/api/widgets", {"widgets": []}),
    ("post", "/api/widgets/reset", None),
    ("put", "/api/defaults", {"defaults": {}}),
    ("post", "/api/defaults/reset-user-prefs", None),
    ("get", "/api/integrations", None),
    ("put", "/api/integrations/sonarr", {"enabled": True}),
    ("get", "/api/sources", None),
    ("get", "/api/sources/home_assistant/keys", None),
    ("post", "/api/widget-data", {"type": "sensor"}),
    ("post", "/api/integration-preview", {"type": "arr_queue"}),
    ("get", "/api/icons", None),
    ("post", "/api/icons", None),
    ("get", "/api/system/info", None),
    ("get", "/api/system/logs", None),
    ("post", "/api/system/restart", None),
]


@pytest.mark.parametrize("method,path,body", ADMIN_ONLY)
def test_admin_only_endpoints(anon, visitor, method, path, body):
    assert getattr(anon, method)(path, json=body).status_code == 401
    assert getattr(visitor, method)(path, json=body).status_code == 403


# --- request forgery -------------------------------------------------------------


def _write(client, headers):
    return client.put("/api/defaults", json={"defaults": {"siteTitle": "x"}}, headers=headers).status_code


def test_writes_must_come_from_this_origin(admin):
    assert _write(admin, {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"}) == 403
    # a different app on a sibling subdomain is "same-site" - still not us
    assert _write(admin, {"Sec-Fetch-Site": "same-site", "Origin": "https://other.localhost"}) == 403
    assert _write(admin, {"Sec-Fetch-Site": "same-site"}) == 403
    assert _write(admin, {"Origin": "https://evil.example"}) == 403
    assert _write(admin, SAME_ORIGIN) == 200
    assert _write(admin, {"Sec-Fetch-Site": "none"}) == 200
    assert _write(admin, {"Origin": "http://localhost"}) == 200  # older browser, own origin
    assert _write(admin, {}) == 200  # non-browser client
    admin.put("/api/defaults", json={"defaults": {}})


def test_a_form_post_cannot_stand_in_for_json(admin):
    response = admin.put("/api/defaults", data="defaults=x", content_type="application/x-www-form-urlencoded", headers=SAME_ORIGIN)
    assert response.status_code == 400


# --- malformed input never crashes ----------------------------------------------

FUZZ = [
    ("post", "/api/login", {"username": {"a": 1}, "password": ["x"]}),
    ("post", "/api/login", [1, 2]),
    ("post", "/api/login", "str"),
    ("post", "/api/users", {"username": 5, "password": {"a": 1}, "role": []}),
    ("put", "/api/me/prefs", [1]),
    ("put", "/api/me/profile", {"display_name": {"x": 1}}),
    ("put", "/api/me/password", {"current_password": 5, "new_password": []}),
    ("put", "/api/apps", {"apps": [1, "x", None, {"title": 5}]}),
    ("put", "/api/apps", {"apps": [], "categories": {"a": 5, "b": {"hidden_for": "x"}}}),
    ("put", "/api/widgets", {"widgets": [1, {"type": {}}, {"type": "x", "x": "NaN", "w": 1e99}], "grid": []}),
    ("put", "/api/widgets", {"widgets": [{"type": "t", "id": {"a": 1}}], "grid": {"columns": "x"}}),
    ("put", "/api/defaults", {"defaults": {"gap": 1e300, "palette": {}}}),
    ("put", "/api/layout", [1]),
    ("put", "/api/integrations/sonarr", {"values": {"url": 5, "api_key": {}}}),
    ("put", "/api/integrations/mqtt", {"values": {"port": "x"}}),
    ("post", "/api/widget-data", {"type": "sensor", "source": {}, "key": [], "entities": [1, {"key": 5}]}),
    ("post", "/api/integration-preview", {"type": [], "source": 5}),
    ("put", f"/api/users/{VISITOR[0]}/role", {"role": {}}),
    ("get", "/api/widget/nope/history?hours=nan", None),
    ("get", "/api/system/logs?lines=abc&source=backend", None),
    ("delete", "/api/login", None),
    ("patch", "/api/apps", {}),
    ("get", "/api/nope", None),
]


@pytest.mark.parametrize("method,path,body", FUZZ)
def test_bad_input_gets_a_json_error_not_a_crash(admin, method, path, body):
    response = getattr(admin, method)(path, json=body)
    assert response.status_code < 500, response.data
    if response.status_code >= 400:
        assert response.is_json and "error" in response.get_json()


def test_oversized_body_is_refused(admin):
    response = admin.put("/api/me/prefs", data=b'{"a":"' + b"x" * (5 * 1024 * 1024) + b'"}', content_type="application/json")
    assert response.status_code in (400, 413)


# --- nothing reaches outside its directory -----------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/icons/..%2f..%2fdata%2fusers.json",
        "/icons/%2e%2e/%2e%2e/etc/passwd",
        "/icons/....//....//etc/passwd",
        "/api/avatar/..%2f..%2fusers",
        "/api/tilefx/..%2f..%2fapps.config/face",
        "/api/tilefx/%2e%2e%5c%2e%2e%5cusers.json/logo?t=1",
    ],
)
def test_path_traversal(anon, path):
    response = anon.get(path)
    assert response.status_code in (400, 404)
    assert b"password_hash" not in response.data


def test_logs_endpoint(admin, app):
    log_dir = os.environ["FYR_LOG_DIR"]
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "backend.log"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(f"line {i}" for i in range(300)))
    body = admin.get("/api/system/logs?lines=25").get_json()
    assert body["available"] and len(body["lines"]) == 25 and body["lines"][-1] == "line 299"
    assert len(admin.get("/api/system/logs?lines=1").get_json()["lines"]) == 10  # lower bound
    assert admin.get("/api/system/logs?source=../etc").status_code == 400


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(f"{record.name.split('.')[-1].upper()} {record.getMessage()}")


def test_changes_and_client_reports_are_logged(admin, anon):
    seen = _Lines()
    loggers = [logging.getLogger("fyr.audit"), logging.getLogger("fyr.client")]
    for logger in loggers:
        logger.addHandler(seen)
    try:
        assert admin.put("/api/defaults", json={"defaults": {"palette": "candy"}}).status_code == 200
        assert admin.put("/api/defaults", json={"defaults": {"palette": "grape", "gap": 14}}).status_code == 200
        assert 'AUDIT default_changed setting="palette" was="candy" now="grape" by="admin1"' in seen.lines
        assert 'AUDIT default_changed setting="gap" was="(built-in)" now="14" by="admin1"' in seen.lines
        assert admin.put("/api/defaults", json={"defaults": {}}).status_code == 200

        assert anon.post("/api/client-log", json={"event": "visit", "screen": "1920x1080", "secret": "x"}).status_code == 200
        assert anon.post("/api/client-log", json={"event": "app_opened", "app": "Evil\nAUDIT login user=root"}).status_code == 200
        assert anon.post("/api/client-log", json={"event": "made_up"}).status_code == 400
        client = [line for line in seen.lines if line.startswith("CLIENT")]
        assert client[0].startswith('CLIENT visit user="-"') and 'screen="1920x1080"' in client[0] and "secret" not in client[0]
        assert len(client) == 2 and "\n" not in client[1] and "Evil\\nAUDIT" in client[1]  # the line break is escaped: no forged second line
        answers = [anon.post("/api/client-log", json={"event": "visit"}).status_code for _ in range(60)]
        assert 429 in answers  # a ceiling per address
    finally:
        for logger in loggers:
            logger.removeHandler(seen)


def test_logs_are_split_into_backend_and_frontend(admin):
    log_dir = os.environ["FYR_LOG_DIR"]
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "backend.log"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(f"2026-10-04 10:00:{i:02d} {'CLIENT visit' if i % 3 == 0 else 'AUDIT login'} n={i}" for i in range(30)))
    frontend = admin.get("/api/system/logs?source=frontend&lines=50").get_json()["lines"]
    backend = admin.get("/api/system/logs?source=backend&lines=50").get_json()["lines"]
    assert len(frontend) == 10 and all(" CLIENT " in line for line in frontend)
    assert len(backend) == 20 and not any(" CLIENT " in line for line in backend)


def test_misc(anon, admin):
    assert anon.get("/api/about").status_code == 200
    assert anon.get("/api/health").get_json() == {"ok": True}
    assert admin.post("/api/system/restart").status_code in (200, 501)  # 501 outside the container
    assert anon.get("/api/calendar/upcoming").status_code == 404  # the old server-wide calendar endpoint is gone


# --- nothing that changes anything is open ---------------------------------
# Every route the app has is walked, so a route added later cannot be
# forgotten: a write is refused for someone not logged in, and for a visitor
# account, unless it is on one of these two short lists.
_OPEN_WRITES = {
    "/api/login",  # how one logs in
    "/api/logout",
    "/api/client-log",  # usage lines for the log: fixed events, clipped values, rate-limited
    "/api/widget/<widget_id>/action",  # refuses by itself unless the widget says allow_anonymous
    "/api/widget/<widget_id>/integration-action",
}
_OWN_ACCOUNT = "/api/me"  # what any logged-in account may change: its own password, profile, settings


def _writes(app):
    for rule in app.url_map.iter_rules():
        for method in sorted(rule.methods - {"GET", "HEAD", "OPTIONS"}):
            path = rule.rule.replace("<integration_id>", "sonarr").replace("<username>", VISITOR[0]).replace("<name>", "nothing.png").replace("<widget_id>", "nothing")
            yield method, rule.rule, path


def test_every_write_needs_a_login(app, anon):
    checked = 0
    for method, rule, path in _writes(app):
        if rule in _OPEN_WRITES:
            continue
        response = anon.open(path, method=method, json={})
        assert response.status_code == 401, f"{method} {rule} answered {response.status_code} to someone not logged in"
        checked += 1
    assert checked >= 20


def test_every_config_write_needs_an_admin(app, visitor):
    checked = 0
    for method, rule, path in _writes(app):
        if rule in _OPEN_WRITES or rule.startswith(_OWN_ACCOUNT):
            continue
        response = visitor.open(path, method=method, json={})
        assert response.status_code == 403, f"{method} {rule} answered {response.status_code} to a visitor account"
        checked += 1
    assert checked >= 15


def test_a_refused_attempt_is_logged(visitor):
    seen = _Lines()
    logger = logging.getLogger("fyr.audit")
    logger.addHandler(seen)
    try:
        assert visitor.post("/api/apps/add", json={"url": "https://example.org"}).status_code == 403
    finally:
        logger.removeHandler(seen)
    assert any(line.startswith('AUDIT refused user="vis1" role="visitor" method="POST" path="/api/apps/add"') for line in seen.lines)


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "file:///etc/passwd", "ftp://host/x", "//host/x", "https://", "https://user:pw@host.example/", "https://host.example/a b", "https://host.example/\nicon: x", "https://host.example/\x00", "https://" + "a" * 600 + ".example"],
)
def test_an_added_app_must_be_a_plain_web_address(admin, url):
    assert admin.post("/api/apps/add", json={"url": url}).get_json() == {"error": "invalid_url"}


def test_app_addresses_cannot_carry_control_characters(admin):
    bad = {"apps": [{"title": "X", "url": "https://x.example/\r\nurl: javascript:alert(1)"}]}
    assert admin.put("/api/apps", json=bad).get_json() == {"error": "invalid_url"}


def test_the_layout_only_takes_places_by_app_title(admin):
    assert admin.put("/api/layout", json={"App": {"x": 1, "y": 2}}).status_code == 200
    for bad in ([], {"": {"x": 1}}, {"App": {"x": {"deep": 1}}}, {"App": [1, 2]}, {"App": {"x": "y" * 300_000}}, {f"a{i}": 1 for i in range(2100)}):
        assert admin.put("/api/layout", json=bad).get_json() == {"error": "invalid_body"}
    assert admin.put("/api/layout", json={}).status_code == 200


def test_the_icon_fetch_only_follows_web_redirects():
    import urllib.error

    from app.routes.config import _fetcher, _WebRedirectsOnly

    assert not any(type(handler).__name__ in ("FileHandler", "FTPHandler", "DataHandler") for handler in _fetcher.handlers)
    handler = _WebRedirectsOnly()
    for target in ("file:///etc/passwd", "ftp://host/x", "gopher://host/"):
        with pytest.raises(urllib.error.HTTPError):
            handler.redirect_request(None, None, 302, "Found", {}, target)


def test_only_admins_see_a_feeds_full_address(admin, visitor, anon):
    private = "https://news.example:8443/private/feed.xml?token=SECRET"
    widget = {"id": "feed1", "type": "feed", "x": 0, "y": 0, "w": 3, "h": 4, "feeds": [{"url": private, "name": "News"}]}
    assert admin.put("/api/widgets", json={"widgets": [widget]}).status_code == 200
    try:
        assert admin.get("/api/widgets").get_json()["widgets"][0]["feeds"][0]["url"] == private
        for client in (visitor, anon):
            body = client.get("/api/widgets")
            assert b"SECRET" not in body.data and b"private/feed" not in body.data
            assert body.get_json()["widgets"][0]["feeds"] == [{"url": "https://news.example:8443/", "name": "News"}]
    finally:
        admin.post("/api/widgets/reset")
