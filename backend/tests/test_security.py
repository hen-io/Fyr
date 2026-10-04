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
