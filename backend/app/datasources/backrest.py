import base64
import time

from . import http
from .base import MetricSource

_SERVICE = "/v1.Backrest/"
_RUNNING = ("INPROGRESS", "PENDING", "SYSTEM_CANCELLED_PENDING")


def _int(value):
    """protobuf JSON sends int64 as strings."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _pick(data, *names):
    """A field by its JSON (camelCase) name or its proto (snake_case) name."""
    for name in names:
        if isinstance(data, dict) and name in data:
            return data[name]
    return None


def _clamp(value, default, lo, hi):
    try:
        return min(hi, max(lo, int(value if value not in (None, "") else default)))
    except (TypeError, ValueError):
        return default


class BackrestSource(MetricSource):
    """Backrest (the restic web UI) through its Connect/gRPC-JSON API - plain
    JSON POSTs to /v1.Backrest/<Method>. HTTP basic auth when Backrest has a
    user configured, none otherwise. Read-only: backup health as metrics for
    the ordinary widgets, plus a per-plan overview and a recent-operations
    list."""

    id = "backrest"
    category = "system"
    label = "Backrest"
    icon = "backup-restore"
    description = "Sikkerhetskopier (restic): status, feil siste 30 dager, størrelse og siste operasjoner."
    METRICS_TTL = 30
    FIELDS = [
        {"name": "url", "label": "Adresse", "kind": "url", "required": True, "placeholder": "http://backrest:9898"},
        {"name": "username", "label": "Brukernavn (valgfritt)", "kind": "text"},
        {"name": "password", "label": "Passord (valgfritt)", "kind": "password"},
    ]
    WIDGETS = ("backrest_plans", "backrest_operations")

    def __init__(self, url, username, password):
        super().__init__()
        self.url = (url or "").rstrip("/")
        self.username = username or ""
        self.password = password or ""

    @classmethod
    def from_values(cls, values, config):
        return cls(values.get("url"), values.get("username"), values.get("password"))

    def is_configured(self):
        return bool(self.url)

    def _rpc(self, method, body=None):
        if not self.is_configured():
            raise RuntimeError("Backrest is not configured")
        headers = {"Connect-Protocol-Version": "1"}
        if self.username:
            token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return http.get_json(http.join(self.url, _SERVICE + method), headers=headers, data=body if body is not None else {}, method="POST", timeout=10)

    def check(self):
        if not self.is_configured():
            return {"connected": False, "detail": "URL mangler", "latency_ms": None}
        started = time.time()
        try:
            dashboard = self._rpc("GetSummaryDashboard") or {}
        except http.HttpError as err:
            detail = "Feil brukernavn/passord" if err.status in (401, 403) else str(err)
            return {"connected": False, "detail": detail, "latency_ms": None}
        except Exception as err:
            return {"connected": False, "detail": str(getattr(err, "reason", err))[:120], "latency_ms": None}
        plans = len(_pick(dashboard, "planSummaries", "plan_summaries") or [])
        return {"connected": True, "detail": f"Backrest ({plans} planer)", "latency_ms": int((time.time() - started) * 1000)}

    # --- data -----------------------------------------------------------------

    def _summaries(self):
        dashboard = self._rpc("GetSummaryDashboard") or {}
        return (
            _pick(dashboard, "repoSummaries", "repo_summaries") or [],
            _pick(dashboard, "planSummaries", "plan_summaries") or [],
        )

    @staticmethod
    def _plan(summary):
        return {
            "id": summary.get("id") or "?",
            "ok": _int(_pick(summary, "backupsSuccessLast30days", "backups_success_last_30days")),
            "warning": _int(_pick(summary, "backupsWarningLast30days", "backups_warning_last_30days")),
            "failed": _int(_pick(summary, "backupsFailed30days", "backups_failed_30days")),
            "snapshots": _int(_pick(summary, "totalSnapshots", "total_snapshots")),
            "next_ms": _int(_pick(summary, "nextBackupTimeMs", "next_backup_time_ms")),
            "added_bytes": _int(_pick(summary, "bytesAddedLast30days", "bytes_added_last_30days")),
        }

    def fetch_metrics(self):
        repos, plans = self._summaries()
        plan_rows = [self._plan(p) for p in plans]
        now_ms = int(time.time() * 1000)
        upcoming = [p["next_ms"] for p in plan_rows if p["next_ms"] > now_ms]
        protected = sum(_int(_pick(r, "protectedBytes", "protected_bytes")) for r in repos)
        snapshots = sum(_int(_pick(r, "totalSnapshots", "total_snapshots")) for r in repos)
        metrics = {
            "backups_ok": (sum(p["ok"] for p in plan_rows), None, "Vellykkede sikkerhetskopier (30 dager)"),
            "backups_warning": (sum(p["warning"] for p in plan_rows), None, "Sikkerhetskopier med advarsel (30 dager)"),
            "backups_failed": (sum(p["failed"] for p in plan_rows), None, "Mislykkede sikkerhetskopier (30 dager)"),
            "plans": (len(plan_rows), None, "Planer"),
            "repos": (len(repos), None, "Repoer"),
            "snapshots": (snapshots, None, "Snapshots"),
            "protected_gb": (round(protected / 1e9, 1), "GB", "Beskyttet data"),
            "added_gb": (round(sum(p["added_bytes"] for p in plan_rows) / 1e9, 2), "GB", "Lagt til (30 dager)"),
        }
        if upcoming:
            metrics["next_backup_minutes"] = (max(0, round((min(upcoming) - now_ms) / 60000)), "min", "Til neste sikkerhetskopi")
        return metrics

    def widget_data(self, widget_type, widget):
        count = _clamp(widget.get("count"), 8, 1, 40)
        if widget_type == "backrest_plans":
            _repos, plans = self._summaries()
            rows = sorted((self._plan(p) for p in plans), key=lambda p: (-p["failed"], p["id"]))
            return {"items": rows[:count]}
        if widget_type == "backrest_operations":
            data = self._rpc("GetOperations", {"selector": {}, "lastN": count * 2}) or {}
            items = []
            for op in reversed(_pick(data, "operations") or []):
                kind = next((k[len("operation"):] for k in op if k.startswith("operation") and k != "operation"), "")
                status = str(op.get("status") or "").replace("STATUS_", "")
                items.append(
                    {
                        "plan": _pick(op, "planId", "plan_id") or _pick(op, "repoId", "repo_id") or "",
                        "kind": kind.lower(),
                        "status": status.lower(),
                        "running": status in _RUNNING,
                        "start_ms": _int(_pick(op, "unixTimeStartMs", "unix_time_start_ms")),
                        "message": str(_pick(op, "displayMessage", "display_message") or "")[:200],
                    }
                )
            items.sort(key=lambda i: -i["start_ms"])
            return {"items": items[:count]}
        raise NotImplementedError(widget_type)
