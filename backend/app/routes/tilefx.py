import os
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, unquote, urlsplit

from flask import Blueprint, Response, current_app, request

from .. import tilefx, tileurls
from .config import _ICON_NAME

tilefx_bp = Blueprint("tilefx", __name__)

_MODES = ("dark", "light")
_FACE_PARAMS = ("v", "r", "s", "c", "vb", "bc", "bc2")
_LOGO_PARAMS = ("v", "t", "sw", "sc", "m", "ac", "bc", "r")


def _number(value, default, lo, hi):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number)) if number == number else default  # NaN -> default


def _draw(config_dir, data_dir, kind, icon, params):
    """The picture these (already verified) parameters describe, drawn or from
    the cache - or None when there is nothing to draw it from."""
    icon_path = os.path.join(config_dir, "icons", icon)
    if not os.path.isfile(icon_path):
        return None
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
    try:
        return tilefx.get_or_render(os.path.join(data_dir, "tilefx"), _key(kind, icon, params), icon_path, kind, tint, width, color, mode, accent, radius, style, colour_style, vibrancy, colour, colour2)
    except Exception:  # an unreadable/odd image: the browser falls back to the plain logo
        return None


def _key(kind, icon, params):
    return "|".join([kind, icon] + [f"{name}={params[name]}" for name in sorted(params)])


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
    data = _draw(current_app.config["CONFIG_DIR"], current_app.config["DATA_DIR"], kind, icon, params)
    if data is None:
        return Response(status=404)
    return Response(data, mimetype="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


# --- drawing ahead ------------------------------------------------------------
# The app list hands out picture URLs; the ones not drawn yet are started on
# at once, in the background, instead of one by one as a browser gets to them
# (it only asks for the tiles on screen, a few at a time).
_ahead = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tilefx")
_queued = set()
_queued_lock = threading.Lock()


def draw_ahead(config, urls):
    """`urls`: picture URLs this server has just issued (tileurls.urls_for)."""
    config_dir, data_dir = config["CONFIG_DIR"], config["DATA_DIR"]
    cache_dir = os.path.join(data_dir, "tilefx")
    for url in urls:
        parts = urlsplit(url)
        icon, kind = (unquote(piece) for piece in parts.path.split("/")[-2:])
        params = {name: value for name, value in parse_qsl(parts.query) if name != "sig"}
        path = tilefx.cache_path(cache_dir, _key(kind, icon, params))
        if os.path.isfile(path):
            continue
        with _queued_lock:
            if path in _queued or len(_queued) > 2000:
                continue
            _queued.add(path)

        def job(path=path, kind=kind, icon=icon, params=params):
            try:
                _draw(config_dir, data_dir, kind, icon, params)
            finally:
                with _queued_lock:
                    _queued.discard(path)

        _ahead.submit(job)
