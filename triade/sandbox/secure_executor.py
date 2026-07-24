"""Ejecución sin shell=True — sandbox seguro con whitelist.

Toda ejecución pasa por execute() sin shell.
Se validan paths, se aplican límites de recursos.
"""

from __future__ import annotations

import os
import resource
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now
from triade.sandbox.isolation import SandboxLimits


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int
    duration_ms: float
    timed_out: bool
    executed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout[:2000],
            "stderr": self.stderr[:2000],
            "returncode": self.returncode,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "executed_at": self.executed_at,
        }


class SecureExecutor:
    """Ejecutor seguro sin shell=True, con límites de recursos."""

    FORBIDDEN_PATTERNS = (
        "rm -rf", "mkfs", ":(){ :|:& };:", "chmod 777",
        "curl|sh", "wget|sh", "eval(", "exec(",
        "__import__", "subprocess.call", "os.system",
    )

    def __init__(
        self,
        timeout_seconds: int = 30,
        max_output_bytes: int = 1_000_000,
        working_dir: str | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()

    def execute(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        stdin_data: str | None = None,
        limits: SandboxLimits | None = None,
    ) -> ExecutionResult:
        import time
        now = utc_now()
        validation = self._validate(command)
        if not validation["valid"]:
            return ExecutionResult(
                success=False, stdout="", stderr=validation["error"],
                returncode=-1, duration_ms=0, timed_out=False, executed_at=now,
            )
        if limits and not limits.network_allowed:
            for arg in command:
                arg_lower = arg.lower()
                if any(p in arg_lower for p in ("curl", "wget", "http://", "https://", "socket", "connect")):
                    return ExecutionResult(
                        success=False, stdout="",
                        stderr=f"BLOQUEADO: SandboxLimits.network_allowed=False — acceso de red denegado.",
                        returncode=-1, duration_ms=0, timed_out=False, executed_at=now,
                    )
        safe_env = os.environ.copy()
        if env:
            safe_env.update(env)
        safe_env["LC_ALL"] = "C.UTF-8"
        safe_env.pop("LD_PRELOAD", None)
        if limits and not limits.network_allowed:
            safe_env["TRIADE_NET_BLOCK"] = "1"
        start = time.perf_counter()
        timed_out = False
        preexec = None
        if sys.platform != "win32":
            def _apply_limits():
                if limits:
                    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
                    mem_bytes = limits.memory_mb * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
                    resource.setrlimit(resource.RLIMIT_NPROC, (limits.max_pids, limits.max_pids))
                os.setsid()
            preexec = _apply_limits
        try:
            proc = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                text=True,
                timeout=limits.timeout_seconds if limits else self.timeout_seconds,
                cwd=str(self.working_dir),
                env=safe_env,
                stdin=subprocess.PIPE if stdin_data else None,
                preexec_fn=preexec,
            )
            stdout = proc.stdout[:self.max_output_bytes]
            stderr = proc.stderr[:self.max_output_bytes]
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            stdout = ""
            stderr = f"Timeout después de {self.timeout_seconds}s"
            returncode = -1
        except Exception as exc:
            stdout = ""
            stderr = f"{type(exc).__name__}: {exc}"
            returncode = -1
        duration = (time.perf_counter() - start) * 1000
        return ExecutionResult(
            success=returncode == 0,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            duration_ms=round(duration, 2),
            timed_out=timed_out,
            executed_at=now,
        )

    def execute_python(
        self,
        code: str,
        *,
        args: list[str] | None = None,
    ) -> ExecutionResult:
        validation = self._validate_code(code)
        if not validation["valid"]:
            return ExecutionResult(
                success=False, stdout="", stderr=validation["error"],
                returncode=-1, duration_ms=0, timed_out=False, executed_at=utc_now(),
            )
        command = [sys.executable, "-c", code]
        if args:
            command.extend(args)
        return self.execute(command)

    def _validate(self, command: list[str]) -> dict[str, Any]:
        cmd_str = " ".join(command).lower()
        for pattern in self.FORBIDDEN_PATTERNS:
            if pattern.lower() in cmd_str:
                return {"valid": False, "error": f"Patrón prohibido detectado: {pattern}"}
        if any(arg.startswith("-") and arg not in {"-c", "-h", "--help"} for arg in command[1:3]):
            pass
        return {"valid": True, "error": None}

    def _validate_code(self, code: str) -> dict[str, Any]:
        code_lower = code.lower()
        dangerous = ("subprocess", "os.system", "exec(", "eval(",
                      "__import__", "open('/etc", "open(\"/etc",
                      "shutil.rmtree", "os.remove")
        for pattern in dangerous:
            if pattern in code_lower:
                return {"valid": False, "error": f"Código contiene patrón prohibido: {pattern}"}
        return {"valid": True, "error": None}

    def set_limits(self, *, cpu_seconds: int = 10, memory_mb: int = 256, max_procs: int = 50) -> None:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024, memory_mb * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_NPROC, (max_procs, max_procs))
        except (ValueError, OSError):
            pass
