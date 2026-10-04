"""Which tile-effect pictures an app gets, and the signed URLs for them.

The pictures (see tilefx.py) are drawn on demand by a public endpoint. To keep
that endpoint from being a way to make the server draw anything at all, the
only URLs it honours are the ones built here: every URL carries an HMAC over
its own parameters, made with the server's secret. What goes into the
parameters comes from the admin's settings - never from the visitor - so each
picture is drawn once and is the same for everyone."""

import hashlib
import hmac
import os
from urllib.parse import quote, urlencode

from . import tilefx

# The built-in value of each setting that shapes a badge. Must match the
# `default` of the same key in the frontend's constants/settings.js (the
# backend test suite compares the two).
SETTING_DEFAULTS = {
    "tileTint": "off",
    "tileBadgeStyle": "glass",
    "tileBadgeColor": "diagonal",
    "tileBadgeVibrancy": 60,
    "roundness": 20,
    "logoStrokeWidth": 0,
    "logoStrokeColor": "ink",
    "palette": "ember",
    "colorMode": "dark",
}

# The accent colour of each palette - a mirror of PALETTE_ACCENTS in the
# frontend's constants/appearance.js (also compared by the test suite). Used
# when an outline is set to "theme colour".
PALETTE_ACCENTS = {
    "ember": "ffb347",
    "nordic": "7cc4ff",
    "deepsea": "4f9cf0",
    "midnight": "8b9dff",
    "forest": "8fd18a",
    "rose": "f29bb8",
    "terminal": "39ff8a",
    "paper": "c8894a",
    "neon": "00f0ff",
    "amethyst": "c39bff",
    "sunset": "ff7a59",
    "ocean": "19d3c5",
    "aurora": "6affb0",
    "graphite": "9db4c9",
    "ruby": "ff5a6e",
    "mint": "5ee6b5",
    "lavender": "b9a4ff",
    "slate": "8fb0d9",
    "mocha": "d9a066",
    "volt": "f5e642",
    "abyss": "3f7fd6",
    "candy": "ff3d8b",
    "electric": "3d7bff",
    "tropic": "00b89f",
    "citrus": "ff8a00",
    "grape": "a24dff",
    "flamingo": "ff5a5f",
    "lagoon": "0fa3ff",
    "prism": "e23bd0",
}

_RASTER = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico")
_VECTOR = (".svg",)


def hex_colour(value):
    """"rrggbb" for "#rrggbb" (any case), else None."""
    if isinstance(value, str) and len(value) == 7 and value[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in value[1:]):
        return value[1:].lower()
    return None


def radius_percent(roundness):
    """A tile's corner radius as a share of its size - the same formula as
    tileRadiusPercent() in the frontend's constants/appearance.js."""
    try:
        return min(50.0, round(float(roundness) * 9) / 10)
    except (TypeError, ValueError):
        return 18.0


def signature(secret, kind, icon, params):
    message = "|".join([kind, icon] + [f"{key}={params[key]}" for key in sorted(params)])
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def verify(secret, kind, icon, params, given):
    return isinstance(given, str) and hmac.compare_digest(signature(secret, kind, icon, params), given)


def _url(secret, kind, icon, params):
    params = {key: str(value) for key, value in params.items()}
    return f"/api/tilefx/{quote(icon)}/{kind}?{urlencode({**params, 'sig': signature(secret, kind, icon, params)})}"


def settings(defaults):
    """The admin's values for the settings above, falling back to the built-ins."""
    merged = dict(SETTING_DEFAULTS)
    for key, fallback in SETTING_DEFAULTS.items():
        value = (defaults or {}).get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(fallback, str) and isinstance(value, str) or not isinstance(fallback, str) and isinstance(value, (int, float)):
            merged[key] = value
    if merged["tileBadgeStyle"] not in tilefx.BADGE_STYLES:
        merged["tileBadgeStyle"] = SETTING_DEFAULTS["tileBadgeStyle"]
    if merged["tileBadgeColor"] not in tilefx.BADGE_COLOURS:
        merged["tileBadgeColor"] = SETTING_DEFAULTS["tileBadgeColor"]
    if merged["logoStrokeColor"] not in tilefx.STROKE_COLORS:
        merged["logoStrokeColor"] = SETTING_DEFAULTS["logoStrokeColor"]
    return merged


def urls_for(app, chosen, icons_dir, secret):
    """{"face": url|None, "logo": url, "round": percent} for one app, or None
    when it gets no drawn effects (no icon file, or neither tint nor outline
    is on). An SVG icon gets the badge only: its logo
    stays the SVG itself, drawn (and outlined) by the browser."""
    icon = app.get("icon")
    if not isinstance(icon, str) or not icon.lower().endswith(_RASTER + _VECTOR):
        return None
    tint = chosen["tileTint"] == "on"
    vector = icon.lower().endswith(_VECTOR)
    if vector and not tint:
        return None  # an SVG logo is drawn by the browser; only its badge comes from here
    width = app.get("iconStroke")
    if isinstance(width, bool) or not isinstance(width, (int, float)):
        width = chosen["logoStrokeWidth"]
    width = round(max(0.0, min(6.0, float(width))) * 2) / 2
    if not tint and width <= 0:
        return None
    try:
        version = f"{int(os.path.getmtime(os.path.join(icons_dir, icon)))}-{tilefx.RENDER_VERSION}"
    except OSError:
        return None

    color = app.get("iconStrokeColor") if app.get("iconStrokeColor") in tilefx.STROKE_COLORS else chosen["logoStrokeColor"]
    radius = radius_percent(chosen["roundness"])
    logo = {"v": version, "t": int(tint), "sw": width, "sc": color, "r": radius}
    if color in ("ink", "auto"):
        logo["m"] = "light" if chosen["colorMode"] == "light" else "dark"
    if color == "accent":
        logo["ac"] = PALETTE_ACCENTS.get(chosen["palette"], PALETTE_ACCENTS["ember"])
    vibrancy = int(max(0, min(100, round(float(chosen["tileBadgeVibrancy"]) / 5) * 5)))
    face = {"v": version, "r": radius, "s": chosen["tileBadgeStyle"], "c": chosen["tileBadgeColor"], "vb": vibrancy}
    # Colours the admin picked for this app, instead of the logo's own.
    first, second = hex_colour(app.get("badgeColor")), hex_colour(app.get("badgeColor2"))
    if first:
        face["bc"] = logo["bc"] = first
    if second:
        face["bc2"] = second
    return {
        "face": _url(secret, "face", icon, face) if tint else None,
        "logo": None if vector else _url(secret, "logo", icon, logo),
        "round": radius,
    }
