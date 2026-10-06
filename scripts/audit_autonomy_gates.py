"""Auditoría reproducible de los gates que faltan para autonomía.

No cambia la base ni crea actividad. Cada gate se clasifica como ``pass``,
``pending`` o ``blocked`` y conserva la evidencia observada.
"""
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
    except Exception as exc:  # noqa: BLE001 - el informe debe continuar
        return {"status": None, "error": str(exc)}


def audit(db_path: Path, base_url: str) -> dict:
    gates: list[dict] = []
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0])
    gates.append({"gate": "database_integrity", "status": "pass" if integrity == "ok" else "blocked", "evidence": integrity})

    counts = {r["status"]: int(r["n"]) for r in db.execute("SELECT status,COUNT(*) n FROM learning_queue GROUP BY status")}
    verified = counts.get("evidence_verified", 0) + counts.get("consolidated", 0) + counts.get("stable", 0)
    gates.append({"gate": "independent_learning_evidence", "status": "pass" if verified else "pending", "evidence": {"verified_or_better": verified, "by_status": counts}})

    uses = int(db.execute("SELECT COALESCE(SUM(run_use_count),0) FROM learning_queue").fetchone()[0])
    gates.append({"gate": "causal_production_use", "status": "pass" if uses else "pending", "evidence": {"run_use_count": uses}})

    has_canaries = bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='improvement_canaries'").fetchone())
    gates.append({"gate": "improvement_canary", "status": "pass" if has_canaries else "pending", "evidence": {"table_present": has_canaries}})

    routes = int(db.execute("SELECT COUNT(*) FROM neuron_learning_assignments WHERE status IN ('experimental','beneficial')").fetchone()[0]) if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='neuron_learning_assignments'").fetchone() else 0
    gates.append({"gate": "neural_routes", "status": "pass" if routes else "pending", "evidence": {"active_routes": routes}})

    federation = int(db.execute("SELECT COUNT(*) FROM federated_nodes WHERE status IN ('active','healthy')").fetchone()[0]) if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='federated_nodes'").fetchone() else 0
    gates.append({"gate": "federation", "status": "pass" if federation else "pending", "evidence": {"active_nodes": federation}})
    db.close()

    heartbeat = _http(base_url.rstrip("/") + "/api/runtime/heartbeat")
    body = heartbeat.get("body") or {}
    live = heartbeat.get("status") == 200 and bool(body.get("workers_active", body.get("runtime_enabled", False)))
    gates.append({"gate": "runtime_live", "status": "pass" if live else "blocked", "evidence": {"http_status": heartbeat.get("status"), "workers_active": body.get("workers_active"), "last_cycle_at": body.get("last_cycle_at"), "error": heartbeat.get("error")}})

    return {"generated_at": datetime.now(UTC).isoformat(), "db": str(db_path), "base_url": base_url, "gates": gates, "summary": {"pass": sum(g["status"] == "pass" for g in gates), "pending": sum(g["status"] == "pending" for g in gates), "blocked": sum(g["status"] == "blocked" for g in gates)}}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita gates de autonomía sin mutar el runtime")
    parser.add_argument("--db", default="triade/memory/triade.db")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = audit(Path(args.db), args.base_url)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["summary"]["blocked"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
