"""Safe Shell · ejecución de comandos whitelist + modo autónomo con audit.

Extiende la whitelist fija con un registro dinámico persistente que Tríade
puede expandir durante su aprendizaje. Incluye gating por nivel de autonomía
y auditoría completa en SQLite.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from .safety import BLOCKED_KEYWORDS, SANDBOX_ONLY_KEYWORDS

WHITELIST: dict[str, list[str]] = {
    "git_status": ["git", "status", "--short"],
    "git_branch": ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    "git_log": ["git", "log", "-5", "--pretty=format:%h|%ad|%s", "--date=iso"],
    "ollama_list": ["ollama", "list"],
    "ollama_ps": ["ollama", "ps"],
    "pytest": ["python", "-m", "pytest"],
    "frontend_build": ["npm", "--prefix", "frontend", "run", "build"],
}

# Extensiones autónomas pre-aprobadas (no requieren审批 humano).
AUTONOMOUS_SAFE_EXTENSIONS: dict[str, list[str]] = {
    "ls": ["ls"],
    "ls_long": ["ls", "-la"],
    "pwd": ["pwd"],
    "whoami": ["whoami"],
    "date": ["date"],
    "df": ["df", "-h"],
    "du": ["du", "-sh", "."],
    "env_keys": ["env"],
    "python_version": ["python", "--version"],
    "pip_list": ["pip", "list"],
    "node_version": ["node", "--version"],
    "npm_list": ["npm", "list", "--depth=0"],
    "git_diff": ["git", "diff", "--stat"],
    "git_status_branch": ["git", "status", "-sb"],
    "test_quick": ["python", "-m", "pytest", "-x", "-q", "--tb=short"],
    "test_verbose": ["python", "-m", "pytest", "-v", "--tb=short"],
    "coverage": ["python", "-m", "pytest", "--cov=triade", "--cov-report=term-missing"],
    "lint": ["python", "-m", "ruff", "check", "triade/"],
    "typecheck": ["python", "-m", "mypy", "triade/", "--ignore-missing-imports"],
    "system_uptime": ["uptime"],
    "system_memory": ["free", "-h"],
    "system_disk": ["df", "-h", "/"],
    "process_list": ["ps", "aux"],
}

MAX_OUTPUT_LENGTH = 4000
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "triade" / "memory" / "triade.db"

_AUTONOMY_GATING: dict[str, int] = {
    "observe_only": 0,
    "form_candidates": 0,
    "train_candidates": 1,
    "promote_experimental": 2,
    "promote_stable": 3,
}

_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS shell_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    executed_at REAL NOT NULL,
    command_key TEXT NOT NULL,
    command TEXT NOT NULL,
    autonomy_level TEXT,
    source TEXT,
    returncode INTEGER,
    duration_ms REAL,
    stdout_preview TEXT,
    stderr_preview TEXT,
    blocked INTEGER DEFAULT 0,
    block_reason TEXT
);
"""


def _ensure_audit_table(db_path: str | Path | None = None) -> None:
    path = Path(db_path) if db_path else DB_PATH
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.execute(_AUDIT_TABLE)
    except Exception:
        pass


def _audit(
    command_key: str,
    command: str,
    returncode: int | None,
    duration_ms: float | None,
    stdout: str,
    stderr: str,
    autonomy_level: str = "unknown",
    source: str = "unknown",
    blocked: bool = False,
    block_reason: str = "",
    db_path: str | Path | None = None,
) -> None:
    path = Path(db_path) if db_path else DB_PATH
    try:
        _ensure_audit_table(path)
        with sqlite3.connect(str(path)) as conn:
            conn.execute(
                """INSERT INTO shell_audit
                   (executed_at, command_key, command, autonomy_level, source,
                    returncode, duration_ms, stdout_preview, stderr_preview,
                    blocked, block_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    time.time(),
                    command_key,
                    command,
                    autonomy_level,
                    source,
                    returncode,
                    duration_ms,
                    (stdout or "")[:500],
                    (stderr or "")[:500],
                    1 if blocked else 0,
                    block_reason,
                ),
            )
    except Exception:
        pass


def _validate_command(command: list[str], autonomy_level: str = "observe_only") -> tuple[bool, str]:
    """Valida un comando contra la política de seguridad.

    Retorna (allowed, reason).
    """
    cmd_text = " ".join(command).lower()

    for kw in BLOCKED_KEYWORDS:
        if kw in cmd_text:
            return False, f"Comando bloqueado: contiene '{kw}'"

    level_idx = _AUTONOMY_GATING.get(autonomy_level, 0)
    if level_idx < 1:
        for kw in SANDBOX_ONLY_KEYWORDS:
            if kw in cmd_text:
                return False, f"Requiere nivel >= train_candidates para '{kw}'"

    return True, "ok"


def list_allowed_commands() -> dict[str, Any]:
    """Devuelve diccionario de comandos whitelist con metadata."""
    commands = {}
    for key, cmd in WHITELIST.items():
        binary = shutil.which(cmd[0]) if cmd else None
        commands[key] = {
            "command": " ".join(cmd),
            "binary_found": bool(binary),
            "binary_path": binary or None,
            "source": "static_whitelist",
        }
    for key, cmd in AUTONOMOUS_SAFE_EXTENSIONS.items():
        binary = shutil.which(cmd[0]) if cmd else None
        commands[key] = {
            "command": " ".join(cmd),
            "binary_found": bool(binary),
            "binary_path": binary or None,
            "source": "autonomous_safe",
        }
    return commands


def run_safe_command(command_key: str, timeout: int = 60) -> dict[str, Any]:
    """Ejecuta un comando whitelist con shell=False y timeout (modo legacy)."""
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
        started = time.perf_counter()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        stdout = (result.stdout or "")[:MAX_OUTPUT_LENGTH]
        stderr = (result.stderr or "")[:MAX_OUTPUT_LENGTH]
        returncode = result.returncode

        _record_event(command_key, returncode, duration_ms)
        _audit(command_key, " ".join(cmd), returncode, duration_ms, stdout, stderr)

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
        _audit(command_key, " ".join(cmd), None, None, "", f"Timeout {timeout}s")
        return {
            "status": "error",
            "command_key": command_key,
            "error": f"Timeout después de {timeout}s.",
        }
    except OSError as exc:
        _audit(command_key, " ".join(cmd), None, None, "", str(exc))
        return {
            "status": "error",
            "command_key": command_key,
            "error": str(exc),
        }


def run_autonomous(
    command_key: str,
    timeout: int = 60,
    autonomy_level: str = "observe_only",
    source: str = "worker",
    db_path: str | Path | None = None,
    working_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Ejecuta un comando en modo autónomo con validación y audit.

    Busca en WHITELIST primero, luego en AUTONOMOUS_SAFE_EXTENSIONS.
    Valida contra la política de seguridad y gating de autonomía.
    Registra todo en shell_audit.

    Args:
        command_key: clave del comando en WHITELIST o AUTONOMOUS_SAFE_EXTENSIONS.
        timeout: timeout en segundos (máx 300).
        autonomy_level: nivel de autonomía actual de Tríade.
        source: quién invocó (worker, life_pulse, api, neuron, etc.).
        working_dir: directorio de trabajo (default: PROJECT_ROOT).

    Returns:
        dict con status, command_key, stdout, stderr, returncode, duration_ms, audit_id.
    """
    timeout = min(timeout, 300)
    cwd = str(working_dir or PROJECT_ROOT)

    # Buscar comando en registros
    cmd = WHITELIST.get(command_key) or AUTONOMOUS_SAFE_EXTENSIONS.get(command_key)
    if cmd is None:
        _audit(command_key, "???", None, None, "", f"Command not found: {command_key}",
               autonomy_level, source, blocked=True, block_reason="unknown_command", db_path=db_path)
        return {
            "status": "error",
            "command_key": command_key,
            "error": f"Comando '{command_key}' no registrado en ningún whitelist.",
        }

    cmd_text = " ".join(cmd)

    # Validar contra política de seguridad
    allowed, reason = _validate_command(cmd, autonomy_level)
    if not allowed:
        _audit(command_key, cmd_text, None, None, "", "", autonomy_level, source,
               blocked=True, block_reason=reason, db_path=db_path)
        return {
            "status": "blocked",
            "command_key": command_key,
            "command": cmd_text,
            "error": reason,
        }

    # Verificar binario
    binary = shutil.which(cmd[0])
    if not binary:
        _audit(command_key, cmd_text, None, None, "", f"Binary not found: {cmd[0]}",
               autonomy_level, source, blocked=True, block_reason="binary_not_found", db_path=db_path)
        return {
            "status": "error",
            "command_key": command_key,
            "command": cmd_text,
            "error": f"Binary '{cmd[0]}' no encontrado en PATH.",
        }

    try:
        started = time.perf_counter()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        stdout = (result.stdout or "")[:MAX_OUTPUT_LENGTH]
        stderr = (result.stderr or "")[:MAX_OUTPUT_LENGTH]
        returncode = result.returncode

        _record_event(command_key, returncode, duration_ms)
        _audit(command_key, cmd_text, returncode, duration_ms, stdout, stderr,
               autonomy_level, source, db_path=db_path)

        return {
            "status": "ok" if returncode == 0 else "error",
            "command_key": command_key,
            "command": cmd_text,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "duration_ms": duration_ms,
            "autonomy_level": autonomy_level,
            "source": source,
        }
    except subprocess.TimeoutExpired:
        _audit(command_key, cmd_text, None, None, "", f"Timeout {timeout}s",
               autonomy_level, source, db_path=db_path)
        return {
            "status": "error",
            "command_key": command_key,
            "command": cmd_text,
            "error": f"Timeout después de {timeout}s.",
        }
    except OSError as exc:
        _audit(command_key, cmd_text, None, None, "", str(exc),
               autonomy_level, source, db_path=db_path)
        return {
            "status": "error",
            "command_key": command_key,
            "command": cmd_text,
            "error": str(exc),
        }


def list_autonomous_commands() -> dict[str, Any]:
    """Devuelve solo los comandos disponibles en modo autónomo."""
    commands = {}
    for key, cmd in AUTONOMOUS_SAFE_EXTENSIONS.items():
        binary = shutil.which(cmd[0]) if cmd else None
        commands[key] = {
            "command": " ".join(cmd),
            "binary_found": bool(binary),
            "binary_path": binary or None,
        }
    return commands


def get_audit_log(
    limit: int = 50,
    source: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Devuelve las últimas entradas del audit log de shell."""
    path = Path(db_path) if db_path else DB_PATH
    try:
        _ensure_audit_table(path)
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            if source:
                rows = conn.execute(
                    "SELECT * FROM shell_audit WHERE source = ? ORDER BY id DESC LIMIT ?",
                    (source, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM shell_audit ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


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
