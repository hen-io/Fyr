"""Renders the per-app tile effects (logo outline, icon-coloured "liquid glass"
face, glow and sheen) once on the server, so browsers only show two cached
images per app instead of computing gradients and filters for every tile.

  face  - the tile background: a vibrant gradient taken from the logo's own
          colours with a glossy highlight and a soft bounce light
  logo  - the logo itself on a transparent square (same size as the tile face):
          outline, coloured glow, drop shadow and a light sheen baked in
"""

import colorsys
import hashlib
import io
import math
import os
import threading

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

SIZE = 420  # image px; a tile is at most ~210 CSS px wide, so this is sharp at 2x
LOGO_FRACTION = 0.64  # logo box as a share of the tile side
LOGO_LIFT = 0.012  # the logo sits a touch above centre (the tile label is below)
UNIT = SIZE / 180.0  # image px per CSS px, for the outline width

STROKE_COLORS = ("ink", "accent", "white", "black", "auto")

_render_lock = threading.Lock()
_MAX_CACHED = 3000


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _hls_rgb(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, _clamp(l, 0, 1), _clamp(s, 0, 1))
    return (round(r * 255), round(g * 255), round(b * 255))


def _hex_rgb(value, fallback):
    value = (value or "").lstrip("#")
    if len(value) == 6:
        try:
            return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return fallback


def load_icon(path):
    image = Image.open(path)
    image.load()
    return image.convert("RGBA")


def dominant_hue(icon):
    """(hue 0-1, saturation) of the logo's main vivid colour, or None for a
    grey/black/white logo. Saturated, opaque pixels vote for their hue bin."""
    small = icon.resize((48, 48), Image.LANCZOS)
    bins = [[0.0, 0.0, 0.0] for _ in range(12)]  # weight, hue*weight, sat*weight
    for r, g, b, a in small.getdata():
        if a < 128:
            continue
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if s * (1 - abs(2 * l - 1)) < 0.12 or l < 0.12 or l > 0.92:
            continue
        weight = s * (a / 255)
        slot = bins[min(11, int(h * 12))]
        slot[0] += weight
        slot[1] += h * weight
        slot[2] += s * weight
    best = max(bins, key=lambda slot: slot[0])
    if best[0] <= 0:
        return None
    return best[1] / best[0], best[2] / best[0]


def average_grey(icon):
    small = icon.resize((24, 24), Image.LANCZOS)
    total = count = 0
    for r, g, b, a in small.getdata():
        if a >= 128:
            total += (r + g + b) / 3
            count += 1
    return (total / count / 255) if count else 0.5


def palette(icon):
    """Three colours from the logo's own hue: vivid centre, darker middle, deep edge."""
    hue = dominant_hue(icon)
    if hue is None:
        grey = _clamp(average_grey(icon), 0.25, 0.75)
        return tuple(_hls_rgb(0, grey * f, 0) for f in (0.78, 0.5, 0.26)), None
    h, s = hue
    s = _clamp(s * 1.15, 0.62, 1.0)
    return (_hls_rgb(h, 0.46, s), _hls_rgb(h + 0.01, 0.29, s), _hls_rgb(h - 0.01, 0.15, s * 0.92)), hue


def _alpha_composite_solid(base, colour, mask):
    """Paint `colour` onto RGBA `base` through L `mask`."""
    solid = Image.new("RGBA", base.size, colour + (255,))
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer.paste(solid, (0, 0), mask)
    return Image.alpha_composite(base, layer)


def render_face(icon):
    (c1, c2, c3), _ = palette(icon)
    size = SIZE
    gradient_size = int(size * 1.45)
    radial = Image.radial_gradient("L").resize((gradient_size, gradient_size), Image.BICUBIC)
    left = round(gradient_size / 2 - size * 0.5)
    top = round(gradient_size / 2 - size * 0.47)
    gray = radial.crop((left, top, left + size, top + size))
    face = ImageOps.colorize(gray, black=c1, mid=c2, white=c3, midpoint=105).convert("RGBA")

    # soft edge vignette for depth
    vignette = gray.point(lambda v: int(_clamp((v - 150) * 1.5, 0, 255) * 0.32))
    face = _alpha_composite_solid(face, (0, 0, 0), vignette)

    # bounce light from below, in the logo's own (lighter) colour
    bounce = Image.new("L", (size, size), 0)
    ImageDraw.Draw(bounce).ellipse((size * 0.08, size * 0.72, size * 0.92, size * 1.35), fill=255)
    bounce = bounce.filter(ImageFilter.GaussianBlur(size * 0.07)).point(lambda v: int(v * 0.35))
    light = tuple(min(255, int(c * 1.5) + 18) for c in c1)
    face = _alpha_composite_solid(face, light, bounce)

    # glossy highlight across the top, fading downwards (the "glass" sheen)
    gloss = Image.new("L", (size, size), 0)
    ImageDraw.Draw(gloss).ellipse((-size * 0.3, -size * 0.85, size * 1.3, size * 0.4), fill=255)
    gloss = gloss.filter(ImageFilter.GaussianBlur(size * 0.045))
    fade = ImageOps.invert(Image.linear_gradient("L").resize((size, size), Image.BILINEAR))
    gloss = ImageChops.multiply(gloss, fade).point(lambda v: int(v * 0.27))
    face = _alpha_composite_solid(face, (255, 255, 255), gloss)

    # thin bright rim along the top edge and dark along the bottom
    rim = Image.new("L", (size, size), 0)
    ImageDraw.Draw(rim).rectangle((0, 0, size, size * 0.018), fill=70)
    face = _alpha_composite_solid(face, (255, 255, 255), rim.filter(ImageFilter.GaussianBlur(size * 0.006)))
    return face.convert("RGB")


def _ring(alpha, radius):
    """Uniform outline: the logo's alpha copied at 32 evenly spaced offsets on a
    circle, merged in parallel, so it is the same thickness in every direction."""
    ring = Image.new("L", alpha.size, 0)
    steps = 32
    for i in range(steps):
        angle = 2 * math.pi * i / steps
        ring = ImageChops.lighter(ring, ImageChops.offset(alpha, round(math.cos(angle) * radius), round(math.sin(angle) * radius)))
    return ring.filter(ImageFilter.GaussianBlur(0.9)).point(lambda v: 255 if v > 150 else int(v * 255 / 150))


def _stroke_rgb(key, hue, mode, accent):
    if key == "white":
        return (255, 255, 255)
    if key == "black":
        return (0, 0, 0)
    if key == "accent":
        return _hex_rgb(accent, (255, 179, 71))
    if key == "auto":
        if hue is None:
            return (245, 245, 247) if mode == "dark" else (30, 32, 44)
        h, s = hue
        return _hls_rgb(h, 0.8 if mode == "dark" else 0.22, _clamp(s, 0.6, 1.0))
    return (245, 245, 247) if mode == "dark" else (20, 23, 36)  # "ink": contrast to the page


def render_logo(icon, tint, stroke_width, stroke_color, mode, accent):
    size = SIZE
    box = round(size * LOGO_FRACTION)
    logo = icon.copy()
    logo.thumbnail((box, box), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(logo, ((size - logo.width) // 2, round((size - logo.height) / 2 - size * LOGO_LIFT)), logo)
    alpha = canvas.split()[3]
    (c1, c2, c3), hue = palette(icon)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    base_alpha = alpha
    if stroke_width > 0:
        ring = _ring(alpha, max(1.0, stroke_width * UNIT))
        base_alpha = ring  # glow and shadow follow the outlined shape

    if tint:
        glow_rgb = tuple(min(255, int(c * 1.35) + 25) for c in c1)
        glow = base_alpha.filter(ImageFilter.GaussianBlur(size * 0.05)).point(lambda v: int(v * 0.6))
        out = _alpha_composite_solid(out, glow_rgb, glow)
        shadow = ImageChops.offset(base_alpha, 0, round(size * 0.028)).filter(ImageFilter.GaussianBlur(size * 0.028)).point(lambda v: int(v * 0.62))
        out = _alpha_composite_solid(out, c3, shadow)

    if stroke_width > 0:
        out = _alpha_composite_solid(out, _stroke_rgb(stroke_color, hue, mode, accent), ring)

    if tint:
        # light sheen across the top of the logo itself, a little shade at the bottom
        sheen = ImageChops.multiply(ImageOps.invert(Image.linear_gradient("L").resize((size, size), Image.BILINEAR)), alpha).point(lambda v: int(v * 0.26))
        shade = ImageChops.multiply(Image.linear_gradient("L").resize((size, size), Image.BILINEAR), alpha).point(lambda v: int(v * 0.16))
        canvas = _alpha_composite_solid(canvas, (255, 255, 255), sheen)
        canvas = _alpha_composite_solid(canvas, c3, shade)
    return Image.alpha_composite(out, canvas)


def _encode(image, kind):
    buffer = io.BytesIO()
    if kind == "face":
        image.save(buffer, "WEBP", quality=88, method=4)
    else:
        image.save(buffer, "WEBP", quality=92, alpha_quality=100, method=4)
    return buffer.getvalue()


def cache_path(cache_dir, key):
    return os.path.join(cache_dir, hashlib.sha256(key.encode("utf-8")).hexdigest()[:40] + ".webp")


def _trim_cache(cache_dir):
    try:
        entries = [os.path.join(cache_dir, n) for n in os.listdir(cache_dir)]
        if len(entries) <= _MAX_CACHED:
            return
        entries.sort(key=lambda p: os.path.getmtime(p))
        for path in entries[: len(entries) - _MAX_CACHED + 200]:
            os.remove(path)
    except OSError:
        pass


def get_or_render(cache_dir, key, icon_path, kind, tint, stroke_width, stroke_color, mode, accent):
    """The rendered WebP for `key`, from the disk cache or freshly drawn."""
    os.makedirs(cache_dir, exist_ok=True)
    path = cache_path(cache_dir, key)
    if os.path.isfile(path):
        os.utime(path, None)
        with open(path, "rb") as handle:
            return handle.read()
    with _render_lock:  # one render at a time: a burst of new icons must not spike the CPU
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                return handle.read()
        icon = load_icon(icon_path)
        if kind == "face":
            data = _encode(render_face(icon), "face")
        else:
            data = _encode(render_logo(icon, tint, stroke_width, stroke_color, mode, accent), "logo")
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
        _trim_cache(cache_dir)
        return data
