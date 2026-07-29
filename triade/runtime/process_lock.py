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
        actual = cls.command_line(pid)
        expected = str(payload.get("expected_token") or "")
        recorded = str(payload.get("command_line") or "")
        if (
            not actual
            or (expected and expected not in actual)
            or (recorded and recorded != actual)
        ):
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
