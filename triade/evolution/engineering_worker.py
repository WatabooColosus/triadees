"""Engineering Evolution Worker: cambios de código aislados, medidos y reversibles."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROTECTED = (
    ".git/",
    ".env",
    "identity_core",
    "triade/memory/",
    "artifacts/",
    "runs/",
    "data/",
    "tests/",
)
ALLOWED_COMMANDS = {
    "compile": ["python", "-m", "compileall", "-q", "triade", "apps"],
    "tests": [
        "python",
        "-m",
        "pytest",
        "-q",
        "tests/test_learning_pipeline.py",
        "tests/test_engineering_evolution_worker.py",
        "tests/test_autonomous_research.py",
        "tests/test_capability_goal_orchestrator.py",
    ],
    "lint": ["python", "-m", "ruff", "check", "triade", "apps"],
}


@dataclass(frozen=True)
class EvolutionBudget:
    max_files: int = 12
    max_commands: int = 8
    max_minutes: int = 30
    max_patch_bytes: int = 100_000
    max_disk_mb: int = 2048
    max_gpu_minutes: float = 0.0


class EngineeringEvolutionWorker:
    def __init__(
        self, repo: str | Path = ".", db_path: str | Path = "triade/memory/triade.db"
    ) -> None:
        self.repo = Path(repo).resolve()
        self.db_path = Path(db_path)
        self.root = (self.repo / "artifacts/evolution_worktrees").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS engineering_evolution_runs(
              evolution_id TEXT PRIMARY KEY, objective TEXT, hypothesis TEXT, baseline_commit TEXT,
              worktree_path TEXT, status TEXT, budget_json TEXT, patch_sha256 TEXT, changed_files_json TEXT,
              baseline_result_json TEXT, candidate_result_json TEXT, review_json TEXT, approved_by TEXT,
              commit_hash TEXT, rollback_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            c.execute("""CREATE TABLE IF NOT EXISTS engineering_evolution_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT,evolution_id TEXT,event TEXT,decision TEXT,payload_json TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    def propose(
        self,
        objective: str,
        hypothesis: str,
        patch: str,
        *,
        budget: EvolutionBudget | None = None,
    ) -> dict[str, Any]:
        budget = budget or EvolutionBudget()
        eid = "evo-" + uuid.uuid4().hex[:12]
        started = time.monotonic()
        if len(patch.encode()) > budget.max_patch_bytes:
            return {"status": "blocked", "reason": "patch_budget_exceeded"}
        baseline = self._git(["rev-parse", "HEAD"], self.repo).strip()
        worktree = self.root / eid
        with sqlite3.connect(self.db_path) as c:
            c.execute(
                "INSERT INTO engineering_evolution_runs(evolution_id,objective,hypothesis,baseline_commit,worktree_path,status,budget_json) VALUES(?,?,?,?,?,'preparing',?)",
                (
                    eid,
                    objective,
                    hypothesis,
                    baseline,
                    str(worktree),
                    json.dumps(asdict(budget)),
                ),
            )
        try:
            self._run(
                ["git", "worktree", "add", "--detach", str(worktree), baseline],
                self.repo,
                120,
            )
            patch_file = worktree / ".triade-candidate.patch"
            patch_file.write_text(patch, encoding="utf-8")
            self._run(["git", "apply", "--check", str(patch_file)], worktree, 30)
            self._run(["git", "apply", str(patch_file)], worktree, 30)
            patch_file.unlink()
            changed = self._changed_files(worktree)
            self._validate_files(changed, budget)
            if self._disk_mb(worktree) > budget.max_disk_mb:
                raise ValueError("disk_budget_exceeded")
            baseline_result = self._independent_eval(
                baseline, eid + "-baseline", budget, started
            )
            candidate_result = self._eval_worktree(worktree, budget, started)
            review = self._review(baseline_result, candidate_result, changed)
            status = (
                "awaiting_approval"
                if review["decision"] == "accept_candidate"
                else "rejected"
            )
            digest = hashlib.sha256(patch.encode()).hexdigest()
            with sqlite3.connect(self.db_path) as c:
                c.execute(
                    "UPDATE engineering_evolution_runs SET status=?,patch_sha256=?,changed_files_json=?,baseline_result_json=?,candidate_result_json=?,review_json=?,updated_at=CURRENT_TIMESTAMP WHERE evolution_id=?",
                    (
                        status,
                        digest,
                        json.dumps(changed),
                        json.dumps(baseline_result),
                        json.dumps(candidate_result),
                        json.dumps(review),
                        eid,
                    ),
                )
            self._event(eid, "independent_review", review["decision"], review)
            return {
                "status": status,
                "evolution_id": eid,
                "baseline_commit": baseline,
                "changed_files": changed,
                "review": review,
                "worktree": str(worktree),
            }
        except Exception as exc:
            self._event(eid, "failed", "reject", {"error": str(exc)})
            self._status(eid, "failed")
            return {
                "status": "error",
                "evolution_id": eid,
                "error": str(exc),
                "rollback_ready": worktree.exists(),
            }

    def approve_and_commit(
        self, evolution_id: str, *, approved_by: str
    ) -> dict[str, Any]:
        if not approved_by:
            return {"status": "blocked", "reason": "named_human_approval_required"}
        row = self._get(evolution_id)
        if not row or row["status"] != "awaiting_approval":
            return {"status": "blocked", "reason": "candidate_not_awaiting_approval"}
        wt = Path(row["worktree_path"])
        self._run(["git", "add", "-A"], wt, 30)
        try:
            self._run(
                ["git", "commit", "-S", "-m", f"evolution: {row['objective'][:60]}"],
                wt,
                60,
            )
        except Exception as exc:
            return {
                "status": "blocked",
                "reason": "signed_commit_required",
                "error": str(exc),
            }
        commit = self._git(["rev-parse", "HEAD"], wt).strip()
        with sqlite3.connect(self.db_path) as c:
            c.execute(
                "UPDATE engineering_evolution_runs SET status='approved_commit',approved_by=?,commit_hash=?,updated_at=CURRENT_TIMESTAMP WHERE evolution_id=?",
                (approved_by, commit, evolution_id),
            )
        self._event(
            evolution_id,
            "human_approval",
            "approved",
            {"approved_by": approved_by, "commit": commit},
        )
        return {
            "status": "approved_commit",
            "commit": commit,
            "deployment": "not_automatic",
            "rollback_ready": True,
        }

    def deploy(self, evolution_id: str, *, approved_by: str) -> dict[str, Any]:
        row = self._get(evolution_id)
        if not row or row["status"] != "approved_commit" or not approved_by:
            return {"status": "blocked", "reason": "approved_signed_commit_required"}
        if self._git(["status", "--porcelain"], self.repo).strip():
            return {"status": "blocked", "reason": "production_worktree_not_clean"}
        before = self._git(["rev-parse", "HEAD"], self.repo).strip()
        self._run(["git", "cherry-pick", row["commit_hash"]], self.repo, 120)
        rollback = {
            "action": "git_revert",
            "commit": row["commit_hash"],
            "previous": before,
        }
        with sqlite3.connect(self.db_path) as c:
            c.execute(
                "UPDATE engineering_evolution_runs SET status='deployed_canary',rollback_json=?,updated_at=CURRENT_TIMESTAMP WHERE evolution_id=?",
                (json.dumps(rollback), evolution_id),
            )
        return {
            "status": "deployed_canary",
            "commit": row["commit_hash"],
            "rollback": rollback,
        }

    def rollback(self, evolution_id: str, *, approved_by: str) -> dict[str, Any]:
        row = self._get(evolution_id)
        if not row or not approved_by:
            return {"status": "blocked", "reason": "approval_or_run_missing"}
        rb = json.loads(row["rollback_json"] or "{}")
        if row["status"] == "deployed_canary" and rb.get("commit"):
            self._run(["git", "revert", "--no-edit", rb["commit"]], self.repo, 120)
        self._cleanup(Path(row["worktree_path"]))
        self._status(evolution_id, "rolled_back")
        return {"status": "rolled_back", "evolution_id": evolution_id}

    def watchdog(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as c:
            rows = c.execute(
                "SELECT evolution_id,worktree_path,budget_json,created_at FROM engineering_evolution_runs WHERE status IN ('preparing','evaluating')"
            ).fetchall()
        return {
            "status": "ok",
            "active": len(rows),
            "runs": [{"evolution_id": r[0], "worktree": r[1]} for r in rows],
        }

    def _independent_eval(
        self, commit: str, name: str, budget: EvolutionBudget, started: float
    ) -> dict:
        wt = self.root / name
        self._run(
            ["git", "worktree", "add", "--detach", str(wt), commit], self.repo, 120
        )
        try:
            return self._eval_worktree(wt, budget, started)
        finally:
            self._cleanup(wt)

    def _eval_worktree(self, wt: Path, budget: EvolutionBudget, started: float) -> dict:
        if (time.monotonic() - started) / 60 > budget.max_minutes:
            raise TimeoutError("time_budget_exceeded")
        results = []
        for key in ("compile", "tests"):
            cmd = ALLOWED_COMMANDS[key]
            p = subprocess.run(
                cmd,
                cwd=wt,
                capture_output=True,
                text=True,
                timeout=max(60, budget.max_minutes * 60),
                env={
                    **os.environ,
                    "TRIADE_RUNTIME_SCOPE": "test",
                    "TRIADE_DISABLE_BACKGROUND": "1",
                },
            )
            results.append(
                {
                    "key": key,
                    "returncode": p.returncode,
                    "stdout": p.stdout[-2000:],
                    "stderr": p.stderr[-1000:],
                }
            )
            if p.returncode:
                break
        return {
            "passed": all(r["returncode"] == 0 for r in results),
            "commands": results,
        }

    @staticmethod
    def _review(base: dict, candidate: dict, changed: list[str]) -> dict:
        accept = base.get("passed") and candidate.get("passed")
        return {
            "reviewer": "deterministic_independent_gate",
            "independent_tests": True,
            "baseline_passed": base.get("passed"),
            "candidate_passed": candidate.get("passed"),
            "changed_files": changed,
            "decision": "accept_candidate" if accept else "reject_candidate",
        }

    @staticmethod
    def _validate_files(files: list[str], budget: EvolutionBudget) -> None:
        if len(files) > budget.max_files:
            raise ValueError("file_budget_exceeded")
        for f in files:
            if f.startswith(PROTECTED) or any(
                x in f for x in ("secret", "private_key")
            ):
                raise ValueError(f"protected_path:{f}")

    def _changed_files(self, worktree: Path) -> list[str]:
        lines = self._git(["status", "--porcelain"], worktree).splitlines()
        return sorted(
            {line[3:].strip().split(" -> ")[-1] for line in lines if len(line) > 3}
        )

    @staticmethod
    def _disk_mb(path: Path) -> float:
        return (
            sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1024 / 1024
        )

    @staticmethod
    def _run(cmd: list[str], cwd: Path, timeout: int) -> None:
        p = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        if p.returncode:
            raise RuntimeError((p.stderr or p.stdout)[-2000:])

    @staticmethod
    def _git(args: list[str], cwd: Path) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout

    def _cleanup(self, wt: Path) -> None:
        if wt.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt)],
                cwd=self.repo,
                capture_output=True,
            )

    def _event(self, eid, event, decision, payload):
        with sqlite3.connect(self.db_path) as c:
            c.execute(
                "INSERT INTO engineering_evolution_events(evolution_id,event,decision,payload_json) VALUES(?,?,?,?)",
                (eid, event, decision, json.dumps(payload)),
            )

    def _status(self, eid, status):
        with sqlite3.connect(self.db_path) as c:
            c.execute(
                "UPDATE engineering_evolution_runs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE evolution_id=?",
                (status, eid),
            )

    def _get(self, eid):
        with sqlite3.connect(self.db_path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM engineering_evolution_runs WHERE evolution_id=?", (eid,)
            ).fetchone()
            return dict(row) if row else None
