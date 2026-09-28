import os

from flask import Flask, jsonify
from flask_session import Session

from .config import Config
from .datasources.registry import DataSourceRegistry
from .routes.auth import auth_bp
from .routes.calendar import calendar_bp
from .routes.config import config_bp
from .routes.legacy import legacy_bp
from .routes.status import status_bp
from .routes.widgets import widgets_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

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
    app.datasources = DataSourceRegistry(Config)

    app.register_blueprint(legacy_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(status_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(widgets_bp)
    app.register_blueprint(calendar_bp)

    # Every route here is a JSON API - Flask's default HTML error pages
    # would be a surprise to any caller, so every error response is JSON too.
    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "not_found"}), 404

    return app
