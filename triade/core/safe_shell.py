"""Safe Shell · ejecución de comandos whitelist seguros sin shell=True."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

WHITELIST: dict[str, list[str]] = {
    "git_status": ["git", "status", "--short"],
    "git_branch": ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    "git_log": ["git", "log", "-5", "--pretty=format:%h|%ad|%s", "--date=iso"],
    "ollama_list": ["ollama", "list"],
    "ollama_ps": ["ollama", "ps"],
    "pytest": ["python", "-m", "pytest"],
    "frontend_build": ["npm", "--prefix", "frontend", "run", "build"],
}

MAX_OUTPUT_LENGTH = 4000
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def list_allowed_commands() -> dict[str, Any]:
    """Devuelve diccionario de comandos whitelist con metadata."""
    commands = {}
    for key, cmd in WHITELIST.items():
        binary = shutil.which(cmd[0]) if cmd else None
        commands[key] = {
            "command": " ".join(cmd),
            "binary_found": bool(binary),
            "binary_path": binary or None,
        }
    return commands


def run_safe_command(command_key: str, timeout: int = 60) -> dict[str, Any]:
    """Ejecuta un comando whitelist con shell=False y timeout.

    Args:
        command_key: clave del comando en WHITELIST.
        timeout: timeout en segundos.

    Returns:
        dict con status, command_key, stdout, stderr, returncode, duration_ms.
    """
    import time as _time

    if command_key not in WHITELIST:
        return {
            "status": "error",
            "command_key": command_key,
            "error": f"Comando '{command_key}' no está en la whitelist.",
        }

    cmd = WHITELIST[command_key]
    binary = shutil.which(cmd[0])
    if not binary:
        return {
            "status": "error",
            "command_key": command_key,
            "error": f"Binary '{cmd[0]}' no encontrado en PATH.",
        }

    try:
        started = _time.perf_counter()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        duration_ms = round((_time.perf_counter() - started) * 1000, 2)
        stdout = (result.stdout or "")[:MAX_OUTPUT_LENGTH]
        stderr = (result.stderr or "")[:MAX_OUTPUT_LENGTH]
        returncode = result.returncode

        # Registrar evento (importación local para evitar ciclos)
        _record_event(command_key, returncode, duration_ms)

        return {
            "status": "ok" if returncode == 0 else "error",
            "command_key": command_key,
            "command": " ".join(cmd),
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "command_key": command_key,
            "error": f"Timeout después de {timeout}s.",
        }
    except OSError as exc:
        return {
            "status": "error",
            "command_key": command_key,
            "error": str(exc),
        }


def _record_event(command_key: str, returncode: int, duration_ms: float) -> None:
    try:
        from triade.core.event_bus import publish_event

        publish_event(
            "safe_shell_command_executed",
            "safe_shell",
            {
                "command_key": command_key,
                "returncode": returncode,
                "duration_ms": duration_ms,
            },
            severity="info",
        )
    except Exception:
        pass
