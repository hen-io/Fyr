import os

from flask import Blueprint, Response, current_app, request

from .. import tilefx, tileurls
from .config import _ICON_NAME

tilefx_bp = Blueprint("tilefx", __name__)

_MODES = ("dark", "light")
_FACE_PARAMS = ("v", "r", "s", "c", "vb", "bc", "bc2")
_LOGO_PARAMS = ("v", "t", "sw", "sc", "m", "ac", "bc")


def _number(value, default, lo, hi):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number)) if number == number else default  # NaN -> default


@tilefx_bp.route("/api/tilefx/<icon>/<kind>")
def tile_image(icon, kind):
    """A tile's pre-rendered background ("face") or logo layer ("logo").

    Public, but it only answers URLs this server issued itself (tileurls.py):
    the parameters must carry a valid signature, so nobody can ask for
    arbitrary variants and keep the server busy drawing them. The response is
    cached for good - a changed icon or setting gives a different URL."""
    if kind not in ("face", "logo") or not _ICON_NAME.match(icon) or (kind == "logo" and icon.lower().endswith(".svg")):
        return Response(status=404)
    names = _FACE_PARAMS if kind == "face" else _LOGO_PARAMS
    params = {name: request.args[name] for name in names if name in request.args}
    if not tileurls.verify(current_app.config["SECRET_KEY"], kind, icon, params, request.args.get("sig")):
        return Response(status=404)
    icon_path = os.path.join(current_app.config["CONFIG_DIR"], "icons", icon)
    if not os.path.isfile(icon_path):
        return Response(status=404)

    tint = params.get("t") == "1"
    width = round(_number(params.get("sw"), 0, 0, 6) * 2) / 2
    color = params.get("sc") if params.get("sc") in tilefx.STROKE_COLORS else "ink"
    mode = params.get("m") if params.get("m") in _MODES else "dark"
    accent = params.get("ac", "")
    if len(accent) != 6 or any(c not in "0123456789abcdefABCDEF" for c in accent):
        accent = ""
    radius = round(_number(params.get("r"), 0, 0, 50) * 2) / 2
    style = params.get("s") if params.get("s") in tilefx.BADGE_STYLES else "glass"
    colour_style = params.get("c") if params.get("c") in tilefx.BADGE_COLOURS else "diagonal"
    vibrancy = _number(params.get("vb"), tilefx.DEFAULT_VIBRANCY, 0, 100)
    colour, colour2 = (tileurls.hex_colour("#" + params.get(name, "")) for name in ("bc", "bc2"))
    if kind == "logo" and not tint and width <= 0:
        return Response(status=404)

    key = "|".join([kind, icon] + [f"{name}={params[name]}" for name in sorted(params)])
    try:
        data = tilefx.get_or_render(
            os.path.join(current_app.config["DATA_DIR"], "tilefx"), key, icon_path, kind, tint, width, color, mode, accent, radius, style, colour_style, vibrancy, colour, colour2
        )
    except Exception:  # an unreadable/odd image: the browser falls back to the plain logo
        return Response(status=404)
    return Response(data, mimetype="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})
