"""Shared setup for the backend tests.

Run from Source/backend:   python -m pytest
(needs requirements.txt + requirements-dev.txt)

The app reads its settings from the environment when it is imported, so the
environment is prepared here, before anything imports `app`."""

import io
import os
import struct
import sys
import tempfile
import zlib

import pytest

_TMP = tempfile.mkdtemp(prefix="fyr-test-")
os.environ.update(
    CONFIG_DIR=os.path.join(_TMP, "config"),
    DATA_DIR=os.path.join(_TMP, "data"),
    SESSION_SECRET="test-secret-not-real",
    SESSION_COOKIE_SECURE="false",
    STATUS_ALLOWED_HOSTS="",
    MQTT_ENABLED="false",
    HA_URL="",
    HA_TOKEN="",
    FYR_LOG_DIR=os.path.join(_TMP, "logs"),
)
os.makedirs(os.environ["CONFIG_DIR"], exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, ratelimit  # noqa: E402
from app.auth import create_user  # noqa: E402

ADMIN = ("admin1", "adminpass123")
VISITOR = ("vis1", "visitorpass1")
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}


def make_png(size=24, rgb=(40, 120, 220)):
    """A small but genuine PNG (uploads are decoded, so a fake will not do)."""

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * size
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b"")


def upload(client, url, name, content, mimetype="image/png", method="post"):
    return getattr(client, method)(url, data={"file": (io.BytesIO(content), name, mimetype)}, content_type="multipart/form-data")


@pytest.fixture(scope="session")
def app():
    application = create_app()
    create_user(*ADMIN, "admin", application.config)
    create_user(*VISITOR, "visitor", application.config)
    return application


@pytest.fixture(autouse=True)
def _fresh_limits():
    ratelimit.reset()
    yield
    ratelimit.reset()


def _client(app, credentials=None):
    client = app.test_client()
    if credentials:
        response = client.post("/api/login", json={"username": credentials[0], "password": credentials[1]})
        assert response.status_code == 200, response.data
    return client


@pytest.fixture
def anon(app):
    return _client(app)


@pytest.fixture
def admin(app):
    return _client(app, ADMIN)


@pytest.fixture
def visitor(app):
    return _client(app, VISITOR)


@pytest.fixture
def login(app):
    """login(("user", "password")) -> a new logged-in client."""
    return lambda credentials: _client(app, credentials)
