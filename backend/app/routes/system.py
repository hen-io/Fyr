import os
import signal
import threading
import time

from flask import Blueprint, jsonify

from ..auth import require_role

system_bp = Blueprint("system", __name__)


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
