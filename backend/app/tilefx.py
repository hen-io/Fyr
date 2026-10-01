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

RENDER_VERSION = 9  # bump when the drawing changes: it is part of every cache key and image URL

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
        return tuple(_hls_rgb(0, _clamp(grey * f, 0, 1), 0) for f in (1.1, 0.8, 0.5)), None
    h, s = hue
    s = _clamp(s * 1.3, 0.82, 1.0)
    return (_hls_rgb(h, 0.56, s), _hls_rgb(h + 0.012, 0.43, s), _hls_rgb(h - 0.012, 0.27, s)), hue


def _alpha_composite_solid(base, colour, mask):
    """Paint `colour` onto RGBA `base` through L `mask`."""
    # the colour everywhere, the mask as its alpha (pasting through a mask onto a
    # transparent layer would grey the soft edges)
    layer = Image.new("RGBA", base.size, colour + (0,))
    layer.putalpha(mask)
    return Image.alpha_composite(base, layer)


BADGE_STYLES = ("glass", "bubble", "crystal", "aurora", "duo", "neon", "gloss", "frosted", "deep", "flat")

_SS = 3  # supersampling for the rounded shapes


def _shape(size, radius_pct, inset=0.0):
    """The tile's rounded square, optionally shrunk by `inset` px on every side
    (with the corner radius reduced to match, so the two outlines stay parallel)."""
    big = size * _SS
    radius = max(0.0, big * max(radius_pct, 0) / 100 - inset * _SS)
    layer = Image.new("L", (big, big), 0)
    ImageDraw.Draw(layer).rounded_rectangle((inset * _SS, inset * _SS, big - 1 - inset * _SS, big - 1 - inset * _SS), radius=radius, fill=255)
    return layer.resize((size, size), Image.LANCZOS)


def _outline(size, radius_pct, width, inset=0.0):
    """A line of even `width` px following the rounded square, `inset` px inside it."""
    big = size * _SS
    radius = max(0.0, big * max(radius_pct, 0) / 100 - inset * _SS)
    layer = Image.new("L", (big, big), 0)
    ImageDraw.Draw(layer).rounded_rectangle(
        (inset * _SS, inset * _SS, big - 1 - inset * _SS, big - 1 - inset * _SS), radius=radius, outline=255, width=max(1, round(width * _SS))
    )
    return layer.resize((size, size), Image.LANCZOS)


def _scale(mask, factor):
    return mask.point(lambda v: int(_clamp(v * factor, 0, 255)))


def _vertical(size, top, bottom):
    """L gradient from `top` (0-1) at the top edge to `bottom` at the bottom edge."""
    ramp = Image.linear_gradient("L").resize((size, size), Image.BILINEAR)
    return ramp.point(lambda v: int(255 * _clamp(top + (bottom - top) * v / 255, 0, 1)))


def _diagonal(size):
    """L gradient: 0 in the top-left corner, 255 in the bottom-right."""
    n = 64
    small = Image.new("L", (n, n))
    small.putdata([round((x + y) * 255 / (2 * n - 2)) for y in range(n) for x in range(n)])
    return small.resize((size, size), Image.BICUBIC)


def _ellipse(size, box, blur):
    layer = Image.new("L", (size, size), 0)
    ImageDraw.Draw(layer).ellipse(tuple(v * size for v in box), fill=255)
    return layer.filter(ImageFilter.GaussianBlur(size * blur)) if blur else layer


def _radial(size, cx, cy, radius):
    """L gradient: 0 at (cx, cy) (fractions of the tile), 255 at `radius` (fraction) and beyond."""
    span = max(2, round(size * radius * 2))
    grad = Image.radial_gradient("L").resize((span, span), Image.BILINEAR).point(lambda v: min(255, int(v * 1.45)))  # Pillow reaches 255 only in the corners
    layer = Image.new("L", (size, size), 255)
    layer.paste(grad, (round(size * cx - span / 2), round(size * cy - span / 2)))
    return layer


def _lighten(rgb, amount):
    return tuple(min(255, int(c + (255 - c) * amount)) for c in rgb)


def _bevel(size, radius_pct, mask, depth):
    """Strongest right at the inside of the edge, fading inwards over `depth` px -
    the same width all the way round, corners included."""
    inner = _shape(size, radius_pct, depth).filter(ImageFilter.GaussianBlur(depth * 0.55))
    return ImageChops.subtract(mask, inner)


def render_face(icon, radius_pct=0, style="glass"):
    """The tile background. Colours come from the logo only; the shape is the
    tile's rounded square. Most styles are partly see-through, so the page's
    blurred glass shows through the middle."""
    (c1, c2, c3), hue = palette(icon)
    size = SIZE
    mask = _shape(size, radius_pct)
    diagonal = _diagonal(size)

    gradient_size = int(size * 1.45)
    radial = Image.radial_gradient("L").resize((gradient_size, gradient_size), Image.BICUBIC)
    left = round(gradient_size / 2 - size * 0.5)
    top = round(gradient_size / 2 - size * 0.44)
    gray = radial.crop((left, top, left + size, top + size))  # 0 in the middle -> 255 at the rim

    if style == "flat":
        face = ImageOps.colorize(gray, black=c1, mid=c2, white=c3, midpoint=120).convert("RGBA")
        face.putalpha(mask)
        return face

    # --- colour and opacity per style -----------------------------------------
    shine = 1.0
    if style == "gloss":  # opaque, lit from straight above
        colour = ImageOps.colorize(_vertical(size, 0, 1), black=_lighten(c1, 0.22), mid=c1, white=c3, midpoint=120)
        alpha = Image.new("L", (size, size), 255)
        shine = 1.5
    elif style == "duo":  # two neighbouring hues of the logo colour, corner to corner
        if hue is None:
            first, last = _lighten(c1, 0.3), c3
        else:
            h, s = hue
            s = _clamp(s * 1.15, 0.65, 1.0)
            first, last = _hls_rgb(h - 0.07, 0.56, s), _hls_rgb(h + 0.08, 0.2, s)
        colour = ImageOps.colorize(diagonal, black=first, mid=c1, white=last, midpoint=120)
        alpha = gray.point(lambda v: int(255 * (0.74 + 0.2 * (v / 255) ** 1.5)))
    elif style == "frosted":  # pale, mostly haze
        colour = Image.new("RGB", (size, size), _lighten(c1, 0.45))
        alpha = gray.point(lambda v: int(255 * (0.2 + 0.26 * (v / 255) ** 1.5)))
        shine = 1.2
    elif style == "deep":  # dark glass with the colour glowing up from below
        colour = ImageOps.colorize(_vertical(size, 0, 1), black=c3, mid=c2, white=c1, midpoint=140)
        alpha = gray.point(lambda v: int(255 * (0.7 + 0.22 * (v / 255) ** 1.5)))
        shine = 0.7
    elif style == "bubble":  # a droplet: lit near the top-left, curving away into shade
        ball = _radial(size, 0.34, 0.28, 0.95)
        colour = ImageOps.colorize(ball, black=_lighten(c1, 0.42), mid=c1, white=c3, midpoint=95)
        alpha = gray.point(lambda v: int(255 * (0.78 + 0.18 * (v / 255) ** 1.5)))
        shine = 1.25
    elif style == "crystal":  # two cut planes meeting on the diagonal
        colour = ImageOps.colorize(diagonal, black=_lighten(c1, 0.3), mid=c1, white=c3, midpoint=128)
        alpha = gray.point(lambda v: int(255 * (0.72 + 0.22 * (v / 255) ** 1.5)))
        shine = 1.1
    elif style == "aurora":  # three neighbouring hues melting into each other
        if hue is None:
            spots = [(_lighten(c1, 0.35), 0.2, 0.25), (c2, 0.82, 0.3), (c1, 0.5, 0.9)]
        else:
            h, s = hue
            s = _clamp(s * 1.3, 0.82, 1.0)
            spots = [(_hls_rgb(h - 0.1, 0.6, s), 0.18, 0.22), (_hls_rgb(h + 0.11, 0.52, s), 0.85, 0.3), (_hls_rgb(h + 0.02, 0.6, s), 0.5, 0.92)]
        colour = Image.new("RGB", (size, size), c2)
        for rgb, cx, cy in spots:
            spot = _radial(size, cx, cy, 0.62).point(lambda v: 255 - v)
            colour.paste(Image.new("RGB", (size, size), rgb), (0, 0), spot)
        alpha = gray.point(lambda v: int(255 * (0.8 + 0.16 * (v / 255) ** 1.5)))
    elif style == "neon":  # near-black glass, the colour lives in a glowing edge
        dark = tuple(int(c * 0.22) for c in c3)
        colour = ImageOps.colorize(gray, black=tuple(int(c * 0.55) for c in c3), mid=dark, white=dark, midpoint=90)
        alpha = gray.point(lambda v: int(255 * (0.74 + 0.2 * (v / 255) ** 1.5)))
        shine = 0.55
    else:  # glass: light enters top-left, the colour deepens towards bottom-right
        colour = ImageOps.colorize(diagonal, black=_lighten(c1, 0.2), mid=c1, white=c3, midpoint=105)
        alpha = gray.point(lambda v: int(255 * (0.66 + 0.28 * (v / 255) ** 1.6)))

    face = colour.convert("RGBA")
    face.putalpha(ImageChops.multiply(alpha, mask))

    if style == "frosted":
        face = _alpha_composite_solid(face, (255, 255, 255), ImageChops.multiply(_vertical(size, 0.2, 0.05), mask))

    # --- shared 3D glass shading ----------------------------------------------
    # a faint lens of light behind the logo so it floats above the glass
    lens = ImageChops.multiply(_ellipse(size, (0.2, 0.16, 0.8, 0.76), 0.1), mask)
    face = _alpha_composite_solid(face, _lighten(c1, 0.5), _scale(lens, 0.16))

    # thickness: an even band inside the edge, dark where the light leaves
    # (bottom-right) and bright where it enters (top-left)
    bevel = _bevel(size, radius_pct, mask, size * 0.05)
    leaving = diagonal.point(lambda v: int(255 * _clamp((v - 95) / 160, 0, 1)))
    entering = diagonal.point(lambda v: int(255 * _clamp((150 - v) / 150, 0, 1)))
    face = _alpha_composite_solid(face, c3, _scale(ImageChops.multiply(bevel, leaving), 0.5))
    face = _alpha_composite_solid(face, (255, 255, 255), _scale(ImageChops.multiply(bevel, entering), 0.34 * shine))

    # soft glare over the upper part (no hard lower edge)
    glare = ImageChops.multiply(_ellipse(size, (-0.3, -0.75, 1.3, 0.5), 0.045), _vertical(size, 0.36 * shine, 0.0))
    face = _alpha_composite_solid(face, (255, 255, 255), ImageChops.multiply(glare, mask))

    # a crisp second highlight just inside the top edge - the glass's inner surface
    inner_line = _outline(size, radius_pct, size * 0.008, size * 0.03).filter(ImageFilter.GaussianBlur(size * 0.003))
    top_only = _vertical(size, 1.6, -0.9)  # full at the top, gone by about two thirds down
    face = _alpha_composite_solid(face, (255, 255, 255), _scale(ImageChops.multiply(inner_line, top_only), 0.3 * shine))

    # the rim itself: one thin even line, bright where light enters and (a little) where it leaves
    rim = _outline(size, radius_pct, size * 0.006)
    two_ended = diagonal.point(lambda v: int(255 * (0.16 + 0.74 * (1 - v / 255) ** 2 + 0.3 * (v / 255) ** 3)))
    face = _alpha_composite_solid(face, (255, 255, 255), ImageChops.multiply(ImageChops.multiply(rim, two_ended), mask))

    if style == "bubble":
        # a tight, bright reflection of the light source, and light bouncing back off the far side
        spark = ImageChops.multiply(_ellipse(size, (0.2, 0.13, 0.4, 0.22), 0.012), mask)
        face = _alpha_composite_solid(face, (255, 255, 255), _scale(spark, 0.9))
        face = _alpha_composite_solid(face, _lighten(c1, 0.6), _scale(ImageChops.multiply(_bevel(size, radius_pct, mask, size * 0.09), leaving), 0.5))
    elif style == "crystal":
        # the upper-left plane catches the light; a fine bright line where the planes meet
        plane = Image.new("L", (size * _SS, size * _SS), 0)
        ImageDraw.Draw(plane).polygon([(0, 0), (size * _SS, 0), (0, size * _SS)], fill=255)
        plane = plane.resize((size, size), Image.LANCZOS)
        face = _alpha_composite_solid(face, (255, 255, 255), _scale(ImageChops.multiply(plane, mask), 0.14))
        seam = Image.new("L", (size * _SS, size * _SS), 0)
        ImageDraw.Draw(seam).line([(size * _SS, 0), (0, size * _SS)], fill=255, width=round(size * 0.006 * _SS))
        seam = seam.resize((size, size), Image.LANCZOS)
        face = _alpha_composite_solid(face, (255, 255, 255), _scale(ImageChops.multiply(seam, mask), 0.4))
    elif style == "neon":
        vivid = _lighten(c1, 0.12)
        face = _alpha_composite_solid(face, vivid, _scale(_bevel(size, radius_pct, mask, size * 0.11), 0.85))
        face = _alpha_composite_solid(face, _lighten(c1, 0.55), ImageChops.multiply(_outline(size, radius_pct, size * 0.012), mask))
        face = _alpha_composite_solid(face, vivid, _scale(ImageChops.multiply(_ellipse(size, (0.1, 0.72, 0.9, 1.3), 0.08), mask), 0.5))
    return face


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
        glow = base_alpha.filter(ImageFilter.GaussianBlur(size * 0.05)).point(lambda v: int(v * 0.3))
        out = _alpha_composite_solid(out, glow_rgb, glow)
        shadow = ImageChops.offset(base_alpha, 0, round(size * 0.028)).filter(ImageFilter.GaussianBlur(size * 0.028)).point(lambda v: int(v * 0.6))
        out = _alpha_composite_solid(out, c3, shadow)

    if stroke_width > 0:
        out = _alpha_composite_solid(out, _stroke_rgb(stroke_color, hue, mode, accent), ring)

    return Image.alpha_composite(out, canvas)


def _encode(image, kind):
    buffer = io.BytesIO()
    if kind == "face":
        image.save(buffer, "WEBP", quality=90, alpha_quality=100, method=4)
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


def get_or_render(cache_dir, key, icon_path, kind, tint, stroke_width, stroke_color, mode, accent, radius_pct=0, style="glass"):
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
            data = _encode(render_face(icon, radius_pct, style), "face")
        else:
            data = _encode(render_logo(icon, tint, stroke_width, stroke_color, mode, accent), "logo")
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
        _trim_cache(cache_dir)
        return data
