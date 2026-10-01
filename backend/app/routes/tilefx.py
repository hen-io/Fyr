import os

from flask import Blueprint, Response, current_app, request

from .. import tilefx
from .config import _ICON_NAME

tilefx_bp = Blueprint("tilefx", __name__)

_MODES = ("dark", "light")


def _number(value, default, lo, hi):
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


@tilefx_bp.route("/api/tilefx/<icon>/<kind>")
def tile_image(icon, kind):
    """A tile's pre-rendered background ("face") or logo layer ("logo"). The
    parameters are all part of the cache key; `v` is the icon file's mtime, so
    a replaced icon gets a new URL and the response can be cached for good."""
    if kind not in ("face", "logo") or not _ICON_NAME.match(icon) or icon.lower().endswith(".svg"):
        return Response(status=404)
    icon_path = os.path.join(current_app.config["CONFIG_DIR"], "icons", icon)
    if not os.path.isfile(icon_path):
        return Response(status=404)

    tint = request.args.get("t") == "1"
    width = round(_number(request.args.get("sw"), 0, 0, 6) * 2) / 2
    color = request.args.get("sc", "ink")
    if color not in tilefx.STROKE_COLORS:
        color = "ink"
    mode = request.args.get("m", "dark")
    if mode not in _MODES:
        mode = "dark"
    accent = (request.args.get("ac") or "")[:6]
    if len(accent) != 6 or any(c not in "0123456789abcdefABCDEF" for c in accent):
        accent = ""
    if kind == "logo" and not tint and width <= 0:
        return Response(status=404)  # nothing to render: the client shows the plain logo

    radius = round(_number(request.args.get("r"), 0, 0, 50) * 2) / 2
    style = request.args.get("s", "glass")
    if style not in tilefx.BADGE_STYLES:
        style = "glass"
    colour_style = request.args.get("c", "diagonal")
    if colour_style not in tilefx.BADGE_COLOURS:
        colour_style = "diagonal"
    version = f"{int(os.path.getmtime(icon_path))}-{tilefx.RENDER_VERSION}"
    if kind == "face":
        key = f"face|{icon}|{version}|{radius}|{style}|{colour_style}"
    else:
        key = f"logo|{icon}|{version}|{int(tint)}|{width}|{color}|{mode if color in ('ink', 'auto') else '-'}|{accent if color == 'accent' else '-'}"
    try:
        data = tilefx.get_or_render(
            os.path.join(current_app.config["DATA_DIR"], "tilefx"), key, icon_path, kind, tint, width, color, mode, accent, radius, style, colour_style
        )
    except Exception:  # an unreadable/odd image: let the client fall back to the plain logo
        return Response(status=404)
    return Response(data, mimetype="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})
