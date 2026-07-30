"""PID lock identity validation without trusting PID reuse."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LockInspection:
    status: str
    pid: int | None
    reason: str


class RuntimeProcessLock:
    @staticmethod
    def payload(pid: int | None = None) -> bytes:
        actual_pid = pid or os.getpid()
        cmdline = RuntimeProcessLock.command_line(actual_pid)
        return json.dumps(
            {
                "pid": actual_pid,
                "command_line": cmdline,
                "start_time": RuntimeProcessLock.start_time(actual_pid),
                "expected_token": "triade",
                "created_at": datetime.now(UTC).isoformat(),
            }
        ).encode()

    @staticmethod
    def command_line(pid: int) -> str:
        try:
            return (
                Path(f"/proc/{pid}/cmdline")
                .read_bytes()
                .replace(b"\0", b" ")
                .decode("utf-8", errors="replace")
            )
        except OSError:
            return ""

    @staticmethod
    def start_time(pid: int) -> int | None:
        """Jiffies-since-boot del proceso (campo 22 de /proc/<pid>/stat).

        El kernel garantiza que un PID reutilizado tiene un starttime
        distinto al del proceso original, incluso si por coincidencia
        cmdline es idéntico. Es la señal de identidad estándar (la misma
        que usa `ps`), a diferencia de un token constante que nunca puede
        distinguir procesos reales entre sí.
        """
        try:
            raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            # El campo "comm" (2do campo) va entre paréntesis y puede
            # contener espacios/paréntesis; los campos numéricos empiezan
            # después del último ")".
            rest = raw[raw.rfind(")") + 2 :].split()
            return int(rest[19])
        except (OSError, IndexError, ValueError):
            return None

    @classmethod
    def inspect(cls, path: Path) -> LockInspection:
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return LockInspection("invalid", None, f"read_failed:{exc}")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if not isinstance(payload, dict):
            try:
                pid = int(raw)
            except ValueError:
                return LockInspection("invalid", None, "unparseable_lock")
            return LockInspection(
                "live" if cls.pid_alive(pid) else "stale",
                pid,
                "legacy_pid_lock" if cls.pid_alive(pid) else "process_missing",
            )
        try:
            pid = int(payload["pid"])
        except (KeyError, TypeError, ValueError):
            return LockInspection("invalid", None, "pid_missing")
        if not cls.pid_alive(pid):
            return LockInspection("stale", pid, "process_missing")

        # Señal primaria: starttime del kernel. Si el lock grabó un
        # start_time y no coincide con el del ocupante actual del PID, es
        # con certeza un proceso distinto (PID reutilizado) sin importar si
        # cmdline coincide por coincidencia.
        recorded_start = payload.get("start_time")
        if recorded_start is not None:
            actual_start = cls.start_time(pid)
            try:
                recorded_start_int: int | None = int(recorded_start)
            except (TypeError, ValueError):
                recorded_start_int = None
            if (
                recorded_start_int is not None
                and actual_start is not None
                and recorded_start_int != actual_start
            ):
                return LockInspection("stale", pid, "process_identity_mismatch")

        # Respaldo para locks legacy sin start_time: heurística de cmdline
        # (relajada a propósito — un token constante no puede ser estricto
        # sin producir falsos positivos en procesos legítimos).
        actual = cls.command_line(pid).strip()
        expected = str(payload.get("expected_token") or "").strip()
        recorded = str(payload.get("command_line") or "").strip()
        if not actual:
            return LockInspection("stale", pid, "empty_cmdline")
        if recorded and recorded != actual and (not expected or expected not in actual):
            return LockInspection("stale", pid, "process_identity_mismatch")
        return LockInspection("live", pid, "process_identity_verified")

    @staticmethod
    def pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
