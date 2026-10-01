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

RENDER_VERSION = 12  # bump when the drawing changes: it is part of every cache key and image URL

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


def _hue_bins(icon):
    """Saturated, opaque pixels vote for their hue (12 bins): [weight, hue*w, sat*w]."""
    small = icon.resize((48, 48), Image.LANCZOS)
    bins = [[0.0, 0.0, 0.0] for _ in range(12)]
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
    return bins


def dominant_hue(icon):
    """(hue 0-1, saturation) of the logo's main vivid colour, or None for a
    grey/black/white logo."""
    best = max(_hue_bins(icon), key=lambda slot: slot[0])
    if best[0] <= 0:
        return None
    return best[1] / best[0], best[2] / best[0]


def secondary_hue(icon):
    """The logo's second colour - only when it is clearly there (at least a
    quarter as strong as the main one and a different hue), else None."""
    bins = _hue_bins(icon)
    first = max(range(12), key=lambda i: bins[i][0])
    if bins[first][0] <= 0:
        return None
    others = [i for i in range(12) if min((i - first) % 12, (first - i) % 12) >= 2 and bins[i][0] >= bins[first][0] * 0.25]
    if not others:
        return None
    second = bins[max(others, key=lambda i: bins[i][0])]
    return second[1] / second[0], second[2] / second[0]


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


BADGE_STYLES = ("glass", "bubble", "crystal", "jelly", "dome", "lens", "pillow", "ring", "ridge", "chisel", "inset", "metal", "gloss", "neon", "flat")  # the 3D shading
BADGE_COLOURS = ("diagonal", "radial", "vertical", "solid", "duo", "dark", "pale", "neutral")  # how the logo colour is laid out

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


def render_face(icon, radius_pct=0, style="glass", colour_style="diagonal"):
    """The tile background: `colour_style` decides how the logo's own colours
    are laid out, `style` decides the 3D shading on top. The shape is the
    tile's rounded square."""
    (c1, c2, c3), hue = palette(icon)
    size = SIZE
    mask = _shape(size, radius_pct)
    diagonal = _diagonal(size)

    gradient_size = int(size * 1.45)
    radial = Image.radial_gradient("L").resize((gradient_size, gradient_size), Image.BICUBIC)
    left = round(gradient_size / 2 - size * 0.5)
    top = round(gradient_size / 2 - size * 0.44)
    gray = radial.crop((left, top, left + size, top + size))  # 0 in the middle -> 255 at the rim

    # --- colour ----------------------------------------------------------------
    alpha = Image.new("L", (size, size), 255)
    if colour_style == "radial":  # bright in the middle, deep at the edge
        colour = ImageOps.colorize(gray, black=_lighten(c1, 0.14), mid=c1, white=c3, midpoint=95)
    elif colour_style == "vertical":  # light at the top, deep at the bottom
        colour = ImageOps.colorize(_vertical(size, 0, 1), black=_lighten(c1, 0.22), mid=c1, white=c3, midpoint=118)
    elif colour_style == "solid":  # one even colour
        colour = Image.new("RGB", (size, size), c1)
    elif colour_style == "duo":  # the logo's own two main colours, corner to corner
        other = secondary_hue(icon)
        if hue is not None and other is not None:
            last = _hls_rgb(other[0], 0.46, _clamp(other[1] * 1.3, 0.8, 1.0))
            colour = ImageOps.colorize(diagonal, black=_lighten(c1, 0.12), mid=c1, white=last, midpoint=110)
        else:  # a one-colour logo: two tones of that colour
            colour = ImageOps.colorize(diagonal, black=_lighten(c1, 0.3), mid=c1, white=c3, midpoint=120)
    elif colour_style == "dark":  # dark glass, the colour glowing up from below
        deep = tuple(int(c * 0.45) for c in c3)
        colour = ImageOps.colorize(_vertical(size, 0, 1), black=deep, mid=c3, white=c1, midpoint=150)
    elif colour_style == "pale":  # a light pastel of the logo colour, a little see-through
        colour = ImageOps.colorize(diagonal, black=_lighten(c1, 0.72), mid=_lighten(c1, 0.5), white=_lighten(c2, 0.25), midpoint=125)
        alpha = gray.point(lambda v: int(255 * (0.62 + 0.3 * (v / 255) ** 1.5)))
    elif colour_style == "neutral":  # no colour at all: smoked grey glass
        colour = ImageOps.colorize(diagonal, black=(150, 154, 164), mid=(96, 100, 112), white=(48, 50, 60), midpoint=118)
    else:  # diagonal: light enters top-left, the colour deepens towards bottom-right
        colour = ImageOps.colorize(diagonal, black=_lighten(c1, 0.2), mid=c1, white=c3, midpoint=105)

    face = colour.convert("RGBA")
    face.putalpha(ImageChops.multiply(alpha, mask))
    if style == "flat":
        return face

    # --- 3D shading ------------------------------------------------------------
    paint = _alpha_composite_solid
    white = (255, 255, 255)
    leaving = diagonal.point(lambda v: int(255 * _clamp((v - 95) / 160, 0, 1)))  # bottom-right
    entering = diagonal.point(lambda v: int(255 * _clamp((150 - v) / 150, 0, 1)))  # top-left
    corner = diagonal.point(lambda v: int(255 * _clamp((115 - v) / 115, 0, 1) ** 2))  # top-left corner only
    within = lambda layer: ImageChops.multiply(layer, mask)  # noqa: E731
    both = ImageChops.multiply

    def rim(strength=1.0):
        line = _outline(size, radius_pct, size * 0.006)
        two_ended = diagonal.point(lambda v: int(255 * _clamp(strength * (0.2 + 0.74 * (1 - v / 255) ** 2 + 0.36 * (v / 255) ** 3), 0, 1)))
        return within(both(line, two_ended))

    if style == "pillow":  # soft and puffy: a wide rounded edge, no glare
        bevel = _bevel(size, radius_pct, mask, size * 0.14)
        face = paint(face, c3, _scale(both(bevel, leaving), 0.8))
        face = paint(face, white, _scale(both(bevel, entering), 0.62))
        face = paint(face, white, _scale(within(_ellipse(size, (0.18, 0.14, 0.82, 0.78), 0.12)), 0.1))
        return paint(face, white, rim(0.6))

    if style == "inset":  # pressed into the page: shadow under the top-left lip, light on the far side
        bevel = _bevel(size, radius_pct, mask, size * 0.09)
        face = paint(face, (0, 0, 0), _scale(both(bevel, entering), 0.62))
        face = paint(face, white, _scale(both(bevel, leaving), 0.4))
        face = paint(face, (0, 0, 0), _scale(within(_outline(size, radius_pct, size * 0.008)), 0.5))
        lip = _outline(size, radius_pct, size * 0.006, size * 0.004)
        return paint(face, white, _scale(within(both(lip, leaving)), 0.75))

    if style == "ring":  # a raised frame around a sunken middle
        frame = size * 0.085
        band = ImageChops.subtract(mask, _shape(size, radius_pct, frame))
        face = paint(face, white, _scale(both(band, entering), 0.4))
        face = paint(face, c3, _scale(both(band, leaving), 0.5))
        # the step down into the middle: shadow on the lit side, light on the far side
        step = _bevel(size, radius_pct, _shape(size, radius_pct, frame), size * 0.05)
        face = paint(face, (0, 0, 0), _scale(both(step, entering), 0.55))
        face = paint(face, white, _scale(both(step, leaving), 0.3))
        face = paint(face, (0, 0, 0), _scale(_outline(size, radius_pct, size * 0.005, frame), 0.3))
        face = paint(face, white, _scale(within(both(_outline(size, radius_pct, size * 0.01, size * 0.012).filter(ImageFilter.GaussianBlur(size * 0.003)), corner)), 0.8))
        return paint(face, white, rim())

    if style == "dome":  # bulging outwards: brightest near the top-left, falling away to the edge
        fall = gray.point(lambda v: int(255 * _clamp((v - 70) / 185, 0, 1) ** 1.4))
        face = paint(face, c3, _scale(within(fall), 0.7))
        hot = _radial(size, 0.38, 0.3, 0.6).point(lambda v: 255 - v)
        face = paint(face, white, _scale(within(hot), 0.42))
        face = paint(face, white, _scale(within(_ellipse(size, (0.24, 0.15, 0.48, 0.3), 0.03)), 0.5))
        return paint(face, white, rim(0.8))

    if style == "jelly":  # soft and wobbly: light glows through the whole edge, a fat highlight sits low
        edge = _bevel(size, radius_pct, mask, size * 0.16)
        face = paint(face, _lighten(c1, 0.75), _scale(edge, 0.55))
        face = paint(face, c3, _scale(both(_bevel(size, radius_pct, mask, size * 0.05), leaving), 0.35))
        face = paint(face, white, _scale(within(_ellipse(size, (0.14, 0.62, 0.86, 0.98), 0.06)), 0.3))
        face = paint(face, white, _scale(within(_ellipse(size, (0.16, 0.07, 0.62, 0.2), 0.02)), 0.6))
        return paint(face, white, rim(0.7))

    if style == "metal":  # brushed metal: bands of light running across, a machined edge
        bands = _vertical(size, 0, 1).point(lambda v: int(255 * (0.5 + 0.5 * math.sin(v / 255 * math.pi * 3.2 + 0.6)) ** 1.5))
        face = paint(face, white, _scale(within(bands), 0.36))
        dark_bands = _vertical(size, 0, 1).point(lambda v: int(255 * (0.5 - 0.5 * math.sin(v / 255 * math.pi * 3.2 + 0.6)) ** 2))
        face = paint(face, (0, 0, 0), _scale(within(dark_bands), 0.3))
        edge = ImageChops.subtract(mask, _shape(size, radius_pct, size * 0.035))
        face = paint(face, white, _scale(both(edge, entering), 0.6))
        face = paint(face, (0, 0, 0), _scale(both(edge, leaving), 0.5))
        face = paint(face, (0, 0, 0), _scale(_outline(size, radius_pct, size * 0.004, size * 0.035), 0.35))
        return paint(face, white, rim())

    if style == "chisel":  # hard cut edges: flat facets, no softness
        edge = ImageChops.subtract(mask, _shape(size, radius_pct, size * 0.07))
        lit = diagonal.point(lambda v: 255 if v < 128 else 0)
        unlit = diagonal.point(lambda v: 255 if v >= 128 else 0)
        face = paint(face, white, _scale(both(edge, lit), 0.5))
        face = paint(face, (0, 0, 0), _scale(both(edge, unlit), 0.42))
        face = paint(face, white, _scale(_outline(size, radius_pct, size * 0.004, size * 0.07), 0.35))
        return paint(face, white, rim(0.9))

    if style == "ridge":  # two raised ridges running round the edge
        for inset in (size * 0.03, size * 0.085):
            groove = _outline(size, radius_pct, size * 0.03, inset).filter(ImageFilter.GaussianBlur(size * 0.006))
            face = paint(face, white, _scale(within(both(groove, entering)), 0.6))
            face = paint(face, c3, _scale(within(both(groove, leaving)), 0.7))
            face = paint(face, (0, 0, 0), _scale(within(_outline(size, radius_pct, size * 0.004, inset + size * 0.03)), 0.28))
        face = paint(face, white, _scale(within(_ellipse(size, (0.2, 0.18, 0.8, 0.8), 0.12)), 0.08))
        return paint(face, white, rim())

    if style == "lens":  # a thick magnifying lens set into the tile
        ring_outer = _ellipse(size, (0.1, 0.1, 0.9, 0.9), 0.004)
        ring_inner = _ellipse(size, (0.14, 0.14, 0.86, 0.86), 0.004)
        collar = ImageChops.subtract(ring_outer, ring_inner)
        face = paint(face, c3, _scale(within(ImageChops.subtract(mask, ring_outer)), 0.35))  # the tile around the lens sits lower
        face = paint(face, white, _scale(both(collar, entering), 0.7))
        face = paint(face, (0, 0, 0), _scale(both(collar, leaving), 0.5))
        inside = ring_inner
        face = paint(face, white, _scale(both(inside, _radial(size, 0.38, 0.32, 0.5).point(lambda v: 255 - v)), 0.34))
        face = paint(face, c3, _scale(both(inside, gray.point(lambda v: int(255 * _clamp((v - 110) / 100, 0, 1)))), 0.5))
        crescent = ImageChops.subtract(_ellipse(size, (0.16, 0.16, 0.84, 0.84), 0.004), _ellipse(size, (0.16, 0.1, 0.84, 0.8), 0.02))
        face = paint(face, _lighten(c1, 0.7), _scale(within(crescent), 0.6))
        return paint(face, white, rim(0.7))

    if style == "neon":  # the middle sinks into the dark, the edge glows in the logo's colour
        face = paint(face, (0, 0, 0), _scale(within(_ellipse(size, (0.02, 0.02, 0.98, 0.98), 0.1)), 0.72))
        vivid = _lighten(c1, 0.15)
        face = paint(face, vivid, _scale(_bevel(size, radius_pct, mask, size * 0.11), 0.85))
        face = paint(face, _lighten(c1, 0.6), within(_outline(size, radius_pct, size * 0.012)))
        return paint(face, white, rim(0.5))

    if style == "gloss":  # lacquer: a hard-edged glare over the top half
        bevel = _bevel(size, radius_pct, mask, size * 0.05)
        face = paint(face, c3, _scale(both(bevel, leaving), 0.55))
        glare = both(_ellipse(size, (-0.3, -0.7, 1.3, 0.47), 0.006), _vertical(size, 0.58, 0.08))
        face = paint(face, white, within(glare))
        face = paint(face, _lighten(c1, 0.6), _scale(within(_ellipse(size, (0.15, 0.8, 0.85, 1.2), 0.06)), 0.5))
        return paint(face, white, rim())

    # glass (and its relatives bubble / crystal): thick liquid glass
    shine = 1.25 if style == "bubble" else 1.0
    bevel = _bevel(size, radius_pct, mask, size * 0.06)
    face = paint(face, c3, _scale(both(bevel, leaving), 0.6))
    face = paint(face, white, _scale(both(bevel, entering), 0.5 * shine))
    # the light that went through comes out again as a bright line of the logo's
    # own colour along the lower-right inside edge
    caustic = _outline(size, radius_pct, size * 0.02, size * 0.028).filter(ImageFilter.GaussianBlur(size * 0.009))
    face = paint(face, _lighten(c1, 0.7), _scale(within(both(caustic, leaving)), 0.75))
    # a wet glare over the top
    face = paint(face, white, within(both(_ellipse(size, (-0.3, -0.75, 1.3, 0.5), 0.045), _vertical(size, 0.4 * shine, 0.0))))
    if style != "bubble":
        face = paint(face, white, within(both(_ellipse(size, (-0.55, -1.25, 1.55, 0.36), 0.008), _vertical(size, 0.2, 0.02))))
    # edge: dark hairline, the inner surface catching light, a hard arc in the lit corner
    hairline = _outline(size, radius_pct, size * 0.005, size * 0.011).filter(ImageFilter.GaussianBlur(size * 0.002))
    face = paint(face, (0, 0, 0), _scale(within(hairline), 0.24))
    inner_line = _outline(size, radius_pct, size * 0.008, size * 0.03).filter(ImageFilter.GaussianBlur(size * 0.003))
    face = paint(face, white, _scale(both(inner_line, _vertical(size, 1.6, -0.9)), 0.4 * shine))
    arc = _outline(size, radius_pct, size * 0.016, size * 0.018).filter(ImageFilter.GaussianBlur(size * 0.004))
    face = paint(face, white, _scale(within(both(arc, corner)), 0.85))
    face = paint(face, white, rim())

    if style == "bubble":
        # a tight reflection of the light source, and light bouncing back off the far side
        face = paint(face, white, _scale(within(_ellipse(size, (0.2, 0.13, 0.4, 0.22), 0.012)), 0.9))
        face = paint(face, _lighten(c1, 0.6), _scale(both(_bevel(size, radius_pct, mask, size * 0.09), leaving), 0.5))
    elif style == "crystal":
        # the upper-left plane catches the light; a fine bright line where the planes meet
        plane = Image.new("L", (size * _SS, size * _SS), 0)
        ImageDraw.Draw(plane).polygon([(0, 0), (size * _SS, 0), (0, size * _SS)], fill=255)
        face = paint(face, white, _scale(within(plane.resize((size, size), Image.LANCZOS)), 0.14))
        seam = Image.new("L", (size * _SS, size * _SS), 0)
        ImageDraw.Draw(seam).line([(size * _SS, 0), (0, size * _SS)], fill=255, width=round(size * 0.006 * _SS))
        face = paint(face, white, _scale(within(seam.resize((size, size), Image.LANCZOS)), 0.4))
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


def get_or_render(cache_dir, key, icon_path, kind, tint, stroke_width, stroke_color, mode, accent, radius_pct=0, style="glass", colour_style="diagonal"):
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
            data = _encode(render_face(icon, radius_pct, style, colour_style), "face")
        else:
            data = _encode(render_logo(icon, tint, stroke_width, stroke_color, mode, accent), "logo")
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
        _trim_cache(cache_dir)
        return data
