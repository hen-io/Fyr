import os
import platform
import signal
import sys
import threading
import time

from flask import Blueprint, current_app, jsonify, request

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


def _supervised_by_supervisord():
    """Only signal PID 1 when it really is the container's supervisord - on a
    developer machine PID 1 is init/systemd and must never be terminated."""
    try:
        with open("/proc/1/comm", encoding="utf-8") as f:
            return "supervisord" in f.read()
    except OSError:
        return False


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
    if not _supervised_by_supervisord():
        return jsonify({"error": "not_in_container"}), 501
    # Delayed on a background thread so this response actually reaches the
    # browser before the container starts going down.
    threading.Thread(target=_restart_after, args=(1,), daemon=True).start()
    return jsonify({"ok": True})


# --- container logs ---------------------------------------------------------
# supervisord writes each service's output to a size-rotated file here (and a
# tail process copies it to the container's stdout, so `docker logs` still works).
LOG_DIR = os.environ.get("FYR_LOG_DIR", "/var/log/fyr")
LOG_SOURCES = {"backend": "backend.log", "nginx": "nginx.log"}
_TAIL_BYTES = 1024 * 1024


def _tail_lines(path, count):
    """The last `count` lines of a text file, read from its end."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _TAIL_BYTES))
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-count:]


def _source_lines(name, count):
    path = os.path.join(LOG_DIR, LOG_SOURCES[name])
    lines = _tail_lines(path, count)
    if len(lines) < count:  # a fresh rotation: continue from the previous file
        lines = _tail_lines(path + ".1", count - len(lines)) + lines
    return lines


@system_bp.route("/api/system/logs")
@require_role("admin")
def container_logs():
    try:
        count = max(10, min(2000, int(request.args.get("lines", 200))))
    except ValueError:
        count = 200
    source = request.args.get("source", "backend")
    if source not in LOG_SOURCES:
        return jsonify({"error": "invalid_source"}), 400
    available = any(os.path.isfile(os.path.join(LOG_DIR, name)) for name in LOG_SOURCES.values())
    lines = _source_lines(source, count) if available else []
    return jsonify({"available": available, "source": source, "lines": lines})
