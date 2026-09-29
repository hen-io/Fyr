import os

from flask import Flask, jsonify
from flask_session import Session

from . import connections
from .config import Config
from .datasources.registry import DataSourceRegistry
from .routes.auth import auth_bp
from .routes.calendar import calendar_bp
from .routes.config import config_bp
from .routes.connections import connections_bp
from .routes.defaults import defaults_bp
from .routes.legacy import legacy_bp
from .routes.status import status_bp
from .routes.system import system_bp
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

    os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
    Session(app)

    # Attached directly to the app object (not app.config, which Flask
    # expects to hold only plain config values) so every route can reach it
    # via current_app.datasources.
    app.datasources = DataSourceRegistry(connections.effective(Config, Config.DATA_DIR))

    app.register_blueprint(legacy_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(status_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(defaults_bp)
    app.register_blueprint(connections_bp)
    app.register_blueprint(widgets_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(users_bp)

    # Every route here is a JSON API - Flask's default HTML error pages
    # would be a surprise to any caller, so every error response is JSON too.
    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(413)
    def too_large(_e):
        return jsonify({"error": "request_too_large"}), 413

    # Applies to every response, including the two file-serving routes
    # (icons, avatars) - stops a browser from ever executing an upload as
    # something other than the content-type it was actually served as,
    # regardless of what bytes it contains. Cheap, no downside for a JSON
    # API + static files, worth having even though today's upload
    # validation (mimetype allowlist) already covers the realistic risk.
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return app
