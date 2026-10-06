import json
import os

_LOCATIONS = (
    "/app/app.meta.json",  # inside the container (Dockerfile copies it here)
    os.path.join(os.path.dirname(__file__), "..", "..", "app.meta.json"),  # Source/ in a dev checkout
)
_cache = None


def load_meta():
    """Name, author, homepage and the three version numbers (container /
    frontend / backend) from Source/app.meta.json - the one file every part
    of the project reads them from."""
    global _cache
    if _cache is None:
        _cache = {}
        for path in _LOCATIONS:
            try:
                with open(path, encoding="utf-8") as f:
                    _cache = json.load(f)
                break
            except (OSError, ValueError):
                continue
    return _cache
