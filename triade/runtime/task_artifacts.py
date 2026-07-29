"""Canonical, atomically published artifacts for autonomous tasks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
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


class AtomicArtifactWriter:
    @staticmethod
    def write_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        with temporary.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @classmethod
    def write_json(cls, path: Path, value: Any) -> None:
        cls.write_bytes(
            path,
            json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        )


class CanonicalTaskArtifacts:
    def __init__(self, worker_run_dir: Path, task_id: str) -> None:
        if not task_id or task_id == "None":
            raise ValueError("canonical_task_id_required")
        self.task_id = task_id
        self.path = worker_run_dir / "tasks" / task_id

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
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
    ) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
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
            AtomicArtifactWriter.write_json(self.path / name, value)
        for name in REQUIRED_LOGS:
            log = self.path / name
            if not log.exists():
                AtomicArtifactWriter.write_bytes(log, b"")
        artifact_hashes = {
            name: self.sha256(self.path / name)
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
        AtomicArtifactWriter.write_json(self.path / "manifest.json", manifest)
        self.verify()
        return self.path / "result.json"

    def verify(self) -> None:
        manifest_path = self.path / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("missing_manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, expected in manifest["artifact_hashes"].items():
            target = self.path / name
            if not target.is_file():
                raise FileNotFoundError(f"missing_artifact:{name}")
            if self.sha256(target) != expected:
                raise ValueError(f"artifact_hash_mismatch:{name}")
