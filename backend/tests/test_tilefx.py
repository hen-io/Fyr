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


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#18a058"/><circle cx="5" cy="5" r="2" fill="rgb(24, 160, 88)"/><path d="M0 0h1" stroke="#fff"/></svg>'


def test_svg_icons_get_a_badge_from_their_own_colours(admin, anon, app):
    path = os.path.join(app.config["CONFIG_DIR"], "icons", "logo.svg")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(SVG)
    (c1, _c2, _c3), hue = tilefx.palette(tilefx.load_icon(path))
    assert hue is not None and c1[1] > c1[0] and c1[1] > c1[2]  # green, like the logo

    admin.put("/api/apps", json={"apps": [{"title": "Vector", "url": "https://v.example", "icon": "logo.svg"}]})
    admin.put("/api/defaults", json={"defaults": {"tileTint": "on", "logoStrokeWidth": 2}})
    fx = _fx(anon, "Vector")
    assert fx["logo"] is None and "logo.svg/face" in fx["face"]  # the logo stays an SVG; the badge is a picture
    face = anon.get(fx["face"])
    assert face.status_code == 200 and face.mimetype == "image/webp"
    middle = Image.open(io.BytesIO(face.data)).convert("RGB").getpixel((tilefx.SIZE // 2, tilefx.SIZE // 2))
    assert middle[1] > middle[0] and middle[1] > middle[2]
    assert anon.get(fx["face"].replace("/face?", "/logo?")).status_code == 404
    admin.put("/api/defaults", json={"defaults": {"logoStrokeWidth": 2}})
    assert _fx(anon, "Vector") is None  # outline only: nothing for the server to draw
    admin.put("/api/defaults", json={"defaults": {}})
    os.remove(path)


def _spread(rgb):
    return max(rgb) - min(rgb)


def test_vibrancy_fades_and_strengthens_the_colour(admin, anon):
    icon = Image.open(io.BytesIO(make_png(64, (200, 60, 60)))).convert("RGBA")
    middle = (tilefx.SIZE // 2, tilefx.SIZE // 2)
    dull, normal, strong = (tilefx.render_face(icon, 20, "flat", "solid", level).getpixel(middle)[:3] for level in (0, 60, 100))
    assert _spread(dull) < _spread(normal) <= _spread(strong) and _spread(dull) < 60
    assert tilefx.render_face(icon, 20, "flat", "solid").getpixel(middle)[:3] == normal  # 60 is the built-in look
    assert sum(strong) > sum(normal)

    _setup(admin, {"tileTint": "on", "tileBadgeVibrancy": 87})
    assert "vb=85" in _fx(anon)["face"]  # stepped, so a slider drag does not draw a hundred variants
    assert anon.get(_fx(anon)["face"]).status_code == 200
    assert anon.get(_fx(anon)["face"].replace("vb=85", "vb=100")).status_code == 404
    admin.put("/api/defaults", json={"defaults": {}})
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


def test_an_app_can_have_its_own_badge_colours(admin, anon):
    grey = make_png(48, (120, 120, 120))
    assert upload(admin, "/api/icons", "mono.png", grey).status_code == 201
    icon = Image.open(io.BytesIO(grey)).convert("RGBA")
    middle = (tilefx.SIZE // 2, tilefx.SIZE // 2)
    assert tilefx.render_face(icon, 20, "flat", "solid", colour="1e90ff").getpixel(middle)[:3] == (0x1E, 0x90, 0xFF)
    assert tilefx.render_face(icon, 20, "flat", "solid", 0, colour="1e90ff").getpixel(middle)[:3] == (0x1E, 0x90, 0xFF)  # vibrancy leaves a picked colour alone
    corner = (tilefx.SIZE - 40, tilefx.SIZE - 40)
    r, g, b = tilefx.render_face(icon, 0, "flat", "duo", colour="1e90ff", colour2="ff2020").getpixel(corner)[:3]
    assert r > 200 and b < 90  # the second colour, bottom right
    assert tilefx.render_face(icon, 20, "glass", "diagonal", colour="000000").mode == "RGBA"  # a grey/black pick works too
    assert tilefx.render_logo(icon, True, 2, "auto", "dark", "", "1e90ff").mode == "RGBA"

    base = {"title": "Mono", "url": "https://mono.example", "icon": "mono.png"}
    admin.put("/api/defaults", json={"defaults": {"tileTint": "on"}})
    for bad in ("blue", "#12345", "#gggggg", 5):
        assert admin.put("/api/apps", json={"apps": [{**base, "badgeColor": bad}]}).status_code == 400
    assert admin.put("/api/apps", json={"apps": [base]}).status_code == 200
    plain = admin.get("/api/apps").get_json()["apps"][0]["fx"]
    assert admin.put("/api/apps", json={"apps": [{**base, "badgeColor": "#1E90FF", "badgeColor2": "#ff2020"}]}).status_code == 200
    stored = admin.get("/api/apps").get_json()["apps"][0]
    assert stored["badgeColor"] == "#1e90ff" and stored["badgeColor2"] == "#ff2020"
    assert "bc=1e90ff" in stored["fx"]["face"] and "bc2=ff2020" in stored["fx"]["face"] and "bc=1e90ff" in stored["fx"]["logo"]
    assert stored["fx"]["face"] != plain["face"]
    assert anon.get(stored["fx"]["face"]).status_code == 200 and anon.get(stored["fx"]["logo"]).status_code == 200
    assert anon.get(stored["fx"]["face"].replace("bc=1e90ff", "bc=ff0000")).status_code == 404  # the colour is signed too
    admin.put("/api/apps", json={"apps": []})
    admin.put("/api/defaults", json={"defaults": {}})


def test_a_small_logo_is_enlarged_to_the_same_box_as_the_others():
    from PIL import Image

    box = round(tilefx.SIZE * tilefx.LOGO_FRACTION)
    for side in (32, 1024):  # a favicon, and a picture larger than the tile
        drawn = tilefx.render_logo(Image.new("RGBA", (side, side), (200, 30, 30, 255)), False, 0, "ink", "dark", "ffb347")
        left, top, right, bottom = drawn.split()[3].getbbox()
        assert abs((right - left) - box) <= 2 and abs((bottom - top) - box) <= 2


def test_a_logo_that_fills_its_square_gets_the_rounding():
    from PIL import Image

    square = Image.new("RGBA", (64, 64), (200, 30, 30, 255))
    sharp = tilefx.render_logo(square, False, 0, "ink", "dark", "ffb347").split()[3]
    rounded = tilefx.render_logo(square, False, 0, "ink", "dark", "ffb347", None, 25).split()[3]
    left, top, right, bottom = sharp.getbbox()
    assert sharp.getpixel((left + 2, top + 2)) == 255 and rounded.getpixel((left + 2, top + 2)) == 0  # the corner is cut
    assert rounded.getpixel(((left + right) // 2, (top + bottom) // 2)) == 255 and rounded.getbbox() == sharp.getbbox()
