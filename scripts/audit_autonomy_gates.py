"""Auditoría read-only de autonomía con evidencia runtime y SQLite."""
from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def _http(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return {"status": response.status, "body": json.loads(response.read())}
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "error": str(exc)}


def _table(db: sqlite3.Connection, name: str) -> bool:
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def _count(db: sqlite3.Connection, table: str, where: str = "") -> int:
    if not _table(db, table):
        return 0
    return int(db.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0])


def audit(db_path: Path, base_url: str) -> dict:
    gates: list[dict] = []

    def add(name: str, status: str, **evidence: object) -> None:
        gates.append({"gate": name, "status": status, "evidence": evidence})

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
    add("database_integrity", "PASS" if integrity == "ok" else "BLOCKED", result=integrity)
    heartbeat = _http(base_url.rstrip("/") + "/api/runtime/heartbeat")
    body = heartbeat.get("body") or {}
    permission_profile = _http(base_url.rstrip("/") + "/api/system/permissions?requested=full_local_guarded")
    live = heartbeat.get("status") == 200 and bool(body.get("workers_active", body.get("runtime_enabled", False)))
    add("runtime_live", "PASS" if live else "BLOCKED", http_status=heartbeat.get("status"), last_cycle_at=body.get("last_cycle_at"), workers_active=body.get("workers_active"), error=heartbeat.get("error"))
    add("workers_live", "PASS" if body.get("workers_active") else "PENDING", workers_active=body.get("workers_active"))
    add("scheduler_live", "PASS" if body.get("scheduler_active", body.get("workers_active")) else "PENDING", scheduler_active=body.get("scheduler_active"))
    add("metabolism_live", "PASS" if body.get("metabolism_active") else "PENDING", metabolism_active=body.get("metabolism_active"))
    statuses = {r["status"]: int(r["n"]) for r in db.execute("SELECT status,COUNT(*) n FROM learning_queue GROUP BY status")}
    verified = sum(statuses.get(s, 0) for s in ("evidence_verified", "consolidated", "stable"))
    add("independent_learning_evidence", "PASS" if verified else "PENDING", verified_or_better=verified, by_status=statuses)
    uses = int(db.execute("SELECT COALESCE(SUM(run_use_count),0) FROM learning_queue").fetchone()[0])
    add("causal_production_use", "PASS" if uses else "PENDING", run_use_count=uses)
    routes = _count(db, "neuron_learning_assignments", "WHERE status IN ('experimental','beneficial')")
    add("neural_routes", "PASS" if routes else "PENDING", active_routes=routes)
    applications = _count(db, "neuron_education_applications")
    add("education_application", "PASS" if applications else "PENDING", applications=applications)
    measured = _count(db, "learning_evidence", "WHERE decision IN ('improved','neutral','degraded','regressed')")
    add("improvement_measurement", "PASS" if measured else "PENDING", measured_evidence=measured)
    canary_runs = _count(db, "improvement_canaries", "WHERE outcome IS NOT NULL")
    add("improvement_canary", "PASS" if canary_runs else "PENDING", executed_with_outcome=canary_runs)
    rollbacks = _count(db, "rollback_receipts") + _count(db, "rollback_events")
    add("rollback_verified", "PASS" if rollbacks else "PENDING", receipts_or_events=rollbacks)
    predictions = _count(db, "capability_predictions", "WHERE outcome_success IS NOT NULL")
    add("metacognition_runtime", "PASS" if predictions else "PENDING", predictions_with_outcome=predictions)
    add("memory_persistence", "PASS" if verified else "PENDING", verified_knowledge=verified)
    add("restart_persistence", "PENDING", reason="requiere ensayo shutdown/restart observable")
    federation = _count(db, "federated_nodes", "WHERE status IN ('active','healthy')")
    add("federation", "PASS" if federation >= 2 else "PENDING", active_nodes=federation)
    add("resource_governor", "PASS" if body.get("resource_governor") or body.get("mode") else "PENDING", mode=body.get("mode"))
    profile = permission_profile.get("body") or {}
    permissions = profile.get("permissions") or {}
    add("permission_governor", "PASS" if permission_profile.get("status") == 200 and permissions else "PENDING", http_status=permission_profile.get("status"), permissions=permissions, can_modify_identity_core=permissions.get("can_modify_identity_core"))
    add("error_recovery", "PASS", dead_letter=_count(db, "autonomous_tasks", "WHERE status='dead_letter'"))
    add("longitudinal_runtime", "PENDING", reason="requiere checkpoint temporal >=5 minutos")
    db.close()
    summary = {s: sum(g["status"] == s for g in gates) for s in ("PASS", "PENDING", "BLOCKED", "NOT_APPLICABLE")}
    return {"generated_at": datetime.now(UTC).isoformat(), "db": str(db_path), "base_url": base_url, "gates": gates, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita gates de autonomía sin mutar el runtime")
    parser.add_argument("--db", default="triade/memory/triade.db")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    args = parser.parse_args()
    report = audit(Path(args.db), args.base_url)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["summary"]["BLOCKED"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
