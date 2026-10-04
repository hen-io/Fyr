"""Renders the per-app tile effects (logo outline, icon-coloured "liquid glass"
face, glow and sheen) once on the server, so browsers only show two cached
images per app instead of computing gradients and filters for every tile.

  face  - the tile background: a vibrant gradient taken from the logo's own
          colours with a glossy highlight and a soft bounce light
  logo  - the logo itself on a transparent square (same size as the tile face):
          outline, coloured glow, drop shadow and a light sheen baked in
"""

import colorsys
import re
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

RENDER_VERSION = 17  # bump when the drawing changes: it is part of every cache key and image URL

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


def _pixels(image):
    """Every pixel of an image (Pillow renamed the call in 12; both spellings work)."""
    return getattr(image, "get_flattened_data", image.getdata)()


_SVG_COLOUR = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b|rgba?\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})")
_SVG_MAX_BYTES = 1024 * 1024


def svg_swatch(path):
    """An SVG cannot be decoded here, but the badge only needs the logo's
    colours - and an SVG names them in plain text (fill, stroke, gradient
    stops). They become a small picture with one stripe per colour, in the
    proportions they are mentioned, which the colour analysis below reads like
    any other icon. The file is only searched as text, never parsed as XML."""
    with open(path, "rb") as handle:
        source = handle.read(_SVG_MAX_BYTES).decode("utf-8", errors="replace")
    colours = []
    for match in _SVG_COLOUR.finditer(source):
        if match.group(1):
            digits = match.group(1)
            if len(digits) == 3:
                digits = "".join(c * 2 for c in digits)
            colours.append(tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4)))
        else:
            colours.append(tuple(min(255, int(match.group(i))) for i in (2, 3, 4)))
    colours = colours[:400] or [(128, 128, 128)]
    swatch = Image.new("RGBA", (len(colours), 8))
    swatch.putdata([c + (255,) for c in colours] * 8)
    return swatch


def load_icon(path):
    if path.lower().endswith(".svg"):
        return svg_swatch(path)
    image = Image.open(path)
    image.load()
    return image.convert("RGBA")


def _hue_bins(icon):
    """Saturated, opaque pixels vote for their hue (12 bins): [weight, hue*w, sat*w]."""
    small = icon.resize((48, 48), Image.LANCZOS)
    bins = [[0.0, 0.0, 0.0] for _ in range(12)]
    for r, g, b, a in _pixels(small):
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
    for r, g, b, a in _pixels(small):
        if a >= 128:
            total += (r + g + b) / 3
            count += 1
    return (total / count / 255) if count else 0.5


DEFAULT_VIBRANCY = 60


def _vivid(saturation, vibrancy):
    """(saturation, extra lightness) for a colour at `vibrancy` 0-100: 60 is the
    logo colour as it is, below that it fades towards grey, above it goes to
    full saturation and a little brighter."""
    level = _clamp(vibrancy, 0, 100) / 100
    if level <= 0.6:
        return saturation * (0.12 + 0.88 * level / 0.6), 0.0
    boost = (level - 0.6) / 0.4
    return saturation + (1 - saturation) * boost, 0.07 * boost


def _chosen(colour):
    """(rgb, (hue, saturation) or None for a grey) of a colour an admin picked."""
    rgb = _hex_rgb(colour, None)
    if rgb is None:
        return None
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return rgb, ((h, s) if s >= 0.08 and 0.04 < l < 0.96 else None)


def palette(icon, vibrancy=DEFAULT_VIBRANCY, colour=None):
    """Three colours from the logo's own hue: vivid centre, darker middle, deep edge.
    `colour` (hex) replaces the logo's colour with one the admin picked for the
    app - used exactly as picked, so the vibrancy setting does not touch it."""
    chosen = _chosen(colour)
    if chosen:
        rgb, hue = chosen
        h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
        return (rgb, _hls_rgb(h + 0.012, l * 0.77, s), _hls_rgb(h - 0.012, l * 0.48, s)), hue
    hue = dominant_hue(icon)
    if hue is None:
        grey = _clamp(average_grey(icon), 0.25, 0.75)
        return tuple(_hls_rgb(0, _clamp(grey * f, 0, 1), 0) for f in (1.1, 0.8, 0.5)), None
    h, s = hue
    s, lift = _vivid(_clamp(s * 1.3, 0.82, 1.0), vibrancy)
    return (_hls_rgb(h, 0.56 + lift, s), _hls_rgb(h + 0.012, 0.43 + lift, s), _hls_rgb(h - 0.012, 0.27 + lift, s)), hue


def _alpha_composite_solid(base, colour, mask):
    """Paint `colour` onto RGBA `base` through L `mask`."""
    # the colour everywhere, the mask as its alpha (pasting through a mask onto a
    # transparent layer would grey the soft edges)
    layer = Image.new("RGBA", base.size, colour + (0,))
    layer.putalpha(mask)
    return Image.alpha_composite(base, layer)


BADGE_STYLES = (
    "glass", "bubble", "jelly", "dome", "wave", "pillow", "ring", "ridge", "inset", "metal", "gloss", "neon",
    "aqua", "plastic", "bevel", "emboss", "crystal", "satin", "frosted", "backlit", "flat",
)  # the 3D shading
BADGE_COLOURS = ("diagonal", "radial", "vertical", "solid", "duo", "dark", "pale", "neutral")  # how the logo colour is laid out

_SS = 3  # supersampling for the rounded shapes


def _shape(size, radius_pct, inset=0.0):
    """The tile's rounded square, optionally shrunk by `inset` px on every side
    (with the corner radius reduced to match, so the two outlines stay parallel)."""
    big = size * _SS
    radius = max(0.0, big * max(radius_pct, 0) / 100 - inset * _SS)
    layer = Image.new("L", (big, big), 0)
    ImageDraw.Draw(layer).rounded_rectangle((inset * _SS, inset * _SS, big - 1 - inset * _SS, big - 1 - inset * _SS), radius=radius, fill=255)
    return layer.reduce(_SS)


def _outline(size, radius_pct, width, inset=0.0):
    """A line of even `width` px following the rounded square, `inset` px inside it."""
    big = size * _SS
    radius = max(0.0, big * max(radius_pct, 0) / 100 - inset * _SS)
    layer = Image.new("L", (big, big), 0)
    ImageDraw.Draw(layer).rounded_rectangle(
        (inset * _SS, inset * _SS, big - 1 - inset * _SS, big - 1 - inset * _SS), radius=radius, outline=255, width=max(1, round(width * _SS))
    )
    return layer.reduce(_SS)


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


def render_face(icon, radius_pct=0, style="glass", colour_style="diagonal", vibrancy=DEFAULT_VIBRANCY, colour=None, colour2=None):
    """The tile background: `colour_style` decides how the logo's own colours
    are laid out, `style` decides the 3D shading on top. The shape is the
    tile's rounded square."""
    (c1, c2, c3), hue = palette(icon, vibrancy, colour)
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
        picked = _hex_rgb(colour2, None)
        other = None if picked or colour else secondary_hue(icon)
        if picked:  # the admin's own second colour
            colour = ImageOps.colorize(diagonal, black=_lighten(c1, 0.12), mid=c1, white=picked, midpoint=110)
        elif hue is not None and other is not None:
            other_s, other_lift = _vivid(_clamp(other[1] * 1.3, 0.8, 1.0), vibrancy)
            last = _hls_rgb(other[0], 0.46 + other_lift, other_s)
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
    # Everything here is soft: depth comes from wide, blurred light and shade
    # that follow the rounded shape - no hairlines, no hard-edged highlights.
    paint = _alpha_composite_solid
    white = (255, 255, 255)
    leaving = diagonal.point(lambda v: int(255 * _clamp((v - 80) / 175, 0, 1)))  # bottom-right
    entering = diagonal.point(lambda v: int(255 * _clamp((175 - v) / 175, 0, 1)))  # top-left
    both = ImageChops.multiply
    within = lambda layer: both(layer, mask)  # noqa: E731
    blur = lambda layer, amount: layer.filter(ImageFilter.GaussianBlur(size * amount))  # noqa: E731

    def edge(depth, softness=0.6):
        """A rounded band inside the edge, `depth` (share of the tile) wide, fading inwards."""
        inner = _shape(size, radius_pct, size * depth).filter(ImageFilter.GaussianBlur(size * depth * softness))
        return ImageChops.subtract(mask, inner)

    def glow_rim(strength):
        """The rim as a soft line of light rather than a drawn stroke."""
        line = blur(_outline(size, radius_pct, size * 0.012, size * 0.004), 0.008)
        lit = diagonal.point(lambda v: int(255 * _clamp(strength * (0.25 + 0.75 * (1 - v / 255) ** 2 + 0.3 * (v / 255) ** 3), 0, 1)))
        return within(both(line, lit))

    def roundness(depth, shade, light):
        """The basic rounded-off look: light on the upper-left shoulder, shade on the lower-right."""
        band = edge(depth)
        out = paint(face, c3, _scale(both(band, leaving), shade))
        return paint(out, white, _scale(both(band, entering), light))

    def glare(strength, reach=0.5, softness=0.07):
        return within(both(_ellipse(size, (-0.3, -0.75, 1.3, reach), softness), _vertical(size, strength, 0.0)))

    if style == "pillow":  # soft and puffy: very wide shoulders, no glare
        face = roundness(0.2, 0.75, 0.6)
        face = paint(face, white, _scale(within(_ellipse(size, (0.2, 0.16, 0.8, 0.76), 0.14)), 0.1))
        return paint(face, white, glow_rim(0.45))

    if style == "dome":  # bulging outwards: brightest near the top-left, falling away all round
        fall = blur(gray.point(lambda v: int(255 * _clamp((v - 60) / 195, 0, 1) ** 1.5)), 0.02)
        face = paint(face, c3, _scale(within(fall), 0.72))
        hot = _radial(size, 0.38, 0.3, 0.62).point(lambda v: 255 - v)
        face = paint(face, white, _scale(within(hot), 0.42))
        face = paint(face, white, _scale(within(_ellipse(size, (0.22, 0.14, 0.5, 0.32), 0.05)), 0.42))
        return paint(face, white, glow_rim(0.4))

    if style == "jelly":  # light glows through the whole edge, a fat soft highlight sits low
        face = paint(face, _lighten(c1, 0.75), _scale(edge(0.18), 0.55))
        face = paint(face, c3, _scale(both(edge(0.07), leaving), 0.3))
        face = paint(face, white, _scale(within(_ellipse(size, (0.14, 0.62, 0.86, 0.98), 0.08)), 0.28))
        face = paint(face, white, _scale(within(_ellipse(size, (0.16, 0.06, 0.64, 0.22), 0.045)), 0.5))
        return paint(face, white, glow_rim(0.5))

    if style == "inset":  # pressed into the page: soft shadow under the upper-left lip, light on the far side
        band = edge(0.16, 0.8)
        face = paint(face, (0, 0, 0), _scale(both(band, entering), 0.55))
        face = paint(face, white, _scale(both(band, leaving), 0.4))
        face = paint(face, white, _scale(within(_ellipse(size, (0.2, 0.55, 0.8, 1.0), 0.1)), 0.14))  # light pooling in the hollow
        return paint(face, white, glow_rim(0.3))

    if style == "ring":  # a soft, thick rim of glass round a gently sunken middle
        rim = blur(ImageChops.subtract(mask, _shape(size, radius_pct, size * 0.12)), 0.04)
        face = paint(face, white, _scale(within(both(rim, entering)), 0.5))
        face = paint(face, c3, _scale(within(both(rim, leaving)), 0.5))
        hollow = blur(_outline(size, radius_pct, size * 0.07, size * 0.13), 0.045)
        face = paint(face, (0, 0, 0), _scale(within(both(hollow, entering)), 0.38))
        face = paint(face, _lighten(c1, 0.6), _scale(within(both(hollow, leaving)), 0.4))
        face = paint(face, white, glare(0.22, 0.42, 0.1))
        return paint(face, white, glow_rim(0.5))

    if style == "ridge":  # ripples: two soft swells of glass running round the edge
        for inset, strength in ((0.045, 1.0), (0.14, 0.7)):
            swell = blur(_outline(size, radius_pct, size * 0.05, size * inset), 0.035)
            face = paint(face, white, _scale(within(both(swell, entering)), 0.6 * strength))
            face = paint(face, c3, _scale(within(both(swell, leaving)), 0.6 * strength))
        face = paint(face, white, glare(0.2, 0.45, 0.1))
        return paint(face, white, glow_rim(0.45))

    if style == "wave":  # liquid in a glass: soft swells of deeper colour rolling across the lower half
        back = _ellipse(size, (0.25, 0.56, 1.55, 1.7), 0.06)
        face = paint(face, c2, _scale(within(back), 0.5))
        front = (-0.45, 0.5, 0.95, 1.6)
        face = paint(face, c3, _scale(within(_ellipse(size, front, 0.05)), 0.55))
        # light caught along the top of the front swell
        crest = ImageChops.subtract(_ellipse(size, front, 0.03), _ellipse(size, (front[0], front[1] + 0.045, front[2], front[3] + 0.045), 0.03))
        face = paint(face, _lighten(c1, 0.75), _scale(within(crest), 0.65))
        face = roundness(0.1, 0.55, 0.45)
        face = paint(face, white, glare(0.35, 0.45, 0.09))
        return paint(face, white, glow_rim(0.55))

    if style == "metal":  # liquid metal: slow, wide waves of light and shade under a glass skin
        wave = lambda sign, power: _vertical(size, 0, 1).point(lambda v: int(255 * (0.5 + sign * 0.5 * math.sin(v / 255 * math.pi * 2.0 + 0.9)) ** power))  # noqa: E731
        face = paint(face, white, _scale(within(blur(wave(1, 1.2), 0.06)), 0.34))
        face = paint(face, c3, _scale(within(blur(wave(-1, 1.6), 0.06)), 0.5))
        face = roundness(0.1, 0.55, 0.5)
        face = paint(face, white, glare(0.22, 0.4, 0.1))
        return paint(face, white, glow_rim(0.55))

    if style == "neon":  # the middle sinks into the dark, the edge glows in the logo's colour
        face = paint(face, (0, 0, 0), _scale(within(_ellipse(size, (0.02, 0.02, 0.98, 0.98), 0.12)), 0.72))
        face = paint(face, _lighten(c1, 0.15), _scale(edge(0.15), 0.9))
        face = paint(face, _lighten(c1, 0.6), within(blur(_outline(size, radius_pct, size * 0.02), 0.012)))
        return face

    if style == "gloss":  # lacquer: a broad glare over the top half that melts away downwards
        face = roundness(0.1, 0.55, 0.3)
        face = paint(face, white, glare(0.55, 0.5, 0.1))
        face = paint(face, _lighten(c1, 0.6), _scale(within(_ellipse(size, (0.15, 0.8, 0.85, 1.2), 0.1)), 0.45))
        return paint(face, white, glow_rim(0.5))

    if style == "aqua":  # a drop of water: a soft cap of light on top, the colour glowing at the bottom
        face = roundness(0.1, 0.5, 0.3)
        cap = within(both(_ellipse(size, (0.1, 0.02, 0.9, 0.46), 0.07), _vertical(size, 0.9, 0.0)))
        face = paint(face, white, _scale(cap, 0.7))
        face = paint(face, _lighten(c1, 0.75), _scale(within(_ellipse(size, (0.12, 0.62, 0.88, 1.1), 0.11)), 0.6))
        return paint(face, white, glow_rim(0.5))

    if style == "plastic":  # candy: fat rounded shoulders, a soft glint, a darker underside
        face = roundness(0.15, 0.7, 0.4)
        face = paint(face, (0, 0, 0), within(_vertical(size, 0.0, 0.28)))
        face = paint(face, white, _scale(within(_ellipse(size, (0.14, 0.08, 0.5, 0.24), 0.04)), 0.7))
        face = paint(face, _lighten(c1, 0.6), _scale(both(edge(0.12), leaving), 0.35))
        return paint(face, white, glow_rim(0.5))

    if style == "bevel":  # a thick slab of glass: a wide, soft edge that bends the light
        band = blur(ImageChops.subtract(mask, _shape(size, radius_pct, size * 0.1)), 0.035)
        face = paint(face, white, _scale(within(both(band, entering)), 0.62))
        face = paint(face, c3, _scale(within(both(band, leaving)), 0.6))
        inner = blur(_outline(size, radius_pct, size * 0.035, size * 0.12), 0.03)
        face = paint(face, _lighten(c1, 0.7), _scale(within(both(inner, leaving)), 0.55))  # light gathering inside the far edge
        face = paint(face, white, glare(0.25, 0.45, 0.1))
        return paint(face, white, glow_rim(0.55))

    if style == "emboss":  # a cushion of glass swelling up out of the middle
        swell = blur(_shape(size, radius_pct, size * 0.13), 0.05)
        ground = ImageChops.subtract(mask, swell)
        face = paint(face, c3, _scale(within(ground), 0.4))
        shade = ImageChops.subtract(ImageChops.offset(swell, round(size * 0.025), round(size * 0.03)), swell)
        face = paint(face, (0, 0, 0), _scale(within(blur(shade, 0.02)), 0.5))
        face = paint(face, white, _scale(both(swell, _radial(size, 0.36, 0.3, 0.6).point(lambda v: 255 - v)), 0.4))
        face = paint(face, white, _scale(within(_ellipse(size, (0.24, 0.17, 0.56, 0.33), 0.05)), 0.35))
        return paint(face, white, glow_rim(0.4))

    if style == "crystal":  # light breaking through cut glass: four soft planes of light and shade
        other = diagonal.transpose(Image.FLIP_LEFT_RIGHT)  # 0 in the top-right corner
        near, far = (lambda v: 255 if v < 128 else 0), (lambda v: 0 if v < 128 else 255)
        facets = (  # (which side, light or shade, how strong)
            (both(diagonal.point(near), other.point(near)), white, 0.4),  # top
            (both(diagonal.point(near), other.point(far)), white, 0.16),  # left
            (both(diagonal.point(far), other.point(near)), c3, 0.3),  # right
            (both(diagonal.point(far), other.point(far)), c3, 0.55),  # bottom
        )
        for facet, tone, strength in facets:
            face = paint(face, tone, _scale(within(blur(facet, 0.055)), strength))
        face = paint(face, _lighten(c1, 0.6), _scale(within(_ellipse(size, (0.22, 0.24, 0.78, 0.8), 0.1)), 0.3))
        face = roundness(0.07, 0.4, 0.35)
        return paint(face, white, glow_rim(0.6))

    if style == "satin":  # silk under glass: one broad, soft sweep of light from corner to corner
        sheen = diagonal.point(lambda v: int(255 * math.exp(-(((v / 255) - 0.36) / 0.26) ** 2)))
        face = paint(face, white, _scale(within(sheen), 0.36))
        face = paint(face, c3, _scale(within(diagonal.point(lambda v: int(255 * _clamp((v - 150) / 105, 0, 1) ** 1.5))), 0.45))
        face = roundness(0.1, 0.5, 0.4)
        caustic = blur(_outline(size, radius_pct, size * 0.03, size * 0.035), 0.022)
        face = paint(face, _lighten(c1, 0.7), _scale(within(both(caustic, leaving)), 0.6))
        return paint(face, white, glow_rim(0.5))

    if style == "frosted":  # matte, frosted glass: a milky veil and a soft light edge, no glare
        face = paint(face, white, _scale(mask, 0.16))
        face = paint(face, white, _scale(edge(0.2), 0.3))
        face = paint(face, c3, _scale(both(edge(0.06), leaving), 0.25))
        return paint(face, white, glow_rim(0.7))

    if style == "backlit":  # lit from behind: a bright heart, the edge falling into shadow
        heart = _radial(size, 0.5, 0.48, 0.5).point(lambda v: 255 - v)
        face = paint(face, _lighten(c1, 0.8), _scale(within(heart), 0.6))
        face = paint(face, (0, 0, 0), _scale(edge(0.22), 0.55))
        return paint(face, _lighten(c1, 0.5), glow_rim(0.35))

    # glass / bubble: thick, rounded liquid glass
    shine = 1.25 if style == "bubble" else 1.0
    face = roundness(0.11, 0.6, 0.5 * shine)
    # the light that went through gathers as a soft glow of the logo's own colour
    # along the lower-right inside edge
    caustic = blur(_outline(size, radius_pct, size * 0.03, size * 0.035), 0.022)
    face = paint(face, _lighten(c1, 0.7), _scale(within(both(caustic, leaving)), 0.7))
    face = paint(face, white, glare(0.4 * shine))
    # the upper-left shoulder catches the light: a soft bloom, not a line
    shoulder = blur(_outline(size, radius_pct, size * 0.03, size * 0.03), 0.02)
    corner = diagonal.point(lambda v: int(255 * _clamp((125 - v) / 125, 0, 1) ** 1.6))
    face = paint(face, white, _scale(within(both(shoulder, corner)), 0.75 * min(shine, 1.1)))
    face = paint(face, white, glow_rim(0.55))
    if style == "bubble":
        # a soft reflection of the light source, and light bouncing back off the far side
        face = paint(face, white, _scale(within(_ellipse(size, (0.17, 0.11, 0.45, 0.27), 0.03)), 0.7))
        face = paint(face, _lighten(c1, 0.6), _scale(both(edge(0.14), leaving), 0.45))
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


def render_logo(icon, tint, stroke_width, stroke_color, mode, accent, colour=None, radius_pct=0):
    size = SIZE
    box = round(size * LOGO_FRACTION)
    # (a small picture - a site's favicon - is enlarged to the same box as the others)
    logo = ImageOps.contain(icon, (box, box), Image.LANCZOS)
    if radius_pct > 0:
        # A logo that fills its square (a site's favicon, a photo) gets the same
        # rounding as everything else; one with clear corners is left as it is.
        big = (logo.width * _SS, logo.height * _SS)
        corners = Image.new("L", big, 0)
        ImageDraw.Draw(corners).rounded_rectangle((0, 0, big[0] - 1, big[1] - 1), radius=min(big) * radius_pct / 100, fill=255)
        logo.putalpha(ImageChops.multiply(logo.split()[3], corners.reduce(_SS)))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(logo, ((size - logo.width) // 2, round((size - logo.height) / 2 - size * LOGO_LIFT)), logo)
    alpha = canvas.split()[3]
    (c1, c2, c3), hue = palette(icon, colour=colour)

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


def get_or_render(cache_dir, key, icon_path, kind, tint, stroke_width, stroke_color, mode, accent, radius_pct=0, style="glass", colour_style="diagonal", vibrancy=DEFAULT_VIBRANCY, colour=None, colour2=None):
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
            data = _encode(render_face(icon, radius_pct, style, colour_style, vibrancy, colour, colour2), "face")
        else:
            data = _encode(render_logo(icon, tint, stroke_width, stroke_color, mode, accent, colour, radius_pct), "logo")
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
        _trim_cache(cache_dir)
        return data
