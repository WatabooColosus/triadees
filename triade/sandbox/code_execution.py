"""Ejecución de Python en un contenedor local; nunca cae a ejecución en el host."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class CodeSandboxUnavailable(RuntimeError):
    pass


def _docker_executable() -> str | None:
    executable = shutil.which("docker")
    if executable:
        return executable
    if os.name == "nt":
        installed = (
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Docker/Docker/resources/bin/docker.exe"
        )
        if installed.is_file():
            return str(installed)
    return None


class DockerCodeSandbox:
    """Un recibo de ejecución no constituye evidencia de calidad ni aprobación."""

    OUTPUT_LIMIT = 64 * 1024

    def __init__(self, root: Path, *, image: str | None = None) -> None:
        self.root = root.resolve()
        self.image = image or os.getenv("TRIADE_CODE_SANDBOX_IMAGE", "")
        if not self.image:
            config = (
                Path(__file__).resolve().parents[2] / "config" / "code_sandbox.json"
            )
            try:
                self.image = str(
                    json.loads(config.read_text(encoding="utf-8"))["image_id"]
                )
            except (OSError, ValueError, KeyError, TypeError):
                self.image = ""

    def execute(self, source: str, budget: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._execute(source, budget)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CodeSandboxUnavailable(
                f"fallo del motor local: {type(exc).__name__}"
            ) from exc

    def _execute(self, source: str, budget: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(source, str) or not source.strip():
            raise ValueError("el código Python no puede estar vacío")
        payload = source.encode("utf-8")
        memory = min(512, int(budget["max_memory_mb"]))
        storage = min(64, int(budget["max_storage_mb"]))
        runtime = min(60, int(budget["max_runtime_seconds"]))
        if min(memory, storage, runtime) < 1:
            raise ValueError("el presupuesto debe ser positivo")
        if len(payload) > min(storage * 1024 * 1024, 256 * 1024):
            raise ValueError("el código excede el presupuesto de almacenamiento")
        # No tags flotantes, descargas automáticas, contextos remotos o fallback host.
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", self.image):
            raise CodeSandboxUnavailable(
                "TRIADE_CODE_SANDBOX_IMAGE requiere un ID sha256 local revisado"
            )
        docker = _docker_executable()
        if not docker:
            raise CodeSandboxUnavailable(
                "Docker local no está instalado; no se ejecutó código"
            )
        host = (
            "npipe:////./pipe/docker_engine"
            if os.name == "nt"
            else "unix:///var/run/docker.sock"
        )
        cli = [docker, "--host", host]
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "USERPROFILE",
                "HOME",
                "LOCALAPPDATA",
                "APPDATA",
                "PROGRAMDATA",
            }
        }
        inspect = subprocess.run(
            [*cli, "image", "inspect", "--format", "{{.Id}}", self.image],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            check=False,
        )
        if inspect.returncode or inspect.stdout.strip() != self.image:
            raise CodeSandboxUnavailable(
                "imagen revisada no disponible en el motor Docker local"
            )
        name = "triade-code-" + uuid.uuid4().hex
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "candidate.py").write_bytes(payload)
        create = [
            *cli,
            "create",
            "--name",
            name,
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--pids-limit",
            "32",
            "--memory",
            f"{memory}m",
            "--memory-swap",
            f"{memory}m",
            "--cpus",
            "1",
            "--ulimit",
            "nofile=64:64",
            "--log-driver",
            "none",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={storage}m",
            "--mount",
            f"type=bind,source={folder},target=/workspace,readonly",
            "--workdir",
            "/workspace",
            "--entrypoint",
            "python",
            self.image,
            "-I",
            "-B",
            "/workspace/candidate.py",
        ]
        process = None
        reader = None
        output = bytearray()
        overflow = threading.Event()
        started = time.monotonic()
        try:
            created = subprocess.run(
                create, capture_output=True, timeout=15, env=env, check=False
            )
            if created.returncode:
                raise CodeSandboxUnavailable(
                    "el motor rechazó la creación del sandbox aislado"
                )
            process = subprocess.Popen(
                [*cli, "start", "--attach", name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )

            def read_output() -> None:
                assert process is not None and process.stdout is not None
                while chunk := process.stdout.read(1024):
                    available = self.OUTPUT_LIMIT - len(output)
                    output.extend(chunk[:available])
                    if len(chunk) > available:
                        overflow.set()
                        process.kill()
                        return

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            try:
                returncode = process.wait(timeout=runtime)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("sandbox excedió el tiempo permitido") from exc
            reader.join(timeout=2)
            if reader.is_alive() or overflow.is_set():
                raise RuntimeError("sandbox excedió el límite de salida")
            if returncode != 0:
                raise RuntimeError(
                    f"ejecución de código fallida (exit_code={returncode})"
                )
            return {
                "backend": "docker_local",
                "image_id": self.image,
                "source_sha256": hashlib.sha256(payload).hexdigest(),
                "source_path": str(folder / "candidate.py"),
                "exit_code": returncode,
                "output": output.decode("utf-8", errors="replace"),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "network": "none",
                "quality_verified": False,
                "limits": {
                    "memory_mb": memory,
                    "runtime_seconds": runtime,
                    "storage_mb": storage,
                },
            }
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            # Se elimina únicamente el contenedor con nombre aleatorio creado aquí.
            removed = subprocess.run(
                [*cli, "rm", "--force", name],
                capture_output=True,
                timeout=15,
                env=env,
                check=False,
            )
            if reader is not None:
                reader.join(timeout=2)
            if process is not None and process.stdout is not None:
                process.stdout.close()
            if removed.returncode and process is not None:
                raise RuntimeError(f"no se confirmó la limpieza del sandbox {name}")
