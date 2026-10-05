"""Strongly cancellable execution for governed worker tasks."""

from __future__ import annotations

import contextlib
import json
import multiprocessing
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import traceback

CHILD_EXECUTION_ERRORS = (
    OSError,
    ImportError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    TimeoutError,
    # Sin estos tipos, una excepción escapa de `_callable_child`, el pipe se
    # cierra sin `send` y el padre sólo ve `child_closed_pipe_without_result`.
    # El traceback real se escribía en el stderr del proceso API, nunca en el
    # `stderr.log` de la tarea: un fallo quedaba con 0 bytes y sin diagnóstico.
    AttributeError,
    IndexError,
    ArithmeticError,
    AssertionError,
    NameError,
)


class ProcessHandle(Protocol):
    @property
    def pid(self) -> int | None: ...

    @property
    def exitcode(self) -> int | None: ...

    def is_alive(self) -> bool: ...

    def join(self, timeout: float | None = None) -> None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


@dataclass(slots=True)
class GovernedExecutionOutcome:
    status: str
    executed: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    exit_code: int | None = None
    termination_signal: int | None = None
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    quarantine_ref: str | None = None
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _append_stderr(stderr_path: str, text: str) -> None:
    """Escribe el traceback en el log de la tarea sin interdependent del redirect.

    El `redirect_stderr` de `contextlib` sólo cubre escrituras Python dentro del
    `with`; un traceback de excepción se escribe en el fd 2 real del proceso.
    """
    try:
        Path(stderr_path).open("a", encoding="utf-8").write(text)
    except OSError:
        pass


def _callable_child(
    send: Any,
    function: Callable[..., dict[str, Any]],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    stdout_path: str,
    stderr_path: str,
) -> None:
    # `setsid` crea una sesión POSIX para poder cancelar el árbol completo;
    # Windows no expone esa llamada y el proceso hijo ya está aislado por
    # `multiprocessing`, así que se omite allí.
    if hasattr(os, "setsid"):
        os.setsid()
    try:
        with (
            Path(stdout_path).open("a", encoding="utf-8") as stdout,
            Path(stderr_path).open("a", encoding="utf-8") as stderr,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = function(*args, **kwargs)
        send.send({"kind": "result", "value": result})
    except CHILD_EXECUTION_ERRORS as exc:
        _append_stderr(
            stderr_path,
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )
        send.send(
            {
                "kind": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    except BaseException as exc:  # noqa: BLE001
        # Una excepción propia (sqlite3.OperationalError, cancelled, etc.) no
        # estaba en la tupla y escapaba del hijo. El pipe se cerraba sin
        # resultado y el traceback real terminaba en el stderr del proceso API,
        # de modo que `stderr.log` quedaba vacío y el padre reportaba un
        # `child_closed_pipe_without_result` sin causa. Ahora el traceback se
        # escribe en el log de la tarea y el padre recibe el tipo real.
        _append_stderr(
            stderr_path,
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )
        send.send(
            {
                "kind": "error",
                "error_type": type(exc).__name__,
                "error": str(exc) or repr(exc),
            }
        )
    finally:
        send.close()


class GovernedTaskExecutor:
    def __init__(
        self, quarantine_root: str | Path = "runs/quarantine/timeouts"
    ) -> None:
        self.quarantine_root = Path(quarantine_root)

    def execute_callable(
        self,
        function: Callable[..., dict[str, Any]],
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        timeout_seconds: float,
        artifact_dir: str | Path,
        heartbeat: Callable[[], bool] | None = None,
        heartbeat_interval_seconds: float = 15.0,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> GovernedExecutionOutcome:
        artifact = Path(artifact_dir)
        artifact.mkdir(parents=True, exist_ok=True)
        stdout_path = artifact / "stdout.log"
        stderr_path = artifact / "stderr.log"
        stdout_path.touch(exist_ok=True)
        stderr_path.touch(exist_ok=True)
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(
            target=_callable_child,
            args=(
                send,
                function,
                args,
                kwargs or {},
                str(stdout_path),
                str(stderr_path),
            ),
            daemon=False,
        )
        started = time.monotonic()
        process.start()
        send.close()

        # El resultado viaja por el pipe, pero el padre sólo lo leía
        # DESPUÉS de ver al hijo muerto. Si el resultado serializado
        # supera el búfer del pipe (~4-16 KB en Windows), el hilo
        # feeder del hijo bloquea a mitad de escritura, el hijo nunca
        # sale y el padre esperaba hasta el timeout: cualquier handler
        # con resultado grande (pulse_check manda 21 KB) moría como
        # `task_timeout` aunque terminara en 2 s. Se drena en un hilo
        # daemon mientras el bucle sigue imponiendo plazo, lease y
        # cancelación.
        payload_box: dict[str, Any] = {}

        def _drain_pipe() -> None:
            try:
                payload_box["payload"] = receive.recv()
            except (EOFError, OSError):
                payload_box["payload"] = {
                    "kind": "error",
                    "error_type": "ChildProcessError",
                    "error": "child_closed_pipe_without_result",
                }

        reader = threading.Thread(
            target=_drain_pipe, daemon=True, name="governed-pipe-drain"
        )
        reader.start()

        deadline = started + max(0.001, timeout_seconds)
        next_heartbeat = started + max(0.01, heartbeat_interval_seconds)
        lease_lost = False
        cancelled = False
        while process.is_alive():
            now = time.monotonic()
            if cancellation_check and cancellation_check():
                cancelled = True
                break
            if now >= deadline:
                break
            wait_until = min(deadline, next_heartbeat) if heartbeat else deadline
            process.join(max(0.001, wait_until - now))
            now = time.monotonic()
            if process.is_alive() and heartbeat and now >= next_heartbeat:
                if not heartbeat():
                    lease_lost = True
                    break
                next_heartbeat = now + max(0.01, heartbeat_interval_seconds)
        if process.is_alive():
            termination_signal = self.terminate(process)
            quarantine = self.quarantine_partial_artifacts(artifact)
            return GovernedExecutionOutcome(
                status="cancelled"
                if cancelled
                else "lease_lost"
                if lease_lost
                else "timeout",
                executed=True,
                error=(
                    "cancellation_requested"
                    if cancelled
                    else "lease_renewal_rejected"
                    if lease_lost
                    else "task_timeout"
                ),
                exit_code=process.exitcode,
                termination_signal=termination_signal,
                stdout_ref=str(quarantine / "stdout.log"),
                stderr_ref=str(quarantine / "stderr.log"),
                quarantine_ref=str(quarantine),
                elapsed_seconds=round(time.monotonic() - started, 6),
            )

        reader.join(timeout=5.0)
        payload = payload_box.get("payload")
        if payload is None:
            # El hijo murió antes de poder enviar nada (spawn, unpickle o
            # DuplicateHandle con WinError 5). Sin esta nota el `stderr.log`
            # quedaba en 0 bytes y el dead_letter no tenía causa accionable.
            _append_stderr(
                str(stderr_path),
                "child_exited_without_result: "
                f"exit_code={process.exitcode}\n"
                "El hijo no alcanzó a enviar un resultado por el pipe. "
                "En Windows esto suele ser un fallo de `spawn` al importar el "
                "módulo principal o al duplicar handles (WinError 5); el "
                "traceback real quedó en el stderr del proceso API.\n",
            )
            payload = {
                "kind": "error",
                "error_type": "ChildProcessError",
                "error": f"child_exited_without_result:{process.exitcode}",
            }
        receive.close()
        elapsed = round(time.monotonic() - started, 6)
        value = payload.get("value")
        if payload.get("kind") == "result" and isinstance(value, dict):
            return GovernedExecutionOutcome(
                status="completed",
                executed=True,
                result=dict(value),
                exit_code=process.exitcode,
                stdout_ref=str(stdout_path),
                stderr_ref=str(stderr_path),
                elapsed_seconds=elapsed,
            )
        return GovernedExecutionOutcome(
            status="failed",
            executed=True,
            error=f"{payload.get('error_type')}: {payload.get('error')}",
            exit_code=process.exitcode,
            stdout_ref=str(stdout_path),
            stderr_ref=str(stderr_path),
            elapsed_seconds=elapsed,
        )

    def execute_subprocess(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float,
        artifact_dir: str | Path,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
    ) -> GovernedExecutionOutcome:
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("non_empty_argv_required")
        artifact = Path(artifact_dir)
        artifact.mkdir(parents=True, exist_ok=True)
        stdout_path = artifact / "stdout.log"
        stderr_path = artifact / "stderr.log"
        started = time.monotonic()
        process = subprocess.Popen(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=max(0.001, timeout_seconds))
            stdout_path.write_text(stdout or "", encoding="utf-8")
            stderr_path.write_text(stderr or "", encoding="utf-8")
        except subprocess.TimeoutExpired as exc:
            termination_signal = self._terminate_subprocess(process)
            stdout, stderr = process.communicate()
            stdout_path.write_text(
                self._as_text(stdout) or self._as_text(exc.stdout), encoding="utf-8"
            )
            stderr_path.write_text(
                self._as_text(stderr) or self._as_text(exc.stderr), encoding="utf-8"
            )
            quarantine = self.quarantine_partial_artifacts(artifact)
            return GovernedExecutionOutcome(
                status="timeout",
                executed=True,
                error="subprocess_timeout",
                exit_code=process.returncode,
                termination_signal=termination_signal,
                stdout_ref=str(quarantine / "stdout.log"),
                stderr_ref=str(quarantine / "stderr.log"),
                quarantine_ref=str(quarantine),
                elapsed_seconds=round(time.monotonic() - started, 6),
            )
        return GovernedExecutionOutcome(
            status="completed" if process.returncode == 0 else "failed",
            executed=True,
            result={"returncode": process.returncode},
            error=None
            if process.returncode == 0
            else f"exit_code:{process.returncode}",
            exit_code=process.returncode,
            stdout_ref=str(stdout_path),
            stderr_ref=str(stderr_path),
            elapsed_seconds=round(time.monotonic() - started, 6),
        )

    @staticmethod
    def terminate(process: ProcessHandle, grace_seconds: float = 0.5) -> int:
        if process.pid is None:
            return signal.SIGTERM
        if os.name == "nt":
            process.terminate()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                process.terminate()
        process.join(grace_seconds)
        if process.is_alive():
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    process.kill()
            process.join(grace_seconds)
            return signal.SIGKILL
        return signal.SIGTERM

    @staticmethod
    def _as_text(value: bytes | str | None) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value or ""

    @staticmethod
    def _terminate_subprocess(
        process: subprocess.Popen[str], grace_seconds: float = 0.5
    ) -> int:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                process.kill()
            return signal.SIGTERM
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return signal.SIGTERM
        try:
            process.wait(timeout=grace_seconds)
            return signal.SIGTERM
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=grace_seconds)
            return signal.SIGKILL

    def quarantine_partial_artifacts(self, artifact_dir: Path) -> Path:
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        target = self.quarantine_root / f"{artifact_dir.name}-{uuid4().hex[:12]}"
        if artifact_dir.exists():
            shutil.move(str(artifact_dir), str(target))
        else:
            target.mkdir(parents=True, exist_ok=False)
        manifest = {
            "status": "quarantined_after_timeout",
            "source": str(artifact_dir),
            "created_at": time.time(),
        }
        (target / "quarantine.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )
        return target
