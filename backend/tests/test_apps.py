"""Apps, categories, who sees what, status checks, icons."""

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
