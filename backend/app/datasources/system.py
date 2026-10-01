import os
import shutil
import sys
import threading
import time

from .base import MetricSource

_START = time.time()


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class SystemSource(MetricSource):
    """The machine Fyr itself runs on: processor, memory, disk, uptime. No
    setup - it reads the operating system directly (/proc on Linux; inside a
    container that is the HOST's processor and memory, and the disk of
    whatever paths are mounted in). Shown by the "Systemressurser" widget, and
    every number is also available to the ordinary sensor / gauge / graph
    widgets."""

    id = "system"
    category = "system"
    label = "System (verten)"
    icon = "server"
    description = "Prosessor, minne, disk og oppetid for maskinen Fyr kjører på."
    default_enabled = True
    METRICS_TTL = 4
    FIELDS = [
        {"name": "paths", "label": "Disker (stier, kommaseparert)", "kind": "text", "placeholder": "/, /config", "default": "/"},
    ]
    WIDGETS = ("system_resources",)

    def __init__(self, paths):
        super().__init__()
        wanted = [p.strip() for p in str(paths or "/").split(",") if p.strip()]
        self.paths = wanted[:8] or ["/"]
        self._cpu_last = None
        self._cpu_at = 0.0
        self._cpu_percent = None
        self._cpu_lock = threading.Lock()
        self._cpu()  # a first sample now, so the first real reading has something to compare with

    @classmethod
    def from_values(cls, values, config):
        return cls(values.get("paths"))

    def check(self):
        return {"connected": True, "detail": sys.platform, "latency_ms": None}

    # --- readings -----------------------------------------------------------------

    def _cpu_times(self):
        """(busy, total) processor time since boot, in arbitrary ticks."""
        if sys.platform.startswith("linux"):
            parts = [float(x) for x in _read("/proc/stat").splitlines()[0].split()[1:]]
            idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
            return sum(parts) - idle, sum(parts)
        if sys.platform == "win32":
            import ctypes

            class FILETIME(ctypes.Structure):
                _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
            ticks = lambda ft: (ft.high << 32) | ft.low  # noqa: E731
            total = ticks(kernel) + ticks(user)  # kernel time includes idle
            return total - ticks(idle), total
        return None

    def _cpu(self):
        """Share of processor time used since the previous reading."""
        try:
            now = self._cpu_times()
        except Exception:
            return None
        if now is None:
            return None
        with self._cpu_lock:
            # Two readings a moment apart would compare almost nothing with
            # almost nothing: keep the last figure until a second has passed.
            if self._cpu_last is not None and time.time() - self._cpu_at < 1.0:
                return self._cpu_percent
            self._cpu_at = time.time()
            previous, self._cpu_last = self._cpu_last, now
            if previous is not None and now[1] > previous[1]:
                self._cpu_percent = round(max(0.0, min(100.0, (now[0] - previous[0]) / (now[1] - previous[1]) * 100)), 1)
            return self._cpu_percent

    @staticmethod
    def _memory():
        """(used_bytes, total_bytes) or None."""
        try:
            if sys.platform.startswith("linux"):
                info = {}
                for line in _read("/proc/meminfo").splitlines():
                    key, _, rest = line.partition(":")
                    info[key] = float(rest.split()[0]) * 1024
                total = info["MemTotal"]
                available = info.get("MemAvailable", info.get("MemFree", 0) + info.get("Buffers", 0) + info.get("Cached", 0))
                return total - available, total
            if sys.platform == "win32":
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(name, ctypes.c_ulonglong) for name in ("total", "avail", "total_page", "avail_page", "total_virtual", "avail_virtual", "avail_ext")]

                status = MEMORYSTATUSEX()
                status.length = ctypes.sizeof(MEMORYSTATUSEX)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
                return float(status.total - status.avail), float(status.total)
        except Exception:
            return None
        return None

    @staticmethod
    def _uptime():
        try:
            if sys.platform.startswith("linux"):
                return float(_read("/proc/uptime").split()[0])
            if sys.platform == "win32":
                import ctypes

                ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
                return ctypes.windll.kernel32.GetTickCount64() / 1000
        except Exception:
            pass
        return time.time() - _START

    def _disks(self):
        disks = []
        for path in self.paths:
            try:
                usage = shutil.disk_usage(path)
            except OSError:
                continue
            disks.append({"path": path, "used": usage.used, "total": usage.total, "free": usage.free, "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0})
        return disks

    def snapshot(self):
        memory = self._memory()
        load = None
        if hasattr(os, "getloadavg"):
            try:
                load = [round(x, 2) for x in os.getloadavg()]
            except OSError:
                load = None
        return {
            "cpu": self._cpu(),
            "cores": os.cpu_count(),
            "load": load,
            "memory": {"used": memory[0], "total": memory[1], "percent": round(memory[0] / memory[1] * 100, 1)} if memory and memory[1] else None,
            "disks": self._disks(),
            "uptime": int(self._uptime()),
        }

    def fetch_metrics(self):
        snap = self.snapshot()
        metrics = {"uptime_hours": (round(snap["uptime"] / 3600, 1), "t", "Oppetid")}
        if snap["cpu"] is not None:
            metrics["cpu_percent"] = (snap["cpu"], "%", "Prosessor")
        if snap["load"]:
            metrics["load_1m"] = (snap["load"][0], None, "Belastning (1 min)")
        if snap["memory"]:
            metrics["memory_percent"] = (snap["memory"]["percent"], "%", "Minne brukt")
            metrics["memory_used_gb"] = (round(snap["memory"]["used"] / 1e9, 1), "GB", "Minne brukt")
            metrics["memory_total_gb"] = (round(snap["memory"]["total"] / 1e9, 1), "GB", "Minne totalt")
        for i, disk in enumerate(snap["disks"], start=1):
            metrics[f"disk_{i}_percent"] = (disk["percent"], "%", f"Disk brukt {disk['path']}")
            metrics[f"disk_{i}_free_gb"] = (round(disk["free"] / 1e9, 1), "GB", f"Ledig plass {disk['path']}")
        return metrics

    def widget_data(self, widget_type, widget):
        if widget_type != "system_resources":
            raise NotImplementedError(widget_type)
        self._current()  # keeps the history used by graph widgets filling
        return self.snapshot()
