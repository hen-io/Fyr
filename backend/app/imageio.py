"""Checks and clean-up for uploaded pictures (Pillow).

An upload's file name and declared type are only claims. Decoding it is the
proof that it is a picture - and re-encoding means what is stored is always a
real, bounded image, never HTML carrying an image's name."""

import io

from PIL import Image, ImageOps

# Refuse anything that would decode to an absurd canvas (a "decompression bomb").
MAX_PIXELS = 40_000_000
AVATAR_SIZE = 256

_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "gif": "GIF", "webp": "WEBP", "ico": "ICO"}


class ImageRejected(ValueError):
    pass


def _open(data):
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > MAX_PIXELS:
            raise ImageRejected("image too large")
        image.load()
        return image
    except ImageRejected:
        raise
    except Exception as err:  # Pillow raises many different things for bad input
        raise ImageRejected("not an image") from err


def verify_icon(data, extension):
    """Raises ImageRejected unless `data` really is an image of the type its
    file extension says."""
    image = _open(data)
    if image.format != _FORMATS.get(extension.lower()):
        raise ImageRejected("content does not match the file type")


def normalize_avatar(data):
    """A square-ish profile picture as WebP: orientation applied, metadata
    dropped, scaled down to AVATAR_SIZE."""
    image = ImageOps.exif_transpose(_open(data))
    image = image.convert("RGBA" if "A" in image.getbands() or image.mode == "P" else "RGB")
    image.thumbnail((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "WEBP", quality=88, method=4)
    return out.getvalue()
