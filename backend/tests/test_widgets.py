"""The dashboard: widgets, actions, integrations, defaults."""

import os

WIDGETS = [
    {"id": "a", "type": "text", "x": 0, "y": 0, "w": 3, "h": 1, "text": "hi"},
    {"id": "p", "type": "text", "x": 3, "y": 0, "w": 3, "h": 1, "text": "s", "visibility": "authenticated"},
    {"id": "b", "type": "buttons", "source": "mqtt", "x": 0, "y": 1, "w": 3, "h": 1, "buttons": [{"topic": "a/#", "payload": "x"}]},
    {"id": "hidden-buttons", "type": "buttons", "source": "home_assistant", "visibility": "authenticated", "allow_anonymous": True, "x": 0, "y": 2, "w": 3, "h": 1, "buttons": [{"service": "light.toggle"}]},
]


def test_widgets_roundtrip_and_visibility(admin, anon, visitor):
    assert admin.put("/api/widgets", json={"widgets": WIDGETS, "grid": {"columns": 99, "row_height": 5}}).status_code == 200
    seen = anon.get("/api/widgets").get_json()
    assert seen["grid"] == {"columns": 24, "row_height": 30}  # clamped
    assert [w["id"] for w in seen["widgets"]] == ["a", "b"]
    assert anon.get("/api/widget/p").status_code == 404
    assert visitor.get("/api/widget/p").status_code == 200
    assert visitor.put("/api/widgets", json={"widgets": []}).status_code == 403


def test_saving_does_not_bring_back_the_default_footer_widgets(admin, anon):
    admin.put("/api/widgets", json={"widgets": WIDGETS[:1], "grid": {}})
    assert [w["id"] for w in anon.get("/api/widgets").get_json()["widgets"]] == ["a"]
    admin.put("/api/widgets", json={"widgets": WIDGETS, "grid": {}})


def test_actions_need_a_login_and_only_run_saved_buttons(admin, anon):
    admin.put("/api/widgets", json={"widgets": WIDGETS, "grid": {}})
    assert anon.post("/api/widget/b/action", json={"index": 0}).status_code == 401
    assert admin.post("/api/widget/b/action", json={"index": 0}).status_code in (400, 502)  # wildcard topic refused
    assert admin.post("/api/widget/b/action", json={"index": 9}).status_code == 400
    assert admin.post("/api/widget/b/action", json={"index": "0"}).status_code == 400
    assert admin.post("/api/widget/a/action", json={"index": 0}).status_code == 404  # not a button widget
    # a members-only widget stays out of reach even when it allows anonymous presses
    assert anon.post("/api/widget/hidden-buttons/action", json={"index": 0}).status_code == 404


def test_editor_previews_are_admin_only(visitor, anon):
    assert visitor.post("/api/widget-data", json={"type": "sensor"}).status_code == 403
    assert visitor.post("/api/integration-preview", json={"type": "arr_queue"}).status_code == 403
    assert anon.get("/api/sources").status_code == 401


def test_reset_dashboard(admin, anon):
    assert admin.post("/api/widgets/reset").status_code == 200
    assert anon.get("/api/widgets").get_json()["widgets"] == []


def test_integrations_keep_their_secrets(admin, visitor, app):
    listing = admin.get("/api/integrations").get_json()
    ids = [entry["id"] for entry in listing]
    assert ids[:2] == ["home_assistant", "mqtt"] and "backrest" in ids
    assert admin.put("/api/integrations/sonarr", json={"enabled": True, "values": {"url": "javascript:x"}}).status_code == 400
    saved = admin.put("/api/integrations/sonarr", json={"enabled": True, "values": {"url": "http://127.0.0.1:9", "api_key": "sekret"}})
    assert saved.status_code == 200
    passwords = [f for f in saved.get_json()["fields"] if f["kind"] == "password"]
    assert passwords and all("value" not in f and f["has_value"] for f in passwords)
    assert b"sekret" not in admin.get("/api/integrations").data
    if os.name != "nt":  # file modes are not meaningful on Windows
        assert os.stat(os.path.join(app.config["DATA_DIR"], "connections.json")).st_mode & 0o077 == 0
    assert visitor.get("/api/integrations").status_code == 403
    assert admin.put("/api/integrations/nope", json={}).status_code == 404
    admin.put("/api/integrations/sonarr", json={"enabled": False})


def test_server_defaults_are_sanitised(admin, visitor, anon):
    response = admin.put("/api/defaults", json={"defaults": {"language": "en", "siteTitle": "T", "junk": 1, "gap": True, "roundness": 12.5}})
    assert response.status_code == 200
    assert anon.get("/api/defaults").get_json()["defaults"] == {"language": "en", "siteTitle": "T", "roundness": 12.5}
    assert visitor.put("/api/defaults", json={"defaults": {}}).status_code == 403
    admin.put("/api/defaults", json={"defaults": {}})
