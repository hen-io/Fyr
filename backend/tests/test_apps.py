"""Apps, categories, who sees what, status checks, icons."""

import io
import json
import os

from conftest import make_png, upload

APPS = [
    {"title": "Pub", "url": "https://pub.example", "category": "Open"},
    {"title": "Secret", "url": "https://s.example", "category": "Hidden", "internalUrl": "http://127.0.0.1:9/secret"},
    {"title": "Lonely", "url": "https://l.example", "visibility": "authenticated"},
    {"title": "Local", "url": "http://127.0.0.1:9/app", "category": "Open"},
]
CATEGORIES = {"Open": {}, "Hidden": {"hidden_for": ["anonymous", "visitor"]}, "Empty": {}}


def _titles(client, query=""):
    return [a["title"] for a in client.get("/api/apps" + query).get_json()["apps"]]


def test_visibility_per_audience(admin, visitor, anon):
    assert admin.put("/api/apps", json={"apps": APPS, "default_mode": "window", "categories": CATEGORIES}).status_code == 200
    assert _titles(anon) == ["Pub", "Local"]
    assert _titles(visitor) == ["Pub", "Local", "Lonely"]
    assert len(_titles(admin)) == 4
    assert len(_titles(visitor, "?all=1")) == 3  # ?all=1 only means something for an admin
    assert "Empty" in admin.get("/api/apps?all=1").get_json()["categories"]
    assert "Secret" not in admin.get("/api/layout").get_json()


def test_category_order_follows_the_editor(admin):
    apps = [{"title": "A1", "url": "https://a.example", "category": "First"}, {"title": "B1", "url": "https://b.example", "category": "Second"}]
    # sent as raw text: the test client's json= would sort the keys, a browser does not
    body = '{"apps": %s, "categories": {"Second": {"icon": "server"}, "First": {}}}' % json.dumps(apps)
    admin.put("/api/apps", data=body, content_type="application/json")
    assert [a["category"] for a in admin.get("/api/apps?all=1").get_json()["apps"]] == ["Second", "First"]
    admin.put("/api/apps", json={"apps": APPS, "default_mode": "window", "categories": CATEGORIES})


def test_app_validation(admin, visitor):
    app = APPS[0]
    assert admin.put("/api/apps", json={"apps": [app, app]}).status_code == 400  # duplicate titles
    assert admin.put("/api/apps", json={"apps": [{"title": "x", "url": "javascript:alert(1)"}]}).status_code == 400
    assert admin.put("/api/apps", json={"apps": [{"title": "x", "url": "http://a.b", "icon": "../../etc/passwd"}]}).status_code == 400
    assert admin.put("/api/apps", json={"apps": [{"title": "x", "url": "http://a.b", "iconStroke": 99}]}).status_code == 400
    assert admin.put("/api/apps", json={"apps": [{"title": "x", "url": "http://a.b", "iconStrokeColor": "pink"}]}).status_code == 400
    assert visitor.put("/api/apps", json={"apps": []}).status_code == 403


def test_status_only_checks_urls_that_are_on_the_dashboard(admin, anon):
    admin.put("/api/apps", json={"apps": APPS, "default_mode": "window", "categories": CATEGORIES})
    assert anon.get("/api/status?url=http://127.0.0.1:9/app").status_code == 200  # a visible app, exactly as configured
    assert anon.get("/api/status?url=http://127.0.0.1:9/other-path").status_code == 403  # same host, different path
    assert anon.get("/api/status?url=http://127.0.0.1:9/secret").status_code == 403  # a hidden app
    assert admin.get("/api/status?url=http://127.0.0.1:9/secret").status_code == 200
    assert anon.get("/api/status?url=http://169.254.169.254/").status_code == 403
    assert anon.get("/api/status?url=file:///etc/passwd").status_code == 400
    assert anon.get("/api/status?url=http://[::1").status_code == 400
    assert anon.get("/api/status?url=http://x:99999999/").status_code == 400


def test_apps_keep_their_search_keywords(admin):
    app = {"title": "Tagged", "url": "https://t.example", "keywords": " film, serier  tv "}
    assert admin.put("/api/apps", json={"apps": [app]}).status_code == 200
    assert admin.get("/api/apps").get_json()["apps"][0]["keywords"] == "film, serier  tv"
    assert admin.put("/api/apps", json={"apps": [{**app, "keywords": ["film"]}]}).status_code == 400
    assert admin.put("/api/apps", json={"apps": [{**app, "keywords": "x" * 501}]}).status_code == 400
    admin.put("/api/apps", json={"apps": []})


def test_server_info_lists_versions_and_dependencies(admin):
    info = admin.get("/api/system/info").get_json()
    assert info["backend_version"] and info["frontend_version"] and info["python_version"]
    assert {"Flask", "Pillow", "argon2-cffi"} <= set(info["dependencies"])
    assert all(isinstance(version, str) and version for version in info["dependencies"].values())


def test_framing_verdict_from_an_apps_headers():
    from app.routes.status import _framing

    own = "fyr.example"
    assert _framing(None, own) is None  # the app did not answer
    assert _framing({"xfo": None, "ancestors": None, "host": "a.example"}, own) == "ok"
    assert _framing({"xfo": "DENY", "ancestors": None, "host": "a.example"}, own) == "blocked"
    assert _framing({"xfo": "SAMEORIGIN", "ancestors": None, "host": "a.example"}, own) == "blocked"
    assert _framing({"xfo": "SAMEORIGIN", "ancestors": None, "host": "fyr.example"}, own) == "ok"
    assert _framing({"xfo": None, "ancestors": ["'none'"], "host": "a.example"}, own) == "blocked"
    assert _framing({"xfo": None, "ancestors": ["'self'"], "host": "a.example"}, own) == "blocked"
    assert _framing({"xfo": "DENY", "ancestors": ["https://fyr.example"], "host": "a.example"}, own) == "ok"  # frame-ancestors wins
    assert _framing({"xfo": None, "ancestors": ["https://*.example"], "host": "a.example"}, own) == "ok"
    assert _framing({"xfo": None, "ancestors": ["*"], "host": "a.example"}, own) == "ok"


def test_status_reports_time_history_and_framing(admin, anon):
    admin.put("/api/apps", json={"apps": APPS, "categories": CATEGORIES})
    body = anon.get("/api/status?url=http://127.0.0.1:9/app").get_json()
    assert body["status"] == "down" and body["ms"] is None and body["history"][-1] == 0 and body["frame"] is None
    assert anon.get("/api/status?url=http://127.0.0.1:9/app&frame=http://127.0.0.1:9/secret").get_json()["frame"] is None  # a hidden app is not probed
    assert "Secret" not in anon.get("/api/status/framing").get_json()
    summary = anon.get("/api/status/summary").get_json()
    assert all("ms" in item for item in summary["items"])


def test_an_app_can_be_added_from_its_address(admin, visitor, anon):
    admin.put("/api/apps", json={"apps": [{"title": "Example", "url": "https://x.example", "category": "Open"}], "categories": {"Open": {}}})
    new = {"url": "http://127.0.0.1:9/some/path"}
    assert anon.post("/api/apps/add", json=new).status_code == 401
    assert visitor.post("/api/apps/add", json=new).status_code == 403
    for bad in ({"url": "javascript:alert(1)"}, {"url": "ftp://files.example"}, {"url": ""}, {"url": "http://ok.example", "category": "Nope"}):
        assert admin.post("/api/apps/add", json=bad).status_code == 400
    added = admin.post("/api/apps/add", json=new)
    assert added.status_code == 201 and added.get_json() == {"title": "127.0.0.1", "icon": None}  # nothing answers there: no logo
    assert admin.post("/api/apps/add", json={"url": "https://www.example.com", "category": "Open"}).get_json()["title"] == "Example 2"  # the name was taken
    apps = {a["title"]: a for a in admin.get("/api/apps?all=1").get_json()["apps"]}
    assert apps["127.0.0.1"]["url"] == new["url"] and "category" not in apps["127.0.0.1"]
    assert apps["Example 2"]["category"] == "Open" and apps["Example"]["url"] == "https://x.example"
    admin.put("/api/apps", json={"apps": [], "categories": {}})


def test_icon_upload_accepts_only_real_images(admin, visitor, anon, app):
    png = make_png()
    assert upload(admin, "/api/icons", "ok.png", png).status_code == 201
    assert upload(visitor, "/api/icons", "v.png", png).status_code == 403
    assert upload(admin, "/api/icons", "x.svg", b"<svg onload=alert(1)>").status_code == 400
    assert upload(admin, "/api/icons", "fake.png", b"notpng").status_code == 400
    assert upload(admin, "/api/icons", "html.png", b"\x89PNG\r\n\x1a\n<script>alert(1)</script>").status_code == 400
    assert upload(admin, "/api/icons", "wrong.jpg", png).status_code == 400  # a PNG named .jpg
    assert upload(admin, "/api/icons", "big.png", png + b"0" * (1024 * 1024 + 10)).status_code == 400
    named = upload(admin, "/api/icons", "../../evil.png", png)
    assert named.status_code == 201 and named.get_json()["name"] == "evil.png"
    assert not os.path.exists(os.path.join(app.config["CONFIG_DIR"], "..", "..", "evil.png"))
    served = anon.get("/icons/ok.png")
    assert "sandbox" in served.headers["Content-Security-Policy"]
    assert anon.get("/icons/../../etc/passwd").status_code in (400, 404)


def test_icons_can_be_listed_renamed_and_deleted(admin, visitor, anon, app):
    png = make_png()
    assert upload(admin, "/api/icons", "logo-a.png", png).status_code == 201
    assert upload(admin, "/api/icons", "logo-b.png", png).status_code == 201
    apps = [{"title": "One", "url": "https://one.example", "icon": "logo-a.png", "category": "Open"}, {"title": "Two", "url": "https://two.example", "icon": "logo-a.png"}]
    assert admin.put("/api/apps", json={"apps": apps, "categories": {"Open": {}}}).status_code == 200

    assert "logo-a.png" in admin.get("/api/icons").get_json()  # the plain list is unchanged
    details = {i["name"]: i for i in admin.get("/api/icons?details=1").get_json()["icons"]}
    assert details["logo-a.png"]["used_by"] == ["One", "Two"] and details["logo-a.png"]["size"] == len(png)
    assert details["logo-b.png"]["used_by"] == []

    for client, status in ((visitor, 403), (anon, 401)):
        assert client.patch("/api/icons/logo-a.png", json={"name": "x.png"}).status_code == status
        assert client.delete("/api/icons/logo-b.png").status_code == status

    assert admin.patch("/api/icons/logo-a.png", json={"name": "logo-b.png"}).get_json()["error"] == "exists"
    assert admin.patch("/api/icons/logo-a.png", json={"name": "logo-a.svg"}).get_json()["error"] == "extension_changed"
    assert admin.patch("/api/icons/logo-a.png", json={"name": "../up.png"}).status_code == 400
    assert admin.patch("/api/icons/nope.png", json={"name": "other.png"}).status_code == 404
    renamed = admin.patch("/api/icons/logo-a.png", json={"name": "renamed.png"})
    assert renamed.status_code == 200 and renamed.get_json() == {"name": "renamed.png", "apps": 2}
    assert [a["icon"] for a in admin.get("/api/apps?all=1").get_json()["apps"]] == ["renamed.png", "renamed.png"]
    assert anon.get("/icons/logo-a.png").status_code == 404 and anon.get("/icons/renamed.png").status_code == 200

    assert upload_keep(admin, "renamed.png", png).status_code == 409
    assert admin.delete("/api/icons/logo-b.png").status_code == 200
    refused = admin.delete("/api/icons/renamed.png")
    assert refused.status_code == 409 and refused.get_json()["apps"] == ["One", "Two"]
    assert admin.delete("/api/icons/renamed.png?force=1").get_json() == {"ok": True, "apps": 2}
    assert all("icon" not in a for a in admin.get("/api/apps?all=1").get_json()["apps"])
    assert not os.path.exists(os.path.join(app.config["CONFIG_DIR"], "icons", "renamed.png"))
    assert admin.delete("/api/icons/..%2f..%2fusers.json").status_code in (400, 404)
    admin.put("/api/apps", json={"apps": [], "categories": {}})


def upload_keep(client, name, content):
    return client.post("/api/icons", data={"file": (io.BytesIO(content), name, "image/png"), "replace": "0"}, content_type="multipart/form-data")


def test_avatar_is_decoded_and_re_encoded(visitor, anon):
    html = b"<html><script>alert(1)</script></html>"
    assert upload(visitor, "/api/me/avatar", "evil.png", html, method="put").status_code == 400
    assert upload(visitor, "/api/me/avatar", "me.png", make_png(64), method="put").status_code == 200
    served = anon.get("/api/avatar/vis1")
    assert served.status_code == 200 and served.data[:4] == b"RIFF" and served.mimetype == "image/webp"
    assert "sandbox" in served.headers["Content-Security-Policy"]
    served.close()  # Windows will not delete a file that is still being read
    assert visitor.delete("/api/me/avatar").status_code == 200
    assert anon.get("/api/avatar/vis1").status_code == 404
    assert anon.get("/api/avatar/..%2f..%2fusers").status_code == 404
