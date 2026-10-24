"""Private Colab-to-Drive telemetry. Counts only; no tokens, emails or prompts.

Start only from the owner's trusted Colab notebook. This module never opens
HTTP listeners or exports row contents. Stops when the Colab kernel stops.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TABLES = (
    "autonomous_tasks",
    "worker_runs",
    "worker_events",
    "metabolic_cycle",
    "runtime_health_snapshots",
    "neurons",
    "neuron_education_sessions",
    "neuron_education_applications",
    "governed_research_runs",
    "triade_weight_events",
    "improvement_proposals",
    "improvement_canaries",
    "trainable_adapters",
    "federated_nodes",
    "auth_users",
    "auth_email_identities",
)
_MONITOR_LOCK = threading.Lock()
_MONITOR: dict[str, Any] = {}


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def project_root() -> Path:
    specified = os.getenv("TRIADE_SOURCE_ROOT")
    candidates = [Path("/content/Triade_580_Limpia"), Path("/content/Triade")]
    if specified:
        candidates.insert(0, Path(specified))
    for path in candidates:
        if (path / "apps/single_port_app.py").is_file():
            return path.resolve()
    raise FileNotFoundError("No se encontró Tríade; instala el código primero")


def _git_sha(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
        return sha
    return None


def _local_http(path: str, *, port: int = 8010) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=4
        ) as response:
            payload = json.loads(response.read(4096))
            if not isinstance(payload, dict):
                return {"http": response.status, "format": "unexpected"}
            safe: dict[str, Any] = {"http": response.status}
            if path == "/api/auth/registration-status":
                safe.update(
                    {
                        "mode": payload.get("mode"),
                        "available": payload.get("available"),
                    }
                )
            elif path == "/health/source":
                safe.update(
                    {
                        "git_sha": payload.get("git_sha"),
                        "verified": payload.get("verified"),
                        "status": payload.get("status"),
                    }
                )
            else:
                safe["status"] = payload.get("status")
            return safe
    except urllib.error.HTTPError as exc:
        return {"http": exc.code, "protected": exc.code in (401, 403)}
    except (OSError, TimeoutError, ValueError) as exc:
        return {"error_type": type(exc).__name__}


def _ollama() -> dict[str, Any]:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=5
        ) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            return {"ok": False, "reason": "unexpected_response"}
        return {
            "ok": True,
            "models": sorted(
                {
                    str(item.get("name"))[:96]
                    for item in payload.get("models", [])
                    if isinstance(item, dict) and item.get("name")
                }
            ),
        }
    except (OSError, TimeoutError, ValueError) as exc:
        return {"ok": False, "error_type": type(exc).__name__}


def _database(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False}
    result: dict[str, Any] = {"present": True, "tables": {}}
    try:
        with sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=4
        ) as conn:
            conn.execute("PRAGMA query_only=ON")
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            result["table_count"] = len(names)
            for name in TABLES:
                result["tables"][name] = (
                    conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    if name in names
                    else None
                )
            if "autonomous_tasks" in names:
                cols = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(autonomous_tasks)")
                }
                if "status" in cols:
                    result["task_statuses"] = {
                        str(status): count
                        for status, count in conn.execute(
                            "SELECT status, COUNT(*) FROM autonomous_tasks GROUP BY status"
                        )
                    }
            result["quick_check"] = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
    except (sqlite3.Error, OSError) as exc:
        result["error_type"] = type(exc).__name__
    return result


def _resources() -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        import psutil

        vm = psutil.virtual_memory()
        result["ram_total_gb"] = round(vm.total / 2**30, 2)
        result["ram_free_gb"] = round(vm.available / 2**30, 2)
    except (ImportError, OSError):
        result["ram_available"] = False
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            result["gpu_summaries"] = proc.stdout.strip().splitlines()[:2]
    except (OSError, subprocess.SubprocessError):
        pass
    return result


def capture(root: Path | None = None, db: Path | None = None) -> dict[str, Any]:
    source = (root or project_root()).resolve()
    database = db or Path(
        os.getenv("TRIADE_DB_PATH", str(source / "triade/memory/triade.db"))
    )
    if not database.is_absolute():
        database = source / database
    return {
        "schema": "triade-live-audit-v2",
        "captured_at_utc": utc_now(),
        "source_git_sha": _git_sha(source),
        "source_dir_name": source.name,
        "data_scope": "aggregate_read_only_no_credentials_no_memory_text",
        "services": {
            "triade": _local_http("/health/live"),
            "source": _local_http("/health/source"),
            "registration": _local_http("/api/auth/registration-status"),
            "deep_auth_guard": _local_http("/health/deep"),
            "ollama": _ollama(),
        },
        "database": _database(database),
        "resources": _resources(),
    }


def _counters(snapshot: dict[str, Any]) -> dict[str, int]:
    source = snapshot.get("database", {}).get("tables", {})
    return {
        key: value
        for key, value in source.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def publish_once(
    destination: Path, *, root: Path | None = None, db: Path | None = None
) -> dict[str, Any]:
    """Publish only whitelisted aggregates via atomic private Drive file."""
    if not destination.is_dir():
        raise FileNotFoundError(
            "Monta Google Drive y crea la carpeta privada antes de publicar"
        )
    current = capture(root, db)
    path = destination / "triade-live-latest.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        old = {}
    if old.get("schema") == current["schema"]:
        old_counts = _counters(old)
        current["comparison"] = {
            "previous_at_utc": old.get("captured_at_utc"),
            "counter_deltas": {
                key: value - old_counts[key]
                for key, value in _counters(current).items()
                if key in old_counts
            },
        }
    temp = destination / f".triade-live-{os.getpid()}-{threading.get_ident()}.tmp"
    try:
        temp.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return current


def start_monitor(
    destination: Path | str = "/content/drive/MyDrive/Triade/telemetria",
    *,
    root: Path | None = None,
    db: Path | None = None,
    interval_seconds: int = 60,
) -> dict[str, Any]:
    """Idempotent background sampling in current kernel (not a cloud daemon)."""
    folder = Path(destination)
    if (
        str(folder).startswith("/content/drive/")
        and not Path("/content/drive/MyDrive").is_dir()
    ):
        raise RuntimeError("Monta Google Drive antes de activar la auditoría")
    folder.mkdir(parents=True, exist_ok=True)
    interval = max(60, int(interval_seconds))
    with _MONITOR_LOCK:
        thread = _MONITOR.get("thread")
        if thread is not None and thread.is_alive():
            return {
                "status": "already_active",
                "folder": str(_MONITOR["folder"]),
            }
        first = publish_once(folder, root=root, db=db)
        stop_event = threading.Event()

        def loop() -> None:
            while not stop_event.wait(interval):
                try:
                    publish_once(folder, root=root, db=db)
                except (OSError, ValueError, RuntimeError, sqlite3.Error):
                    # Keep previous sample with original timestamp on failure.
                    continue

        thread = threading.Thread(
            target=loop,
            name="triade-live-aggregate-monitor",
            daemon=True,
        )
        _MONITOR.update({"thread": thread, "stop": stop_event, "folder": folder})
        thread.start()
    return {
        "status": "active",
        "file": str(folder / "triade-live-latest.json"),
        "observed_at_utc": first["captured_at_utc"],
        "git_sha": first["source_git_sha"],
        "ollama_ok": first["services"]["ollama"]["ok"],
        "interval_seconds": interval,
    }


def stop_monitor() -> bool:
    with _MONITOR_LOCK:
        event = _MONITOR.get("stop")
        if event is None:
            return False
        event.set()
        _MONITOR.clear()
        return True
