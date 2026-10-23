"""Canonical, atomically published artifacts for autonomous tasks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from triade.core.contracts import utc_now

REQUIRED_JSON = (
    "input.json",
    "execution.json",
    "result.json",
    "evidence.json",
    "resource_usage.json",
    "postconditions.json",
    "rollback.json",
)
REQUIRED_LOGS = ("stdout.log", "stderr.log")


def _io_path(path: Path) -> Path:
    """Use Windows extended paths without changing persisted evidence refs."""
    if os.name != "nt":
        return path
    absolute = str(path.absolute())
    if absolute.startswith("\\\\?\\"):
        return path
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


class AtomicArtifactWriter:
    @staticmethod
    def write_bytes(path: Path, content: bytes) -> None:
        path = _io_path(path)
        # Un timeout gobernado puede mover el staging a cuarentena mientras el
        # cierre canónico todavía está escribiendo. En Windows esa carrera se
        # manifiesta como FileNotFoundError sobre el temporal; reabrir el
        # directorio una vez conserva el cierre y deja la cuarentena intacta.
        for intento in range(3):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
                with temporary.open("wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                break
            except FileNotFoundError:
                if intento == 2:
                    raise
                continue
        # POSIX permite sincronizar el directorio; Windows no permite abrirlo
        # como descriptor, aunque os.replace ya sea atómico en el mismo volumen.
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    @classmethod
    def write_json(cls, path: Path, value: Any) -> None:
        cls.write_bytes(
            path,
            json.dumps(value, ensure_ascii=False, indent=2, default=str).encode(
                "utf-8"
            ),
        )


class CanonicalTaskArtifacts:
    def __init__(self, worker_run_dir: Path, task_id: str, *, attempt: int = 1) -> None:
        if not task_id or task_id == "None":
            raise ValueError("canonical_task_id_required")
        self.task_id = task_id
        suffix = "" if attempt <= 1 else f".attempt-{attempt}"
        self.path = worker_run_dir / "tasks" / f"{task_id}{suffix}"

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with _io_path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def finalize(
        self,
        *,
        task: dict[str, Any],
        execution: dict[str, Any],
        result: dict[str, Any],
        worker_id: str,
        lease_generation: int,
        payload_hash: str,
        status: str,
        target_path: Path | None = None,
    ) -> Path:
        target = _io_path(target_path or self.path)
        target.mkdir(parents=True, exist_ok=True)
        values = {
            "input.json": task,
            "execution.json": execution,
            "result.json": result,
            "evidence.json": {"evidence": execution.get("evidence", [])},
            "resource_usage.json": execution.get("resource_usage", {}),
            "postconditions.json": execution.get("postconditions", {}),
            "rollback.json": execution.get("rollback", {}),
        }
        for name, value in values.items():
            AtomicArtifactWriter.write_json(target / name, value)
        for name in REQUIRED_LOGS:
            log = target / name
            if not log.exists():
                AtomicArtifactWriter.write_bytes(log, b"")
        artifact_hashes = {
            name: self.sha256(target / name)
            for name in (*REQUIRED_JSON, *REQUIRED_LOGS)
        }
        manifest = {
            "task_id": self.task_id,
            "worker_id": worker_id,
            "lease_generation": lease_generation,
            "task_type": task.get("task_type"),
            "payload_hash": payload_hash,
            "result_hash": artifact_hashes["result.json"],
            "artifact_hashes": artifact_hashes,
            "created_at": task.get("created_at"),
            "finalized_at": utc_now(),
            "status": status,
            "executor": "GovernedTaskExecutor",
            "code_version": os.getenv("TRIADE_CODE_VERSION", "unavailable"),
        }
        AtomicArtifactWriter.write_json(target / "manifest.json", manifest)
        self.verify(target)
        return target / "result.json"

    def verify(self, target_path: Path | None = None) -> None:
        target_root = _io_path(target_path or self.path)
        manifest_path = target_root / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("missing_manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, expected in manifest["artifact_hashes"].items():
            target = target_root / name
            if not target.is_file():
                raise FileNotFoundError(f"missing_artifact:{name}")
            if self.sha256(target) != expected:
                raise ValueError(f"artifact_hash_mismatch:{name}")

    def staging_path(self) -> Path:
        # Task identity is retained in the manifest and canonical destination.
        # Repeating it here consumes Windows path space before handler files.
        return self.path.parent / f".{uuid4().hex}.staging"

    def publish(self, staging_path: Path) -> None:
        source = staging_path.resolve()
        destination = self.path.resolve()
        if source.parent != destination.parent:
            raise ValueError("staging_must_share_canonical_parent")
        if self.path.exists():
            raise FileExistsError(f"canonical_artifact_path_exists:{self.path}")
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            move = cast(Any, ctypes).WinDLL(
                "kernel32", use_last_error=True
            ).MoveFileExW
            move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
            move.restype = wintypes.BOOL
            # MOVEFILE_WRITE_THROUGH; sin reemplazar evidencia existente.
            if not move(str(source), str(destination), 0x8):
                raise cast(Any, ctypes).WinError(
                    cast(Any, ctypes).get_last_error()
                )
            return
        os.replace(staging_path, self.path)
        directory_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def quarantine(staging_path: Path, quarantine_root: Path) -> Path:
        quarantine_root.mkdir(parents=True, exist_ok=True)
        target = quarantine_root / f"{staging_path.name}-{uuid4().hex[:8]}"
        shutil.move(str(staging_path), target)
        return target
