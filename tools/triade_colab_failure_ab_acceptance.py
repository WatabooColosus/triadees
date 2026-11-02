"""Colab: comprobar fallos A/B sobre copia SQLite sin modificar producción.

Ejecutar en un proceso separado, desde el checkout Git fijado de la candidata.
NUNCA ejecuta evaluate_auto(), observe(), propose(), deploy() ni rollback().
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SHA40 = re.compile(r"^[a-f0-9]{40}$")
COUNT_TABLES = (
    "neurons",
    "autonomous_tasks",
    "autonomous_task_transitions",
    "worker_tasks",
    "worker_events",
    "failure_ab_experiments",
    "failure_ab_shadow_canaries",
    "autonomous_worker_repair_attempts",
    "neuron_education_applications",
)


def checked_head(repo: Path) -> str:
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=8,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("No hay commit Git verificable") from exc
    if not SHA40.fullmatch(commit):
        raise RuntimeError("Commit Git inválido")
    return commit


def snapshot_sqlite(source: Path, target: Path) -> dict[str, Any]:
    """Backup transaccional de solo lectura: incluye datos WAL confirmados."""
    if source.is_symlink():
        raise RuntimeError("La Bodega es un enlace simbólico")
    source = source.resolve(strict=True)
    if not source.is_file():
        raise RuntimeError("Bodega SQLite ausente")
    if target.exists() or target.is_symlink():
        raise RuntimeError("La copia de destino ya existe")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=10) as live,
            sqlite3.connect(target, timeout=10) as copy,
        ):
            live.backup(copy, pages=128, sleep=0.05)
            check = copy.execute("PRAGMA quick_check").fetchone()
            if check is None or check[0] != "ok":
                raise RuntimeError("Copia SQLite no íntegra")
            names = {
                row[0]
                for row in copy.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            counts = {
                table: int(
                    copy.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                )
                for table in COUNT_TABLES
                if table in names
            }
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "quick_check": "ok", "counts": counts}


def diagnose_evidence_sources(snapshot: Path) -> dict[str, Any]:
    """Indica por qué 3.000 tareas pueden dar cero observaciones válidas.

    Solo consulta la copia. No infiere fallos de las tareas pendientes y no
    atribuye causalidad a archivos cuyo hash todavía no se haya validado.
    """
    terminal = (
        "completed",
        "observed",
        "cancelled",
        "blocked",
        "failed",
        "dead_letter",
        "timeout",
        "lease_lost",
    )
    with sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

        def columns(table: str) -> set[str]:
            if table not in tables:
                return set()
            return {
                str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')
            }

        def count(table: str) -> int | None:
            if table not in tables:
                return None
            return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

        statuses: dict[str, int] = {}
        if {"autonomous_tasks"} <= tables and "status" in columns("autonomous_tasks"):
            statuses = {
                str(row["status"]): int(row["total"])
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS total FROM autonomous_tasks "
                    "GROUP BY status ORDER BY status LIMIT 30"
                )
            }

        legacy_required = {
            "worker_tasks": {"id", "run_ref", "status", "task_type", "result_json"},
            "worker_events": {
                "task_id",
                "event_type",
                "run_ref",
                "task_type",
                "payload_json",
            },
        }
        canonical_required = {
            "autonomous_tasks": {
                "task_id",
                "status",
                "worker_id",
                "result_ref",
                "lease_generation",
            },
            "autonomous_task_transitions": {
                "task_id",
                "to_status",
                "worker_id",
                "result_ref",
                "lease_generation",
            },
        }
        missing_legacy = {
            table: sorted(fields - columns(table))
            for table, fields in legacy_required.items()
            if fields - columns(table)
        }
        missing_canonical = {
            table: sorted(fields - columns(table))
            for table, fields in canonical_required.items()
            if fields - columns(table)
        }

        legacy_matches = None
        if not missing_legacy:
            legacy_matches = int(
                conn.execute(
                    "SELECT COUNT(*) FROM worker_events e "
                    "JOIN worker_tasks t ON t.id = e.task_id "
                    "WHERE e.event_type LIKE 'task_%'"
                ).fetchone()[0]
            )

        canonical_matches = None
        references = {
            "sampled_terminal_transitions": 0,
            "nonempty_result_refs": 0,
            "accessible_result_json": 0,
            "accessible_manifest_json": 0,
        }
        if not missing_canonical:
            placeholders = ",".join("?" for _ in terminal)
            sql = (
                "SELECT t.result_ref AS result_ref "
                "FROM autonomous_task_transitions e "
                "JOIN autonomous_tasks t ON t.task_id = e.task_id "
                "WHERE e.to_status IN (" + placeholders + ") "
                "ORDER BY e.rowid DESC LIMIT 1000"
            )
            canonical_matches = int(
                conn.execute(
                    "SELECT COUNT(*) FROM autonomous_task_transitions e "
                    "JOIN autonomous_tasks t ON t.task_id = e.task_id "
                    "WHERE e.to_status IN (" + placeholders + ")",
                    terminal,
                ).fetchone()[0]
            )
            for row in conn.execute(sql, terminal):
                references["sampled_terminal_transitions"] += 1
                reference = str(row["result_ref"] or "")
                if not reference:
                    continue
                references["nonempty_result_refs"] += 1
                if not Path(reference).is_absolute():
                    continue
                artifact = Path(reference)
                if (
                    artifact.name != "result.json"
                    or artifact.is_symlink()
                    or artifact.parent.is_symlink()
                    or not artifact.is_file()
                ):
                    continue
                references["accessible_result_json"] += 1
                manifest = artifact.parent / "manifest.json"
                if manifest.is_file() and not manifest.is_symlink():
                    references["accessible_manifest_json"] += 1

    reasons = []
    if missing_legacy:
        reasons.append("legacy_contract_missing")
    elif legacy_matches == 0:
        reasons.append("no_linked_legacy_task_events")
    if missing_canonical:
        reasons.append("canonical_contract_missing")
    elif canonical_matches == 0:
        reasons.append("no_terminal_canonical_transitions")
    elif references["nonempty_result_refs"] == 0:
        reasons.append("terminal_transitions_without_result_refs")
    elif references["accessible_result_json"] == 0:
        reasons.append("result_artifacts_not_accessible_in_this_colab")
    elif references["accessible_manifest_json"] == 0:
        reasons.append("canonical_manifests_not_accessible")
    return {
        "table_counts": {
            table: count(table)
            for table in (
                "autonomous_tasks",
                "autonomous_task_transitions",
                "worker_tasks",
                "worker_events",
            )
        },
        "autonomous_task_status_counts": statuses,
        "legacy_contract_missing": missing_legacy,
        "canonical_contract_missing": missing_canonical,
        "linked_legacy_task_events": legacy_matches,
        "canonical_terminal_transitions": canonical_matches,
        "canonical_artifact_sample": references,
        "diagnostic_codes": reasons,
        "canonical_artifacts_fully_verified": False,
        "production_modified": False,
    }


def inspect_copy(snapshot: Path, checkout: Path) -> dict[str, Any]:
    """Leer métodos de elegibilidad; no crear experimentos ni canaries."""
    import triade
    from triade.evolution.autonomous_worker_repair import AutonomousWorkerRepair
    from triade.self_improvement.worker_failure_ab import WorkerFailureABRunner
    from triade.self_improvement.worker_failure_canary import (
        WorkerFailureShadowCanary,
    )

    if Path(triade.__file__).resolve().parents[1] != checkout.resolve():
        raise RuntimeError("Importación de Tríade desde un checkout diferente")
    runner = WorkerFailureABRunner(snapshot)
    observations = runner._load_observations()
    cases = runner.replay_cases()
    refs = sorted(str(row["source_ref"]) for row in observations)
    incident = AutonomousWorkerRepair(snapshot, repo=checkout).pending_incident()
    return {
        "verified_observations": len(observations),
        "evidence_source_diagnostics": diagnose_evidence_sources(snapshot),
        "source_ref_fingerprint": hashlib.sha256(
            json.dumps(refs, separators=(",", ":")).encode()
        ).hexdigest(),
        "cohorts": {
            split: sum(case.split == split for case in cases)
            for split in ("train", "holdout", "negative")
        },
        "real_regression_measurement_pending": runner.pending_auto_measurement(),
        "shadow_canary_ready": WorkerFailureShadowCanary(snapshot).ready(),
        "functional_repair_incident_pending": bool(incident),
        "incident_ref_hash": (
            hashlib.sha256(incident.encode()).hexdigest() if incident else None
        ),
    }


def acceptance(
    database: Path, checkout: Path, expected_commit: str, report_path: Path
) -> dict[str, Any]:
    checkout = checkout.resolve(strict=True)
    if not SHA40.fullmatch(expected_commit):
        raise ValueError("SHA esperado inválido")
    commit = checked_head(checkout)
    if commit != expected_commit:
        raise RuntimeError("El checkout no coincide con el commit autorizado")
    target = report_path.resolve()
    if (
        report_path.is_symlink()
        or target.is_relative_to(database.resolve().parent)
        or target.is_relative_to(Path("/content/drive"))
    ):
        raise RuntimeError("El informe debe quedar fuera de Drive y de la Bodega")
    with tempfile.TemporaryDirectory(prefix="triade-failure-ab-") as folder:
        snapshot = Path(folder) / "snapshot.sqlite3"
        receipt = snapshot_sqlite(database, snapshot)
        findings = inspect_copy(snapshot, checkout)
    result = {
        "schema": "triade.colab.failure_ab.acceptance.v1",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "commit": commit,
        "snapshot": receipt,
        "findings": findings,
        "decision": "readonly_evidence_collected",
        "operational_causality_proven": False,
        "colab_rollback_certified": False,
        "stable_memory_written": False,
        "promotion_authorized": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(".partial")
    if temporary.exists() or temporary.is_symlink():
        raise RuntimeError("Temporal de informe existente")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            os.chmod(temporary, 0o600)
            json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temporary, report_path)
    finally:
        temporary.unlink(missing_ok=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = acceptance(args.db, args.repo, args.expected_commit, args.report)
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports all failed probes
        print(
            json.dumps(
                {
                    "decision": "blocked",
                    "error": type(exc).__name__,
                    "detail": str(exc)[:300],
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
