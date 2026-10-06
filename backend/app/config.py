import os


class Config:
    """All settings come from environment variables (.env), same as the
    original weather_proxy.py - no behavior change, just centralized so
    every module reads config the same way instead of each grabbing
    os.environ directly."""

    HA_URL = os.environ.get("HA_URL", "").rstrip("/")
    HA_TOKEN = os.environ.get("HA_TOKEN", "")
    HA_WEATHER_ENTITY = os.environ.get("HA_WEATHER_ENTITY", "weather.home")
    HA_HOME_MODE_ENTITY = os.environ.get("HA_HOME_MODE_ENTITY", "")
    HA_INDOOR_TEMP_ENTITY = os.environ.get("HA_INDOOR_TEMP_ENTITY", "")
    # Empty by default (calendar feature is a no-op until set) - same
    # pattern as HA_HOME_MODE_ENTITY. Set to whichever calendar.* entity
    # Home Assistant exposes (check Settings -> Devices & services ->
    # Entities, or your calendar integration's own entity id).
    HA_CALENDAR_ENTITY = os.environ.get("HA_CALENDAR_ENTITY", "")
    WEATHER_CACHE_TTL = int(os.environ.get("WEATHER_CACHE_TTL", "300"))
    PORT = int(os.environ.get("PORT", "8584"))

    MQTT_ENABLED = os.environ.get("MQTT_ENABLED", "false").lower() == "true"
    MQTT_HOST = os.environ.get("MQTT_HOST", "")
    MQTT_PORT = int(os.environ.get("MQTT_PORT") or 1883)
    MQTT_USER = os.environ.get("MQTT_USER") or None
    MQTT_PASS = os.environ.get("MQTT_PASS") or None

    # Two separate volumes, both mounted from outside the app's own source
    # tree so a redeploy of the app itself never touches either of them:
    #   CONFIG_DIR - apps.config, ui.conf, icons/. Files an admin actually
    #                edits by hand, meant to be easy to find on the host.
    #   DATA_DIR   - users.json, prefs.json, the session store. Internal
    #                runtime state that's never meant to be hand-edited -
    #                kept separate so "things you edit" and "things the app
    #                manages itself" never get confused for one another.
    CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")
    DATA_DIR = os.environ.get("DATA_DIR", "/data")

    # Signs the session cookie. Required - the app refuses to start without
    # it (see app/__init__.py) rather than silently falling back to an
    # insecure default, since that default would let anyone forge a login.
    SECRET_KEY = os.environ.get("SESSION_SECRET", "")

    # Sessions are stored server-side (one file per session, under
    # DATA_DIR/sessions) specifically so a session can be revoked - Flask's
    # default signed-cookie sessions can't be, which matters for an admin
    # login. The cookie itself only ever holds an opaque session id.
    SESSION_TYPE = "filesystem"
    SESSION_FILE_DIR = os.path.join(DATA_DIR, "sessions")
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = int(os.environ.get("SESSION_LIFETIME_DAYS", "30")) * 86400
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Default on (cookie only sent over HTTPS) - set SESSION_COOKIE_SECURE=
    # false in .env if this backend is ever served over plain HTTP only.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"

    # How many reverse proxies sit in front of the backend (see
    # reqtools.client_address). 1 = only the container's own nginx; 2 = one
    # more proxy (Nginx Proxy Manager, Traefik, Caddy ...) in front of that.
    TRUSTED_PROXIES = int(os.environ.get("TRUSTED_PROXIES") or 1)

    # Hostname glob patterns /api/status is allowed to fetch. Without this,
    # that endpoint would be an open proxy: on a host-networked container,
    # anyone could make the backend fetch any URL on the LAN or internet.
    # It only ever checks the HOSTNAME of the requested URL against this
    # list - it doesn't need to know about apps.js/apps.config at all.
    # Empty by default (nothing allowed) - fail closed until .env sets it,
    # rather than defaulting to any particular deployment's own domains.
    STATUS_ALLOWED_HOSTS = [
        h.strip() for h in os.environ.get("STATUS_ALLOWED_HOSTS", "").split(",") if h.strip()
    ]
