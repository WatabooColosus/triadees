"""Ciclo autónomo y acotado de reparación de incidentes verificables.

Solo consume eventos corroborados por el lector v1/v2, genera variantes
de reglas de código predeterminadas, y entrega las variantes al certificador
Git aislado. Nunca ejecuta código procedente del evento, de un prompt o de
fuentes externas. Nunca aprueba, fusiona ni despliega un parche.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from triade.db import sqlite3

from .engineering_worker import EngineeringEvolutionWorker, EvolutionBudget

REPAIR_PROTOCOL_VERSION = "worker-repair-v1"
REPAIR_RULE = "requested_cancellation_marked_failed"
REPAIR_TEST = "tests/test_worker_failure_repair_oracle.py"
REPAIR_TARGET = "triade/workers/worker_loop.py"
MAX_TRIALS_PER_SOURCE = 2
MAX_INCIDENTS_PER_REVISION = 2

_OLD_GUARD = '    if status == "cancelled":'
_VARIANTS = (
    ("B1-guard-failed", '    if status in {"cancelled", "failed"}:'),
    ("B2-guard-blocked", '    if status in {"cancelled", "failed", "blocked"}:'),
)


def _is_repairable_incident(item: Mapping[str, Any]) -> bool:
    """Una cancelación correcta nunca provoca una reparación."""
    payload = item.get("payload")
    return (
        item.get("status") == "failed"
        and isinstance(payload, dict)
        and any(
            str(payload.get(key) or "").strip().casefold() == "cancellation_requested"
            for key in ("reason", "error", "message", "skipped_reason")
        )
        and str(item.get("source_ref") or "").startswith(
            ("worker-event:", "autonomous-transition:")
        )
    )


class AutonomousWorkerRepair:
    def __init__(
        self,
        db_path: str | Path,
        repo: str | Path | None = None,
        *,
        engine_factory: Callable[..., EngineeringEvolutionWorker] = (
            EngineeringEvolutionWorker
        ),
        artifact_root: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.repo = (
            Path(repo).resolve()
            if repo is not None
            else Path(__file__).resolve().parents[2]
        )
        self.engine_factory = engine_factory
        self.artifact_root = artifact_root

    def _observed(self) -> list[dict[str, Any]]:
        from triade.self_improvement.worker_failure_ab import WorkerFailureABRunner

        return [
            row
            for row in WorkerFailureABRunner(
                self.db_path, artifact_root=self.artifact_root
            )._load_observations()
            if _is_repairable_incident(row)
        ]

    def _attempted(self, evidence_ref: str, revision: str) -> bool:
        with sqlite3.connect(
            self.db_path.resolve().as_uri() + "?mode=ro", uri=True
        ) as conn:
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "autonomous_worker_repair_attempts" not in tables:
                return False
            existing = conn.execute(
                "SELECT 1 FROM autonomous_worker_repair_attempts "
                "WHERE evidence_ref=? AND protocol=? LIMIT 1",
                (evidence_ref, REPAIR_PROTOCOL_VERSION),
            ).fetchone()
            total = conn.execute(
                "SELECT COUNT(*) FROM autonomous_worker_repair_attempts "
                "WHERE protocol=? AND baseline_commit=?",
                (REPAIR_PROTOCOL_VERSION, revision),
            ).fetchone()[0]
            return existing is not None or total >= MAX_INCIDENTS_PER_REVISION

    def pending_incident(self) -> str | None:
        """Consulta read-only para el planificador, no crea ni cambia tareas."""
        # No despertar workers caros si desapareció la receta o el oráculo.
        source_path = self.repo / REPAIR_TARGET
        test_path = self.repo / REPAIR_TEST
        if not source_path.is_file() or not test_path.is_file():
            return None
        if source_path.is_symlink() or test_path.is_symlink():
            return None
        if source_path.read_text(encoding="utf-8").count(_OLD_GUARD) != 1:
            return None
        # El presupuesto pertenece al commit actual, no a toda la historia.
        # Sin identidad Git verificable no se programan reparaciones.
        try:
            revision = subprocess.check_output(
                ["git", "-C", str(self.repo), "rev-parse", "--verify", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=3,
            ).strip()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        if len(revision) != 40 or not all(
            char in "0123456789abcdef" for char in revision
        ):
            return None
        for item in reversed(self._observed()):
            evidence_ref = str(item["source_ref"])
            if not self._attempted(evidence_ref, revision):
                return evidence_ref
        return None

    @staticmethod
    def _patch(source: str, replacement: str) -> str:
        if source.count(_OLD_GUARD) != 1:
            raise ValueError("repair_source_guard_missing_or_ambiguous")
        new_source = source.replace(_OLD_GUARD, replacement)
        return "".join(
            difflib.unified_diff(
                source.splitlines(keepends=True),
                new_source.splitlines(keepends=True),
                fromfile="a/" + REPAIR_TARGET,
                tofile="b/" + REPAIR_TARGET,
            )
        )

    def _build_variants(self) -> list[tuple[str, str]]:
        source_path = self.repo / REPAIR_TARGET
        if source_path.is_symlink() or not source_path.is_file():
            raise ValueError("trusted_repair_source_unavailable")
        source = source_path.read_text(encoding="utf-8")
        return [
            (name, self._patch(source, replacement)) for name, replacement in _VARIANTS
        ]

    def _reserve(self, evidence_ref: str, revision: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS autonomous_worker_repair_attempts("
                "attempt_id TEXT PRIMARY KEY, evidence_ref TEXT NOT NULL,"
                "protocol TEXT NOT NULL, rule_id TEXT NOT NULL,"
                "baseline_commit TEXT NOT NULL, status TEXT NOT NULL,"
                "results_json TEXT NOT NULL DEFAULT '{}',"
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
                "UNIQUE(evidence_ref,protocol))"
            )
            count = conn.execute(
                "SELECT COUNT(*) FROM autonomous_worker_repair_attempts "
                "WHERE baseline_commit=? AND protocol=?",
                (revision, REPAIR_PROTOCOL_VERSION),
            ).fetchone()[0]
            if count >= MAX_INCIDENTS_PER_REVISION:
                return False
            attempt_id = hashlib.sha256(
                f"{REPAIR_PROTOCOL_VERSION}:{revision}:{evidence_ref}".encode()
            ).hexdigest()[:32]
            cursor = conn.execute(
                "INSERT OR IGNORE INTO autonomous_worker_repair_attempts "
                "(attempt_id,evidence_ref,protocol,rule_id,baseline_commit,status)"
                " VALUES(?,?,?,?,?,?)",
                (
                    attempt_id,
                    evidence_ref,
                    REPAIR_PROTOCOL_VERSION,
                    REPAIR_RULE,
                    revision,
                    "investigating",
                ),
            )
            return cursor.rowcount == 1

    def _record(self, evidence_ref: str, result: dict[str, Any]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE autonomous_worker_repair_attempts "
                "SET status=?,results_json=? WHERE evidence_ref=? AND protocol=?",
                (
                    str(result["status"]),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    evidence_ref,
                    REPAIR_PROTOCOL_VERSION,
                ),
            )

    def evaluate(self, evidence_ref: str) -> dict[str, Any]:
        """Una sola investigación por evidencia, con dos candidatos como máximo.

        No se infiere una corrección de un mensaje de error: se exige la prueba
        preexistente y el contraste red→green del EngineeringEvolutionWorker.
        """
        result: dict[str, Any] = {
            "status": "no_evidence",
            "evidence_ref": evidence_ref,
            "protocol": REPAIR_PROTOCOL_VERSION,
            "rule_id": REPAIR_RULE,
            "production_changed": False,
            "stable_memory_written": False,
            "approval_requested_from_user": False,
        }
        if not any(item["source_ref"] == evidence_ref for item in self._observed()):
            return {**result, "reason": "unverified_or_inapplicable_incident"}
        engine = self.engine_factory(repo=self.repo, db_path=self.db_path)
        try:
            engine._require_trusted_regression_test(REPAIR_TEST)
            revisions = engine._git(["rev-parse", "HEAD"], self.repo).strip()
            variants = self._build_variants()
        except (OSError, RuntimeError, ValueError) as exc:
            return {
                **result,
                "reason": "no_independent_functional_oracle_or_recipe",
                "detail": type(exc).__name__,
            }
        if not variants or len(variants) > MAX_TRIALS_PER_SOURCE:
            return {**result, "reason": "invalid_repair_variant_budget"}
        if not self._reserve(evidence_ref, revisions):
            return {**result, "reason": "already_evaluated_or_budget_exhausted"}
        receipts: list[dict[str, Any]] = []
        for name, patch in variants:
            if not patch or len(patch.encode()) > 4096:
                receipts.append(
                    {
                        "version": name,
                        "status": "blocked",
                        "reason": "patch_budget_exceeded",
                    }
                )
                continue
            try:
                trial = engine.propose(
                    objective="Reparar incidencia verificada de cancelación",
                    hypothesis=(
                        "La tarea se registró como failed con "
                        "cancellation_requested; verificar regla sin "
                        "convertir cancelaciones legítimas en errores"
                    ),
                    patch=patch,
                    regression_test=REPAIR_TEST,
                    budget=EvolutionBudget(
                        max_files=1,
                        max_commands=4,
                        max_minutes=3,
                        max_patch_bytes=4096,
                        max_disk_mb=384,
                        max_gpu_minutes=0.0,
                    ),
                )
            except (OSError, RuntimeError, ValueError) as exc:
                trial = {"status": "error", "reason": type(exc).__name__}
            receipts.append(
                {
                    "version": name,
                    "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                    "status": str(trial.get("status") or "error"),
                    "evolution_id": trial.get("evolution_id"),
                    "review": trial.get("review"),
                    "reason": trial.get("reason") or trial.get("error"),
                }
            )
        candidates = [
            item
            for item in receipts
            if item["status"] == "awaiting_approval"
            and isinstance(item["review"], dict)
            and item["review"].get("measured_functional_repair") is True
            and item["review"].get("rollback_verified") is True
        ]
        result.update(
            {
                "status": (
                    "candidate_certified_in_sandbox"
                    if candidates
                    else "no_certified_repair"
                ),
                "variants": receipts,
                "candidate_evolution_id": (
                    candidates[0]["evolution_id"] if candidates else None
                ),
                "certification_scope": "isolated_git_worktrees_only",
                "production_causality_proven": False,
                "production_changed": False,
                "stable_memory_written": False,
            }
        )
        self._record(evidence_ref, result)
        return result
