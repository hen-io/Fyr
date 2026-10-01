"""Server-drawn tile effects: signed URLs, rendering, and the values the backend
shares with the frontend."""

import io
import os
import re

from PIL import Image

from app import tilefx, tileurls
from conftest import make_png, upload

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src")


def _setup(admin, defaults):
    assert upload(admin, "/api/icons", "badge.png", make_png(48, (30, 140, 220))).status_code == 201
    admin.put("/api/apps", json={"apps": [{"title": "Badge", "url": "https://b.example", "icon": "badge.png"}, {"title": "NoIcon", "url": "https://n.example"}]})
    assert admin.put("/api/defaults", json={"defaults": defaults}).status_code == 200


def _fx(client, title="Badge"):
    return next(a for a in client.get("/api/apps").get_json()["apps"] if a["title"] == title).get("fx")


def test_no_effects_means_no_urls(admin, anon):
    _setup(admin, {})
    assert _fx(anon) is None


def test_signed_urls_render_and_nothing_else_does(admin, anon):
    _setup(admin, {"tileTint": "on", "logoStrokeWidth": 2, "logoStrokeColor": "accent", "roundness": 30, "tileBadgeStyle": "dome", "tileBadgeColor": "radial"})
    fx = _fx(anon)
    assert fx["round"] == 27.0 and "s=dome" in fx["face"] and "c=radial" in fx["face"] and "ac=ffb347" in fx["logo"]
    assert _fx(anon, "NoIcon") is None

    face = anon.get(fx["face"])
    assert face.status_code == 200 and face.mimetype == "image/webp" and "immutable" in face.headers["Cache-Control"]
    image = Image.open(io.BytesIO(face.data)).convert("RGBA")
    assert image.size == (tilefx.SIZE, tilefx.SIZE)
    assert image.getpixel((2, 2))[3] == 0 and image.getpixel((tilefx.SIZE // 2, tilefx.SIZE // 2))[3] == 255  # rounded corners baked in
    assert anon.get(fx["logo"]).status_code == 200

    # unsigned, tampered or re-pointed URLs are refused
    assert anon.get("/api/tilefx/badge.png/face?v=1&r=27.0&s=dome&c=radial").status_code == 404
    assert anon.get(fx["logo"].replace("sw=2", "sw=6")).status_code == 404
    assert anon.get(fx["face"].replace("/face?", "/logo?")).status_code == 404
    assert anon.get(fx["face"].replace("badge.png", "other.png")).status_code == 404
    admin.put("/api/defaults", json={"defaults": {}})


def test_browser_mode_issues_no_urls(admin, anon):
    _setup(admin, {"tileTint": "on", "tileFxMode": "client"})
    assert _fx(anon) is None
    admin.put("/api/defaults", json={"defaults": {}})


def test_per_app_outline_overrides_the_default(admin, anon):
    _setup(admin, {"logoStrokeWidth": 3})
    admin.put("/api/apps", json={"apps": [{"title": "Badge", "url": "https://b.example", "icon": "badge.png", "iconStroke": 0}]})
    assert _fx(anon) is None  # switched off for this app, and no tint
    admin.put("/api/apps", json={"apps": [{"title": "Badge", "url": "https://b.example", "icon": "badge.png", "iconStroke": 5, "iconStrokeColor": "white"}]})
    assert "sw=5.0" in _fx(anon)["logo"] and "sc=white" in _fx(anon)["logo"] and _fx(anon)["face"] is None
    admin.put("/api/defaults", json={"defaults": {}})


def test_every_style_and_colour_renders():
    icon = Image.open(io.BytesIO(make_png(64, (200, 60, 60)))).convert("RGBA")
    for style in tilefx.BADGE_STYLES:
        assert tilefx.render_face(icon, 20, style, "diagonal").size == (tilefx.SIZE, tilefx.SIZE)
    for colour in tilefx.BADGE_COLOURS:
        assert tilefx.render_face(icon, 20, "glass", colour).mode == "RGBA"
    grey = Image.open(io.BytesIO(make_png(64, (128, 128, 128)))).convert("RGBA")
    assert tilefx.render_face(grey, 0, "glass", "duo").size == (tilefx.SIZE, tilefx.SIZE)
    for color in tilefx.STROKE_COLORS:
        assert tilefx.render_logo(icon, True, 3, color, "dark", "ffb347").mode == "RGBA"


# --- values that exist on both sides must agree --------------------------------------


def _read(*parts):
    with open(os.path.join(FRONTEND, *parts), encoding="utf-8") as handle:
        return handle.read()


def test_palette_accents_match_the_stylesheet():
    css = _read("styles", "theme.css")
    in_css = {name: accent.lower() for name, accent in re.findall(r'data-palette="([a-z]+)"\]\s*\{[^}]*?--accent:\s*#([0-9a-fA-F]{6})', css)}
    assert in_css, "no palettes found in theme.css"
    assert in_css == tileurls.PALETTE_ACCENTS


def test_setting_defaults_match_the_frontend():
    js = _read("constants", "settings.js")
    for key, expected in tileurls.SETTING_DEFAULTS.items():
        match = re.search(r'key: "%s",.*?default: ("[^"]*"|[0-9.]+)' % key, js, re.S)
        assert match, f"setting {key} not found in settings.js"
        assert match.group(1).strip('"') == str(expected), key


def test_badge_options_match_the_frontend():
    js = _read("constants", "appearance.js")

    def values(name):
        block = re.search(r"export const %s = \[(.*?)\];" % name, js, re.S).group(1)
        return tuple(re.findall(r'value: "([a-z]+)"', block))

    assert values("BADGE_STYLES") == tilefx.BADGE_STYLES
    assert values("BADGE_COLOURS") == tilefx.BADGE_COLOURS
    assert set(values("LOGO_STROKE_COLORS")) == set(tilefx.STROKE_COLORS)


def test_radius_formula():
    assert tileurls.radius_percent(20) == 18.0
    assert tileurls.radius_percent(40) == 36.0
    assert tileurls.radius_percent(0) == 0
    assert tileurls.radius_percent("x") == 18.0
