"""T-019 — System Monitor: monitoreo completo de CPU, RAM, GPU, VRAM,
disco, temperatura, red, con señales al Hipotálamo."""

import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    import hashlib
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS monitor_signals (
    signal_id      TEXT PRIMARY KEY,
    signal_type    TEXT NOT NULL,
    source         TEXT DEFAULT 'system_monitor',
    severity       TEXT DEFAULT 'info',
    metric_name    TEXT DEFAULT '',
    metric_value   REAL DEFAULT 0.0,
    threshold      REAL DEFAULT 0.0,
    message        TEXT DEFAULT '',
    payload_json   TEXT DEFAULT '{}',
    delivered      INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ms_type ON monitor_signals(signal_type, severity);
CREATE TABLE IF NOT EXISTS monitor_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    cpu_percent    REAL DEFAULT 0.0,
    ram_percent    REAL DEFAULT 0.0,
    ram_used_gb    REAL DEFAULT 0.0,
    ram_total_gb   REAL DEFAULT 0.0,
    gpu_percent    REAL DEFAULT 0.0,
    gpu_vram_used  REAL DEFAULT 0.0,
    gpu_vram_total REAL DEFAULT 0.0,
    gpu_temp_c     REAL DEFAULT 0.0,
    disk_percent   REAL DEFAULT 0.0,
    disk_free_gb   REAL DEFAULT 0.0,
    net_sent_mb    REAL DEFAULT 0.0,
    net_recv_mb    REAL DEFAULT 0.0,
    load_avg_1     REAL DEFAULT 0.0,
    load_avg_5     REAL DEFAULT 0.0,
    load_avg_15    REAL DEFAULT 0.0,
    ollama_status  TEXT DEFAULT 'unknown',
    raw_json       TEXT DEFAULT '{}',
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS monitor_thresholds (
    metric_name    TEXT PRIMARY KEY,
    warning        REAL DEFAULT 0.8,
    critical       REAL DEFAULT 0.95,
    direction      TEXT DEFAULT 'above'
);
"""


class SystemMonitor:
    """Monitor completo del sistema con señales al Hipotálamo."""

    DEFAULT_THRESHOLDS = {
        "cpu_percent": (80.0, 95.0),
        "ram_percent": (80.0, 95.0),
        "gpu_percent": (85.0, 98.0),
        "gpu_temp_c": (75.0, 90.0),
        "disk_percent": (85.0, 95.0),
    }

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._ensure_thresholds()

    def _ensure_thresholds(self):
        for metric, (warn, crit) in self.DEFAULT_THRESHOLDS.items():
            self._conn.execute(
                "INSERT OR IGNORE INTO monitor_thresholds (metric_name, warning, critical) VALUES (?,?,?)",
                (metric, warn, crit),
            )
        self._conn.commit()

    def snapshot(self, metrics: dict[str, float] | None = None) -> dict:
        """Toma snapshot del sistema y genera señales si hay umbrales excedidos."""
        now = utc_now()
        snap_id = _gen_id("snap")

        m = metrics or self._collect_metrics()

        self._conn.execute(
            """INSERT INTO monitor_snapshots
               (snapshot_id, cpu_percent, ram_percent, ram_used_gb, ram_total_gb,
                gpu_percent, gpu_vram_used, gpu_vram_total, gpu_temp_c,
                disk_percent, disk_free_gb, net_sent_mb, net_recv_mb,
                load_avg_1, load_avg_5, load_avg_15, ollama_status,
                raw_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (snap_id,
             m.get("cpu_percent", 0), m.get("ram_percent", 0),
             m.get("ram_used_gb", 0), m.get("ram_total_gb", 0),
             m.get("gpu_percent", 0), m.get("gpu_vram_used", 0),
             m.get("gpu_vram_total", 0), m.get("gpu_temp_c", 0),
             m.get("disk_percent", 0), m.get("disk_free_gb", 0),
             m.get("net_sent_mb", 0), m.get("net_recv_mb", 0),
             m.get("load_avg_1", 0), m.get("load_avg_5", 0),
             m.get("load_avg_15", 0), m.get("ollama_status", "unknown"),
             json.dumps(m, default=str), now),
        )

        signals = self._check_thresholds(m)
        self._conn.commit()

        return {
            "snapshot_id": snap_id,
            "metrics": m,
            "signals_generated": len(signals),
            "signals": signals,
        }

    def _collect_metrics(self) -> dict[str, float]:
        metrics = {}
        try:
            import psutil
            metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            metrics["ram_percent"] = mem.percent
            metrics["ram_used_gb"] = round(mem.used / (1024**3), 2)
            metrics["ram_total_gb"] = round(mem.total / (1024**3), 2)
            disk = psutil.disk_usage("/")
            metrics["disk_percent"] = disk.percent
            metrics["disk_free_gb"] = round(disk.free / (1024**3), 2)
            net = psutil.net_io_counters()
            metrics["net_sent_mb"] = round(net.bytes_sent / (1024**2), 2)
            metrics["net_recv_mb"] = round(net.bytes_recv / (1024**2), 2)
            load = psutil.getloadavg()
            metrics["load_avg_1"] = round(load[0], 2)
            metrics["load_avg_5"] = round(load[1], 2)
            metrics["load_avg_15"] = round(load[2], 2)
        except ImportError:
            metrics["cpu_percent"] = 0.0
            metrics["ram_percent"] = 0.0

        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(", ")
                if len(parts) >= 4:
                    metrics["gpu_percent"] = float(parts[0])
                    metrics["gpu_vram_used"] = float(parts[1])
                    metrics["gpu_vram_total"] = float(parts[2])
                    metrics["gpu_temp_c"] = float(parts[3])
        except Exception:
            pass

        metrics["ollama_status"] = self._check_ollama()
        return metrics

    @staticmethod
    def _check_ollama() -> str:
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return "healthy" if resp.status == 200 else "degraded"
        except Exception:
            return "unreachable"

    def _check_thresholds(self, metrics: dict) -> list[dict]:
        signals = []
        rows = self._conn.execute("SELECT * FROM monitor_thresholds").fetchall()
        for row in rows:
            name = row["metric_name"]
            val = metrics.get(name, 0.0)
            warn = row["warning"]
            crit = row["critical"]
            direction = row["direction"]

            triggered = False
            severity = "info"
            if direction == "above":
                if val >= crit:
                    triggered = True
                    severity = "critical"
                elif val >= warn:
                    triggered = True
                    severity = "warning"
            else:
                if val <= crit:
                    triggered = True
                    severity = "critical"
                elif val <= warn:
                    triggered = True
                    severity = "warning"

            if triggered:
                signal_id = _gen_id("sig")
                msg = f"{name}={val} exceeds {severity} threshold (warn={warn}, crit={crit})"
                self._conn.execute(
                    """INSERT INTO monitor_signals
                       (signal_id, signal_type, severity, metric_name,
                        metric_value, threshold, message, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (signal_id, "threshold_exceeded", severity, name,
                     val, crit, msg, utc_now()),
                )
                signals.append({
                    "signal_id": signal_id, "type": "threshold_exceeded",
                    "severity": severity, "metric": name,
                    "value": val, "message": msg,
                })
        return signals

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM monitor_snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        return dict(row) if row else None

    def latest_snapshot(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM monitor_snapshots ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def pending_signals(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM monitor_signals WHERE delivered=0 ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_delivered(self, signal_id: str) -> dict:
        self._conn.execute(
            "UPDATE monitor_signals SET delivered=1 WHERE signal_id=?", (signal_id,)
        )
        self._conn.commit()
        return {"signal_id": signal_id, "delivered": True}

    def signal_history(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM monitor_signals ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def set_threshold(self, metric_name: str, warning: float, critical: float,
                      direction: str = "above") -> dict:
        self._conn.execute(
            """INSERT INTO monitor_thresholds (metric_name, warning, critical, direction)
               VALUES (?,?,?,?)
               ON CONFLICT(metric_name) DO UPDATE SET warning=?, critical=?, direction=?""",
            (metric_name, warning, critical, direction, warning, critical, direction),
        )
        self._conn.commit()
        return {"metric": metric_name, "warning": warning, "critical": critical}

    def get_models_status(self) -> dict:
        """Check Ollama models status."""
        try:
            import urllib.request, json as _json
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = _json.loads(resp.read())
                models = [m.get("name", "unknown") for m in data.get("models", [])]
                return {"models_available": models, "count": len(models), "status": "healthy"}
        except Exception:
            return {"models_available": [], "count": 0, "status": "unreachable"}

    def get_scheduler_status(self) -> dict:
        """Check scheduler status."""
        try:
            from triade.workers.advanced_scheduler import AdvancedScheduler
            sch = AdvancedScheduler()
            return sch.doctor()
        except Exception:
            return {"status": "unreachable"}

    def get_workers_status(self) -> dict:
        """Check workers status."""
        try:
            from triade.workers.worker_supervisor import WorkerSupervisor
            ws = WorkerSupervisor()
            return ws.doctor()
        except Exception:
            return {"status": "unreachable"}

    def doctor(self) -> dict:
        snaps = self._conn.execute("SELECT COUNT(*) as c FROM monitor_snapshots").fetchone()["c"]
        signals = self._conn.execute("SELECT COUNT(*) as c FROM monitor_signals").fetchone()["c"]
        pending = self._conn.execute("SELECT COUNT(*) as c FROM monitor_signals WHERE delivered=0").fetchone()["c"]
        return {"snapshots": snaps, "total_signals": signals, "pending_signals": pending,
                "models": self.get_models_status(),
                "scheduler": self.get_scheduler_status(),
                "workers": self.get_workers_status()}
