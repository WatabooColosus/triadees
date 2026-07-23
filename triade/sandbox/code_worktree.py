"""Sandbox de código real sobre git worktree con regresión y rollback."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


class CodeWorktreeSandbox:
    ALLOWED_TESTS = {
        "pytest": ["python", "-m", "pytest", "-q"],
        "pytest_quick": ["python", "-m", "pytest", "-q", "-x"],
        "compileall": ["python", "-m", "compileall", "-q", "triade", "apps"],
    }
    FORBIDDEN_PARTS = {".git", ".env", "identity_core", "secrets", "private_keys"}

    def __init__(self, repo_path: str | Path, evidence_dir: str | Path = "runs/code_sandbox") -> None:
        self.repo_path = Path(repo_path).resolve()
        self.evidence_dir = (self.repo_path / evidence_dir).resolve() if not Path(evidence_dir).is_absolute() else Path(evidence_dir)
        if not (self.repo_path / ".git").exists():
            raise ValueError("repo_path debe ser un repositorio Git")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def run_patch(self, patch_text: str, *, tests: list[str], timeout: int = 300) -> dict[str, Any]:
        if not patch_text.strip() or len(patch_text.encode()) > 512_000:
            raise ValueError("parche vacío o demasiado grande")
        for line in patch_text.splitlines():
            if line.startswith(("+++ ", "--- ")):
                path = line[4:].removeprefix("a/").removeprefix("b/")
                if any(part in self.FORBIDDEN_PARTS for part in Path(path).parts):
                    raise ValueError(f"ruta protegida en parche: {path}")
        unknown = set(tests) - self.ALLOWED_TESTS.keys()
        if unknown:
            raise ValueError(f"tests no permitidos: {sorted(unknown)}")

        sandbox_id = f"code-{uuid4().hex[:12]}"
        base_commit = self._run(["git", "rev-parse", "HEAD"], self.repo_path, 30)["stdout"].strip()
        worktree_parent = Path(tempfile.mkdtemp(prefix="triade-worktree-"))
        worktree = worktree_parent / "repo"
        evidence_path = self.evidence_dir / f"{sandbox_id}.json"
        result: dict[str, Any] = {
            "sandbox_id": sandbox_id, "base_commit": base_commit,
            "patch_sha256": hashlib.sha256(patch_text.encode()).hexdigest(),
            "tests": tests, "network_isolation": "not_provided_by_worktree", "promoted": False,
        }
        added = False
        try:
            add = self._run(["git", "worktree", "add", "--detach", str(worktree), base_commit], self.repo_path, 60)
            if add["returncode"] != 0:
                raise RuntimeError(add["stderr"])
            added = True
            patch_file = worktree_parent / "change.patch"
            patch_file.write_text(patch_text, encoding="utf-8")
            applied = self._run(["git", "apply", "--whitespace=error", str(patch_file)], worktree, 60)
            result["apply"] = applied
            if applied["returncode"] != 0:
                result.update({"status": "rolled_back", "rollback_reason": "patch_apply_failed"})
                return self._finish(result, evidence_path)
            checks = []
            for name in tests:
                check = self._run(self.ALLOWED_TESTS[name], worktree, timeout)
                checks.append({"name": name, **check})
                if check["returncode"] != 0:
                    rollback = self._run(["git", "reset", "--hard", base_commit], worktree, 30)
                    clean = self._run(["git", "clean", "-fd"], worktree, 30)
                    result.update({"status": "rolled_back", "rollback_reason": f"regression:{name}",
                                   "checks": checks, "rollback": {"reset": rollback, "clean": clean}})
                    return self._finish(result, evidence_path)
            diff = self._run(["git", "diff", "--binary", base_commit], worktree, 60)
            result.update({"status": "validated", "checks": checks, "validated_patch": diff["stdout"],
                           "rollback_available": True})
            return self._finish(result, evidence_path)
        finally:
            if added:
                self._run(["git", "worktree", "remove", "--force", str(worktree)], self.repo_path, 60)
            shutil.rmtree(worktree_parent, ignore_errors=True)

    @staticmethod
    def _run(command: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=False)
            return {"command": command, "returncode": proc.returncode,
                    "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-8000:],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2)}
        except subprocess.TimeoutExpired as exc:
            return {"command": command, "returncode": 124, "stdout": str(exc.stdout or "")[-8000:],
                    "stderr": "timeout", "duration_ms": round((time.perf_counter() - started) * 1000, 2)}

    @staticmethod
    def _finish(result: dict[str, Any], evidence_path: Path) -> dict[str, Any]:
        serializable = {**result, "validated_patch": (result.get("validated_patch") or "")[:200_000]}
        evidence_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
        result["evidence_path"] = str(evidence_path)
        return result
