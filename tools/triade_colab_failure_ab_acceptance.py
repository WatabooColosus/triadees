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
        print(json.dumps({"decision": "blocked", "error": type(exc).__name__,
                          "detail": str(exc)[:300]}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
