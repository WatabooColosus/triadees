"""Auditoría read-only de autonomía con evidencia runtime y SQLite."""

from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def _http(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return {"status": response.status, "body": json.loads(response.read())}
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "error": str(exc)}


def _table(db: sqlite3.Connection, name: str) -> bool:
    return bool(
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def _count(db: sqlite3.Connection, table: str, where: str = "") -> int:
    if not _table(db, table):
        return 0
    return int(db.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0])


def audit(db_path: Path, base_url: str) -> dict:
    gates: list[dict] = []

    def add(name: str, status: str, **evidence: object) -> None:
        gates.append({"gate": name, "status": status, "evidence": evidence})

    # Missing databases must not be created by an audit.
    db = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
    add(
        "database_integrity",
        "PASS" if integrity == "ok" else "BLOCKED",
        result=integrity,
    )
    heartbeat = _http(base_url.rstrip("/") + "/api/runtime/heartbeat")
    body = heartbeat.get("body") or {}
    metabolism = _http(base_url.rstrip("/") + "/api/runtime/metabolism/status")
    metabolism_body = metabolism.get("body") or {}
    metabolism_state = metabolism_body.get("metabolism") or {}
    permission_profile = _http(
        base_url.rstrip("/") + "/api/system/permissions?requested=full_local_guarded"
    )
    live = heartbeat.get("status") == 200 and bool(
        body.get("workers_active", body.get("runtime_enabled", False))
    )
    add(
        "runtime_live",
        "PASS" if live else "BLOCKED",
        http_status=heartbeat.get("status"),
        last_cycle_at=body.get("last_cycle_at"),
        workers_active=body.get("workers_active"),
        error=heartbeat.get("error"),
    )
    add(
        "workers_live",
        "PASS" if body.get("workers_active") else "PENDING",
        workers_active=body.get("workers_active"),
    )
    add(
        "scheduler_live",
        "PASS" if body.get("scheduler_active") is True else "PENDING",
        scheduler_active=body.get("scheduler_active"),
    )
    metabolism_live = (
        metabolism.get("status") == 200
        and metabolism_state.get("running") is True
        and int(metabolism_state.get("cycle_count") or 0) > 0
        and not metabolism_state.get("last_tick_error")
    )
    add(
        "metabolism_live",
        "PASS" if metabolism_live else "PENDING",
        http_status=metabolism.get("status"),
        running=metabolism_state.get("running"),
        cycle_count=metabolism_state.get("cycle_count"),
        last_tick_at=metabolism_state.get("last_tick_at"),
        last_tick_error=metabolism_state.get("last_tick_error"),
    )
    statuses = {
        r["status"]: int(r["n"])
        for r in db.execute(
            "SELECT status,COUNT(*) n FROM learning_queue GROUP BY status"
        )
    }
    verified = sum(
        statuses.get(s, 0) for s in ("evidence_verified", "consolidated", "stable")
    )
    add(
        "independent_learning_evidence",
        "PENDING",
        verified_or_better=verified,
        by_status=statuses,
        reason="Requires independent source provenance linked to runtime verification",
    )
    uses = int(
        db.execute(
            "SELECT COALESCE(SUM(run_use_count),0) FROM learning_queue"
        ).fetchone()[0]
    )
    add(
        "causal_production_use",
        "PENDING",
        run_use_count=uses,
        reason="Usage counters do not establish causal improvement; a controlled comparison is required",
    )
    routes = _count(
        db,
        "neuron_learning_assignments",
        "WHERE status IN ('experimental','beneficial')",
    )
    add(
        "neural_routes",
        "PENDING",
        active_routes=routes,
        reason="Requires candidate-route-run evidence chain",
    )
    applications = _count(db, "neuron_education_applications")
    add(
        "education_application",
        "PENDING",
        applications=applications,
        reason="Requires lesson baseline, subsequent use and measured resolution",
    )
    measured = _count(
        db,
        "learning_evidence",
        "WHERE decision IN ('improved','neutral','degraded','regressed')",
    )
    add(
        "improvement_measurement",
        "PENDING",
        measured_evidence=measured,
        reason="Requires audited before/after evidence; historical decisions alone are insufficient",
    )
    canary_runs = _count(db, "improvement_canaries")
    add(
        "improvement_canary",
        "PENDING",
        registered=canary_runs,
        reason="Requires linked execution, measured outcome and verification receipt",
    )
    rollbacks = _count(db, "rollback_receipts") + _count(db, "rollback_events")
    add(
        "rollback_verified",
        "PENDING",
        receipts_or_events=rollbacks,
        reason="Requires verified state change and subsequent behavior",
    )
    predictions = _count(
        db, "capability_predictions", "WHERE outcome_success IS NOT NULL"
    )
    add(
        "metacognition_runtime",
        "PENDING",
        predictions_with_outcome=predictions,
        reason="Requires production run references and calibration metrics",
    )
    add(
        "memory_persistence",
        "PENDING",
        verified_knowledge=verified,
        reason="Requires observed write-read-restart-read continuity",
    )
    add(
        "restart_persistence",
        "PENDING",
        reason="requiere ensayo shutdown/restart observable",
    )
    federation = _count(db, "federated_nodes", "WHERE status IN ('active','healthy')")
    add(
        "federation",
        "PENDING",
        active_nodes=federation,
        reason="Registry entries do not prove two independent nodes completed authenticated dispatch",
    )
    add(
        "resource_governor",
        "PENDING",
        mode=body.get("mode"),
        reason="Requires observed low-resource transitions and essential-service continuity",
    )
    profile = permission_profile.get("body") or {}
    permissions = profile.get("permissions") or {}
    add(
        "permission_governor",
        "PASS"
        if permission_profile.get("status") == 200 and permissions
        else "PENDING",
        http_status=permission_profile.get("status"),
        permissions=permissions,
        can_modify_identity_core=permissions.get("can_modify_identity_core"),
    )
    add(
        "error_recovery",
        "PENDING",
        dead_letter=_count(db, "autonomous_tasks", "WHERE status='dead_letter'"),
        reason="Requires observed failure, recovery and absence of duplicate effects",
    )
    long_dir = Path("artifacts/long-run")
    longitudinal = None
    if long_dir.exists():
        for report in sorted(
            long_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                lines = [
                    json.loads(line)
                    for line in report.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                footer = lines[-1] if lines else {}
                header = lines[0] if lines else {}
                samples = [item for item in lines[1:-1] if item.get("at")]
                # COMPLETED only records that the collector stopped. It does not
                # certify health, progress, duration or source revision.
                if (
                    footer.get("verdict") == "CERTIFIED"
                    and footer.get("duration_seconds", 0) >= 300
                    and footer.get("healthy_progress") is True
                    and header.get("source_hash")
                    and len(samples) >= 2
                ):
                    longitudinal = {
                        "file": str(report),
                        "samples": len(samples),
                        "sha": header.get("sha_at_start"),
                    }
                    break
            except (OSError, ValueError, TypeError):
                continue
    add(
        "longitudinal_runtime",
        "PASS" if longitudinal else "PENDING",
        **(longitudinal or {"reason": "requiere checkpoint temporal >=5 minutos"}),
    )
    db.close()
    summary = {
        s: sum(g["status"] == s for g in gates)
        for s in ("PASS", "PENDING", "BLOCKED", "NOT_APPLICABLE")
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "db": str(db_path),
        "base_url": base_url,
        "gates": gates,
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita gates de autonomía sin mutar el runtime"
    )
    parser.add_argument("--db", default="triade/memory/triade.db")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    args = parser.parse_args()
    report = audit(Path(args.db), args.base_url)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["summary"]["BLOCKED"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
