import json
import os
import platform
import signal
import sys
import threading
import time

from flask import Blueprint, current_app, jsonify

from ..auth import require_role
from ..meta import load_meta

system_bp = Blueprint("system", __name__)

# Captured at import time (app startup) - the module loads once when
# create_app() registers this blueprint, close enough to "process start"
# for a meaningful uptime figure.
_START_TIME = time.time()


def _public_meta():
    meta = load_meta()
    return {
        "name": meta.get("name"),
        "author": meta.get("author"),
        "homepage": meta.get("homepage"),
        "version": meta.get("version"),
        "frontend_version": meta.get("frontend_version"),
        "backend_version": meta.get("backend_version"),
    }


@system_bp.route("/api/about")
def about():
    return jsonify(_public_meta())


@system_bp.route("/api/system/info")
@require_role("admin")
def system_info():
    return jsonify(
        {
            **_public_meta(),
            "uptime_seconds": int(time.time() - _START_TIME),
            "python_version": platform.python_version(),
            "platform": sys.platform,
            "connections": current_app.datasources.check_all(),
        }
    )


def _restart_after(delay_seconds):
    time.sleep(delay_seconds)
    # Signals PID 1 (supervisord) rather than anything Docker-API-based -
    # no socket mount or extra privileges needed. supervisord exits on
    # SIGTERM, which ends the container; "restart: unless-stopped" in
    # docker-compose.yml is what actually brings it back up.
    os.kill(1, signal.SIGTERM)


@system_bp.route("/api/system/restart", methods=["POST"])
@require_role("admin")
def restart_container():
    # Delayed on a background thread so this response actually reaches the
    # browser before the container starts going down.
    threading.Thread(target=_restart_after, args=(1,), daemon=True).start()
    return jsonify({"ok": True})
