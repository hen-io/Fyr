import json
import os
import platform
import signal
import sys
import threading
import time

from flask import Blueprint, jsonify

from ..auth import require_role

system_bp = Blueprint("system", __name__)

# Captured at import time (app startup) - the module loads once when
# create_app() registers this blueprint, close enough to "process start"
# for a meaningful uptime figure.
_START_TIME = time.time()


def _app_metadata():
    # /app/package.json is a copy kept specifically for this (see
    # Dockerfile/entrypoint.sh's startup banner) - not the one nginx
    # serves, which gets deleted at build time.
    try:
        with open("/app/package.json", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "name": data.get("name"),
            "version": data.get("version"),
            "author": data.get("author"),
            "homepage": data.get("homepage"),
        }
    except Exception:
        return {}


@system_bp.route("/api/system/info")
@require_role("admin")
def system_info():
    return jsonify(
        {
            **_app_metadata(),
            "uptime_seconds": int(time.time() - _START_TIME),
            "python_version": platform.python_version(),
            "platform": sys.platform,
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
