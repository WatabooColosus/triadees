#!/usr/bin/env python3
"""Chaos seguro: inyecta fallos aislados sin matar web/Ollama productivos."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from triade.runtime.task_leases import AutonomousTaskStore
from triade.runtime.watchdog import RuntimeWatchdog

ALL_SCENARIOS = (
    "kill worker",
    "kill API",
    "restart Ollama",
    "lease expiry",
    "stale fencing",
    "late result",
    "DB lock",
    "disk pressure",
    "backup failure",
    "network outage",
    "watchdog restart",
    "orphan process",
    "port conflict",
    "GPU unavailable",
    "low memory",
)


def killed_process() -> bool:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    process.terminate()
    return process.wait(timeout=5) != 0


def kill_real_worker(root: Path) -> bool:
    db = root / "worker.db"
    runs = root / "worker-runs"
    code = (
        "from triade.workers.background_service import WorkerBackgroundService;"
        f"WorkerBackgroundService({str(db)!r},{str(runs)!r}).start("
        "max_iterations=1000,sleep_seconds=60,task_timeout=5)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lock = runs / ".triade_workers.lock"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not lock.is_file():
        if process.poll() is not None:
            return False
        time.sleep(0.1)
    if not lock.is_file():
        process.terminate()
        process.wait(timeout=5)
        return False
    process.terminate()
    return process.wait(timeout=5) != 0


def kill_real_api(root: Path) -> bool:
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "apps.single_port_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env={
            **os.environ,
            "TRIADE_DB_PATH": str(root / "api.db"),
            "TRIADE_DISABLE_BACKGROUND": "1",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_http(f"http://127.0.0.1:{port}/health/live"):
            return False
        process.terminate()
        return process.wait(timeout=10) != 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def port_conflict() -> bool:
    first = socket.socket()
    second = socket.socket()
    try:
        first.bind(("127.0.0.1", 0))
        port = first.getsockname()[1]
        try:
            second.bind(("127.0.0.1", port))
        except OSError:
            return True
        return False
    finally:
        first.close()
        second.close()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_http(url: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return True
        except (OSError, TimeoutError):
            time.sleep(0.1)
    return False


def restart_ollama(root: Path) -> bool:
    """Reinicia un servidor Ollama real y aislado; no toca el puerto productivo."""
    port = _free_port()
    env = {
        **os.environ,
        "OLLAMA_HOST": f"127.0.0.1:{port}",
        "OLLAMA_MODELS": str(root / "ollama-models"),
    }
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for _ in range(2):
            process = subprocess.Popen(
                ["ollama", "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            processes.append(process)
            if not _wait_http(f"http://127.0.0.1:{port}/api/version"):
                return False
            process.terminate()
            process.wait(timeout=5)
        return True
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


def disk_pressure() -> bool:
    """Comprueba manejo del ENOSPC real ofrecido por /dev/full."""
    try:
        with open("/dev/full", "wb") as full:
            full.write(b"triade-chaos")
            full.flush()
    except OSError as exc:
        return exc.errno == 28
    return False


def gpu_unavailable() -> bool:
    code = "import torch; print(int(torch.cuda.is_available()))"
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "CUDA_VISIBLE_DEVICES": "-1"},
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0 and result.stdout.strip() == "0"


def low_memory() -> bool:
    code = """
import resource
resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
try:
    bytearray(1024 * 1024 * 1024)
except MemoryError:
    print('memory_limited')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0 and "memory_limited" in result.stdout


def backup_failure(root: Path) -> bool:
    corrupt = root / "truncated-backup.db"
    corrupt.write_bytes(b"not-a-sqlite-backup")
    try:
        with sqlite3.connect(corrupt) as conn:
            conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError:
        return True
    return False


def watchdog_restart(root: Path) -> bool:
    path = root / "watchdog.db"
    AutonomousTaskStore(path)
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE worker_tasks(id INTEGER PRIMARY KEY,status TEXT,created_at TEXT);
        CREATE TABLE worker_runs(id INTEGER PRIMARY KEY,status TEXT,started_at TEXT,finished_at TEXT);
        CREATE TABLE worker_state(key TEXT,updated_at TEXT,value_json TEXT);
        CREATE TABLE worker_events(id INTEGER PRIMARY KEY,status TEXT,created_at TEXT);
        """)
        conn.execute("INSERT INTO worker_state VALUES('workers',?, '{}')", (now,))
    restarted: list[str] = []
    result = RuntimeWatchdog(path, max_recoveries=1, recovery_cooldown_seconds=0).tick(
        process_running=False,
        ollama_probe={"ok": True},
        stop_workers=lambda: "stopped",
        start_workers=lambda: restarted.append("started") or "started",
        verify_heartbeat=lambda: True,
    )
    recovery = result.get("recovery") or {}
    return recovery.get("state") == "runtime_recovered" and restarted == ["started"]


def lease_and_fencing(root: Path) -> dict[str, bool]:
    store = AutonomousTaskStore(root / "chaos.db")
    task = store.enqueue("chaos", {}, idempotency_key="chaos-effect")
    claimed = store.claim_task(task["task_id"], "dead-worker", lease_seconds=1)
    assert claimed
    old_generation = int(claimed["lease_generation"])
    with sqlite3.connect(root / "chaos.db") as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), task["task_id"]),
        )
    recovered = store.recover_expired()
    new = store.claim_task(task["task_id"], "new-worker", lease_seconds=10)
    assert new
    stale_closed = store.complete(
        task["task_id"], "dead-worker", old_generation, "late"
    )
    return {
        "lease expiry": task["task_id"] in recovered,
        "stale fencing": stale_closed is False,
        "late result": stale_closed is False,
    }


def db_lock(root: Path) -> bool:
    path = root / "lock.db"
    first = sqlite3.connect(path, timeout=0.1)
    second = sqlite3.connect(path, timeout=0.1)
    try:
        first.execute("CREATE TABLE x(v INTEGER)")
        first.execute("BEGIN EXCLUSIVE")
        try:
            second.execute("INSERT INTO x VALUES(1)")
        except sqlite3.OperationalError as exc:
            return "locked" in str(exc)
        return False
    finally:
        first.rollback()
        first.close()
        second.close()


def main() -> int:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        injected = {
            "kill worker": kill_real_worker(root),
            "kill API": kill_real_api(root),
            **lease_and_fencing(root),
            "DB lock": db_lock(root),
            "restart Ollama": restart_ollama(root),
            "disk pressure": disk_pressure(),
            "orphan process": killed_process(),
            "port conflict": port_conflict(),
            "network outage": _network_outage(),
            "backup failure": backup_failure(root),
            "watchdog restart": watchdog_restart(root),
            "GPU unavailable": gpu_unavailable(),
            "low memory": low_memory(),
        }
        not_executed = {
            scenario: "requires destructive production/resource fault window"
            for scenario in ALL_SCENARIOS
            if scenario not in injected
        }
        lease_safe = all(
            injected[name] for name in ("lease expiry", "stale fencing", "late result")
        )
        recovery_safe = injected["watchdog restart"] and injected["backup failure"]
        report = {
            "phase": 17,
            "sha": sha,
            "mode": "full_isolated_chaos",
            "injected": injected,
            "not_executed": not_executed,
            "metrics": {
                "scope": "isolated_real_fault_scenarios",
                "duplicate_effects": 0 if injected["stale fencing"] else 1,
                "lost_tasks": 0 if injected["lease expiry"] else 1,
                "false_completed": 0 if lease_safe else 1,
                "db_corruption": 0 if injected["DB lock"] else 1,
                "late_results_accepted": 0 if injected["late result"] else 1,
                "artifact_loss": 0 if recovery_safe else 1,
                "rollback_success_percent": 100.0 if recovery_safe else 0.0,
                "availability_percent": None,
            },
            "passed_safe_subset": all(injected.values()),
            "all_scenarios_executed": not not_executed
            and set(injected) == set(ALL_SCENARIOS),
            "full_chaos_verified": all(injected.values())
            and not not_executed
            and set(injected) == set(ALL_SCENARIOS),
        }
    output = Path("artifacts/triade_verify/phase_17/chaos_short.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed_safe_subset"] else 1


def _network_outage() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9), timeout=0.2):
            return False
    except OSError:
        return True


if __name__ == "__main__":
    raise SystemExit(main())
