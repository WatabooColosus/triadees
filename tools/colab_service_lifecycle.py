"""Strictly-scoped ownership of the Colab Tríade API process.

Never kill unrelated PIDs or expose remote control through public HTTP.
Use only in the owner's private Colab notebook.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any


def _psutil() -> Any:
    import psutil

    return psutil


def _verified_process(record: dict[str, object]) -> bool:
    """Fail closed on reused PID, different cwd/command or foreign port."""
    psutil = _psutil()
    try:
        pid = int(record["pid"])
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return False
        if abs(process.create_time() - float(record["create_time"])) > 1.0:
            return False
        if Path(process.cwd()).resolve() != Path(str(record["root"])).resolve():
            return False
        argv = process.cmdline()
        if not any("uvicorn" in word for word in argv):
            return False
        if "apps.single_port_app:app" not in argv:
            return False
        if "--port" not in argv or str(record["port"]) not in argv:
            return False
        if process.uids().effective != os.geteuid():
            return False
        listeners = [
            conn.pid
            for conn in psutil.net_connections(kind="inet")
            if conn.status == psutil.CONN_LISTEN
            and conn.laddr
            and conn.laddr.port == int(record["port"])
        ]
        return pid in listeners
    except (KeyError, TypeError, ValueError, OSError, psutil.Error):
        return False


def register_process(
    proc: subprocess.Popen[Any],
    root: Path,
    state_file: Path,
    *,
    port: int = 8010,
) -> dict[str, object]:
    """Persist ownership only after the managed API confirmed HTTP liveness."""
    psutil = _psutil()
    process = psutil.Process(proc.pid)
    if proc.poll() is not None:
        raise RuntimeError("El servidor terminó antes de registrar su identidad")
    record: dict[str, object] = {
        "pid": proc.pid,
        "create_time": process.create_time(),
        "root": str(root.resolve()),
        "port": port,
    }
    if not _verified_process(record):
        raise RuntimeError("Proceso API distinto al esperado: no se tomará control")
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_file.with_name(state_file.name + ".partial")
    temporary.write_text(json.dumps(record), encoding="utf-8")
    os.replace(temporary, state_file)
    return record


def process_owned(root: Path, state_file: Path, *, port: int = 8010) -> bool:
    if not state_file.is_file():
        return False
    try:
        record = json.loads(state_file.read_text(encoding="utf-8"))
        return (
            isinstance(record, dict)
            and record.get("root") == str(root.resolve())
            and record.get("port") == port
            and _verified_process(record)
        )
    except (OSError, ValueError, TypeError):
        return False


def stop_owned(
    root: Path,
    state_file: Path,
    *,
    port: int = 8010,
    timeout: int = 50,
) -> bool:
    """Stop the exact verified Colab-owned process; never SIGKILL strangers."""
    if not process_owned(root, state_file, port=port):
        raise PermissionError("Servicio no reconocido: no se finalizará otro proceso")
    record = json.loads(state_file.read_text(encoding="utf-8"))
    pid = int(record["pid"])
    os.kill(pid, signal.SIGTERM)
    psutil = _psutil()
    process = psutil.Process(pid)
    try:
        process.wait(timeout=timeout)
    except psutil.NoSuchProcess:
        pass
    except psutil.TimeoutExpired as exc:
        raise RuntimeError("La API no terminó ordenadamente; sin SIGKILL") from exc
    for _ in range(10):
        if not any(
            conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port
            for conn in psutil.net_connections(kind="inet")
        ):
            state_file.unlink(missing_ok=True)
            return True
        time.sleep(0.5)
    raise RuntimeError("Puerto todavía ocupado: actualización detenida")
