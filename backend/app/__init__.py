import os

from urllib.parse import urlparse

from flask import Flask, jsonify, request
from flask_session import Session
from werkzeug.exceptions import HTTPException

from . import passwords
from .config import Config
from .datasources.registry import DataSourceRegistry
from .routes.auth import auth_bp
from .routes.calendar import calendar_bp
from .routes.config import config_bp
from .routes.integrations import integrations_bp
from .routes.defaults import defaults_bp
from .routes.feeds import feeds_bp
from .routes.legacy import legacy_bp
from .routes.status import status_bp
from .routes.system import system_bp
from .routes.tilefx import tilefx_bp
from .routes.users import users_bp
from .routes.widgets import widgets_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Without this, Werkzeug buffers an incoming request body fully before
    # any route-level size check (e.g. PUT /api/me/avatar's own 2MB cap)
    # ever runs - a client sending an arbitrarily large body would be
    # accepted and held in memory regardless of what a route later
    # decides to do with it. Comfortably above the avatar upload's own
    # limit (multipart framing adds a little overhead), small enough that
    # nothing legitimate on this API needs more.
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

    if not app.config["SECRET_KEY"]:
        raise RuntimeError(
            "SESSION_SECRET is not set. Refusing to start: without it, session "
            "cookies can't be signed securely. Set SESSION_SECRET in .env to a "
            "long random value (e.g. `python3 -c \"import secrets; print(secrets.token_hex(32))\"`)."
        )

    # Responses keep the order things were put in (categories, settings ...)
    # instead of Flask's default of sorting every object's keys.
    app.json.sort_keys = False

    os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
    try:
        # Flask-Session's current API: hand it the file cache directly (the
        # older SESSION_TYPE="filesystem" still works but is deprecated). The
        # threshold is how many session files may exist before old ones are
        # pruned - one per logged-in browser, so this is generous.
        from cachelib.file import FileSystemCache

        app.config["SESSION_TYPE"] = "cachelib"
        app.config["SESSION_CACHELIB"] = FileSystemCache(app.config["SESSION_FILE_DIR"], threshold=5000)
    except ImportError:  # an older Flask-Session without cachelib
        pass
    Session(app)

    # Attached directly to the app object (not app.config, which Flask
    # expects to hold only plain config values) so every route can reach it
    # via current_app.datasources.
    app.datasources = DataSourceRegistry(app.config, app.config["DATA_DIR"])

    # Made now rather than during the first login for an unknown username,
    # which would otherwise take visibly longer than every later one.
    passwords.dummy_hash()

    app.register_blueprint(legacy_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(status_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(defaults_bp)
    app.register_blueprint(integrations_bp)
    app.register_blueprint(widgets_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(tilefx_bp)
    app.register_blueprint(feeds_bp)

    # Cookie-authenticated state changes must come from this site. SameSite=Lax
    # already blocks cross-site POST/PUT/DELETE cookies in current browsers;
    # this is the second layer: a write that did not start on this very origin
    # is refused.
    @app.before_request
    def reject_cross_origin_writes():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        # Browsers state the request's provenance themselves and it is not
        # affected by whatever Host header a reverse proxy passes on, so it
        # is the primary signal.
        site = request.headers.get("Sec-Fetch-Site")
        if site == "cross-site":
            return jsonify({"error": "cross_origin_blocked"}), 403
        if site in ("same-origin", "none"):
            return None
        # "same-site" is another host under the same registrable domain - a
        # different app on a sibling subdomain. That is not us: fall through
        # to the Origin comparison, which it fails. Older browsers and
        # non-browser clients (no Sec-Fetch-Site at all) are judged the same
        # way: an Origin, if sent, must be one of the names this request was
        # addressed to.
        origin = request.headers.get("Origin")
        if not origin:
            if site == "same-site":
                return jsonify({"error": "cross_origin_blocked"}), 403
            return None
        origin_host = (urlparse(origin).hostname or "").lower()
        own = {request.host.split(":")[0].lower()}
        for header in ("X-Forwarded-Host", "X-Original-Host"):
            for value in (request.headers.get(header) or "").split(","):
                if value.strip():
                    own.add(value.strip().split(":")[0].lower())
        if origin_host not in own:
            return jsonify({"error": "cross_origin_blocked"}), 403
        return None

    # Every route here is a JSON API - Flask's default HTML error pages would
    # be a surprise to any caller (and say more about the stack than they
    # should), so every error response is JSON too.
    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(413)
    def too_large(_e):
        return jsonify({"error": "request_too_large"}), 413

    @app.errorhandler(405)
    def method_not_allowed(_e):
        return jsonify({"error": "method_not_allowed"}), 405

    @app.errorhandler(passwords.Busy)
    def busy(_e):
        # too many password checks at once (see passwords.py): come back shortly
        response = jsonify({"error": "busy"})
        response.headers["Retry-After"] = "5"
        return response, 503

    @app.errorhandler(HTTPException)
    def http_error(err):
        return jsonify({"error": (err.name or "error").lower().replace(" ", "_")}), err.code or 500

    @app.errorhandler(Exception)
    def unexpected(err):
        # Logged with its traceback (visible in the admin panel's Logs tab);
        # the caller only learns that something went wrong.
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        return jsonify({"error": "internal_error"}), 500

    # Applies to every response, including the two file-serving routes
    # (icons, avatars) - stops a browser from ever executing an upload as
    # something other than the content-type it was actually served as,
    # regardless of what bytes it contains. Cheap, no downside for a JSON
    # API + static files, worth having even though today's upload
    # validation (mimetype allowlist) already covers the realistic risk.
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Account, settings and widget data must never be served from a
        # shared/proxy cache or replayed after logout by the back button.
        if response.mimetype == "application/json":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    return app
