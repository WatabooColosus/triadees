#!/usr/bin/env python3
"""Auditor y reparador limitado R6 para todas las neuronas existentes.

No crea neuronas, contenidos educativos, eventos, evaluaciones ni logros.
No modifica identidad ni memoria estable. Solo crea misiones de OBSERVACION
faltantes a partir de objetivos reales de neuronas activas, bajo autorización.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

SAFE_STATUSES = {"experimental", "stable"}
SAFE_ACTIONS = json.dumps(["observe", "diagnose"], separators=(",", ":"))
SAFE_SOURCES = json.dumps(["worker", "run"], separators=(",", ":"))
CHECK_TABLES = (
    "neurons",
    "neuron_missions",
    "neuron_education_sessions",
    "neuron_education_applications",
    "neuron_activity",
    "verification_reports",
    "neuron_work_cycles",
    "neuron_evidence",
    "neuron_scores",
    "autonomous_tasks",
    "worker_events",
    "worker_runs",
    "metabolic_cycle",
    "learning_queue",
    "learning_retrieval_decisions",
    "neuron_learning_assignments",
    "auth_users",
    "auth_email_identities",
    "runtime_health_snapshots",
    "metabolic_receipts",
    "governed_research_runs",
    "neuron_contributions",
)


def connect(db: Path, readonly: bool = True) -> sqlite3.Connection:
    db = db.resolve()
    con = sqlite3.connect(
        db.as_uri() + ("?mode=ro" if readonly else "?mode=rw"), uri=True, timeout=15
    )
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    if readonly:
        con.execute("PRAGMA query_only=ON")
    else:
        con.execute("PRAGMA foreign_keys=ON")
    return con


def tables_of(con):
    return {
        x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def count(con, table):
    return int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def scalar(con, query, params=()):
    return con.execute(query, params).fetchone()[0]


def last_id(con, table, column):
    return scalar(con, f'SELECT MAX("{column}") FROM "{table}"')


def assess(con):
    tab = tables_of(con)
    integrity = scalar(con, "PRAGMA quick_check")
    neurons = []
    counts = {t: count(con, t) if t in tab else None for t in CHECK_TABLES}
    if not {"neurons", "neuron_missions"}.issubset(tab):
        raise RuntimeError(
            "Faltan tablas neurons / neuron_missions: intervención prohibida"
        )
    existing = {}
    for m in con.execute(
        "SELECT neuron_id,status,COUNT(*) n FROM neuron_missions GROUP BY neuron_id,status"
    ):
        nid = str(m["neuron_id"])
        existing.setdefault(nid, []).append({"status": m["status"], "count": m["n"]})
    for n in con.execute(
        "SELECT id,name,status,domain,mission FROM neurons ORDER BY id"
    ):
        nid = str(n["id"])
        mission = str(n["mission"] or "").strip()
        status = str(n["status"] or "")
        linked = existing.get(nid, [])
        if linked:
            action, reason = "keep", "mission_exists"
        elif status not in SAFE_STATUSES:
            action, reason = "skip", "neuron_not_active"
        elif not mission or not str(n["name"] or "").strip():
            action, reason = "review", "no_explicit_mission_or_name"
        else:
            action, reason = (
                "create_safe_experimental_mission",
                "existing_objective_without_mission",
            )
        neurons.append(
            {
                "id": n["id"],
                "name": n["name"],
                "status": status,
                "domain": n["domain"],
                "existing_missions": linked,
                "action": action,
                "reason": reason,
                "has_explicit_mission": bool(mission),
            }
        )

    def groups(table, field):
        if table not in tab:
            return {}
        cols = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        if field not in cols:
            return {}
        return {
            str(a): int(b)
            for a, b in con.execute(
                f'SELECT "{field}",COUNT(*) FROM "{table}" GROUP BY "{field}"'
            )
        }

    joined = None
    if {"neuron_activity", "verification_reports"}.issubset(tab):
        joined = scalar(
            con,
            "SELECT COUNT(DISTINCT na.run_id) FROM neuron_activity na JOIN verification_reports vr ON vr.run_id=na.run_id WHERE na.activated=1",
        )
    training_neurons = []
    if "neuron_education_sessions" in tab:
        for n in con.execute(
            "SELECT neuron_id,state,COUNT(*) n FROM neuron_education_sessions GROUP BY neuron_id,state ORDER BY neuron_id"
        ):
            training_neurons.append(dict(n))
    movements = {}
    for table, field in [
        ("worker_events", "id"),
        ("metabolic_cycle", "cycle_id"),
        ("autonomous_tasks", "id"),
    ]:
        if table in tab and field in {
            r[1] for r in con.execute(f'PRAGMA table_info("{table}")')
        }:
            movements[table] = last_id(con, table, field)
    result = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "quick_check": integrity,
        "counts": counts,
        "neurons": neurons,
        "neuron_actions": dict(Counter(n["action"] for n in neurons)),
        "task_status": groups("autonomous_tasks", "status"),
        "task_type": groups("autonomous_tasks", "task_type"),
        "learning_states": groups("learning_queue", "status"),
        "education_states": groups("neuron_education_sessions", "state"),
        "mission_states": groups("neuron_missions", "status"),
        "education_by_neuron": training_neurons,
        "verifiable_neural_runs": joined,
        "latest_identifiers": movements,
        "worker_events_recent_types": [],
        "warnings": [],
    }
    if "worker_events" in tab:
        cols = {r[1] for r in con.execute("PRAGMA table_info(worker_events)")}
        if {"event_type", "created_at"}.issubset(cols):
            result["worker_events_recent_types"] = [
                dict(x)
                for x in con.execute(
                    "SELECT event_type,COUNT(*) AS total FROM worker_events WHERE datetime(created_at)>=datetime('now','-30 minutes') GROUP BY event_type ORDER BY total DESC LIMIT 15"
                )
            ]
    if result["counts"].get("neuron_education_applications") == 0:
        result["warnings"].append(
            "Aplicaciones educativas=0: requiere usos medidos, no rellenar a mano."
        )
    if joined == 0:
        result["warnings"].append(
            "No hay activaciones neuronales vinculadas a verificaciones: reparación de misiones es necesaria pero no suficiente."
        )
    return result


def safe_backup(db: Path, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise RuntimeError("El respaldo de destino ya existe, no sobrescribir")
    with connect(db, True) as src:
        dest = sqlite3.connect(str(out))
        try:
            src.backup(dest, pages=200)
            if scalar(dest, "PRAGMA integrity_check") != "ok":
                raise RuntimeError("El respaldo SQLite no superó integrity_check")
        finally:
            dest.close()
    os.chmod(out, 0o600)


def repair(db: Path, audit: dict, backup_path: Path):
    if audit["quick_check"] != "ok":
        raise RuntimeError("SQLite no íntegra, reparación cancelada")
    if not any(
        x["action"] == "create_safe_experimental_mission" for x in audit["neurons"]
    ):
        return {"status": "no_changes", "created": [], "backup": None}
    safe_backup(db, backup_path)
    created = []
    with connect(db, False) as con:
        con.execute("BEGIN IMMEDIATE")
        for n in con.execute(
            "SELECT id,name,status,domain,mission FROM neurons ORDER BY id"
        ).fetchall():
            if n["status"] not in SAFE_STATUSES:
                continue
            if not str(n["name"] or "").strip() or not str(n["mission"] or "").strip():
                continue
            if (
                scalar(
                    con,
                    "SELECT COUNT(*) FROM neuron_missions WHERE neuron_id=?",
                    (n["id"],),
                )
                > 0
            ):
                continue
            now = datetime.now(timezone.utc).isoformat()
            con.execute(
                """INSERT INTO neuron_missions
                (neuron_id,title,mission,domain,allowed_sources_json,
                allowed_actions_json,schedule_hint,status,created_at,updated_at,metrics_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    n["id"],
                    str(n["name"]).strip(),
                    str(n["mission"]).strip(),
                    str(n["domain"] or "general"),
                    SAFE_SOURCES,
                    SAFE_ACTIONS,
                    "every_cycle",
                    "experimental",
                    now,
                    now,
                    json.dumps(
                        {
                            "source": "existing_neuron_objective",
                            "bridge_version": "r6",
                            "auto_promotion": False,
                        }
                    ),
                ),
            )
            created.append(int(n["id"]))
        if con.execute("PRAGMA foreign_key_check").fetchone() is not None:
            # First row exists => violation; full PRAGMA returns None if empty
            raise RuntimeError("foreign_key_check falló: no se confirma la transacción")
        con.commit()
    with connect(db, True) as c:
        check = scalar(c, "PRAGMA quick_check")
        if check != "ok":
            raise RuntimeError(f"Verificación posterior falló: {check}")
    return {
        "status": "repaired" if created else "no_changes",
        "created_neuron_ids": created,
        "created_count": len(created),
        "backup": str(backup_path),
        "quick_check_after": check,
    }


def local_services():
    endpoints = {
        "api_live": "http://127.0.0.1:8010/health/live",
        "always_on_protected": "http://127.0.0.1:8010/api/runtime/always-on/status",
        "metabolism_protected": "http://127.0.0.1:8010/api/runtime/metabolism/status",
        "ollama": "http://127.0.0.1:11434/api/tags",
    }
    result = {}
    for name, url in endpoints.items():
        try:
            with urlopen(url, timeout=3) as resp:
                result[name] = {"http": resp.status, "note": "responding"}
        except HTTPError as exc:
            result[name] = {
                "http": exc.code,
                "note": "protected (authentication required)"
                if exc.code in (401, 403)
                else "HTTP error",
            }
        except (URLError, TimeoutError, OSError) as exc:
            result[name] = {"http": None, "note": type(exc).__name__}
    return result


def graph_debt(root: Path, db: Path):
    result = {
        "status": "not_available",
        "note": "No se cambió ninguna categoría de deuda",
    }
    cache = root / "artifacts/internal_graphs"
    index = cache / "index.json"
    if not index.is_file():
        result["note"] = (
            "Falta cache de grafos; no se reconstruyó para no bloquear el runtime"
        )
        return result
    try:
        from triade.observability.introspection import build_debt_report

        r = build_debt_report(root, db, cache_dir=cache, allow_build=False)
        items = r.get("items", {})
        signals = {}
        for kind, d in items.items():
            if not isinstance(d, dict):
                continue
            signals[kind] = {
                "count": d.get("count"),
                "sample": d.get("sample", [])[:15]
                if isinstance(d.get("sample"), list)
                else [],
            }
        result = {
            "status": r.get("status", "unknown"),
            "cache_generated_before_script": True,
            "debt_real_total": r.get("debt_real_total"),
            "debt_items_total": r.get("debt_items_total"),
            "by_classification": r.get("by_classification", {}),
            "graph_age_seconds": r.get("graphs_age_seconds"),
            "categories": signals,
            "limitations": "Sin modificar grafos ni autoejecutar scripts; las categorías contractuales requieren revisión individual.",
        }
    except Exception as exc:
        result = {
            "status": "error",
            "reason": type(exc).__name__,
            "note": str(exc)[:220],
        }
    return result


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    if tmp.is_symlink() or path.is_symlink():
        raise RuntimeError("Ruta de informe no segura")
    tmp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Tríade Ω · Control integral R6 sin acciones peligrosas"
    )
    ap.add_argument("mode", choices=["audit", "repair"])
    ap.add_argument("--root", default="/content/Triade")
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default="/content/triade_operacion_r5/triade_integral_r6")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    db = Path(args.db).resolve() if args.db else root / "triade/memory/triade.db"
    out = Path(args.out).resolve()
    if not db.is_file():
        raise RuntimeError("No existe SQLite; no se crea una Bodega vacía.")
    with connect(db, True) as c:
        before = assess(c)
    if before["quick_check"] != "ok":
        raise RuntimeError("Integridad SQLite no OK")
    report = {
        "version": "R6.0",
        "mode": args.mode,
        "db": str(db),
        "before": before,
        "policy": {
            "identity_modified": False,
            "stable_memory_promoted": False,
            "fake_tasks_created": False,
            "daemon_started": False,
            "other_graph_defects_autofixed": False,
        },
    }
    report["graph_debt"] = graph_debt(root, db)
    report["services"] = local_services()
    if args.mode == "repair":
        backup = out / (
            "pre_repair_"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "_"
            + str(os.getpid())
            + ".sqlite3"
        )
        report["repair"] = repair(db, before, backup)
        with connect(db, True) as c:
            report["after"] = assess(c)
    else:
        report["repair"] = {"status": "not_requested"}
    report_file = out / "report.json"
    write_report(report_file, report)
    print("TRÍADE Ω · CONTROL INTEGRAL R6")
    print("Estado SQLite:", before["quick_check"])
    print("Neuronas:", len(before["neurons"]))
    print("Misiones existentes:", before["counts"].get("neuron_missions"))
    print(
        "Misiones seguras faltantes:",
        before["neuron_actions"].get("create_safe_experimental_mission", 0),
    )
    print(
        "Revisión humana por objetivo ausente:",
        before["neuron_actions"].get("review", 0),
    )
    print("Acción aplicada:", report["repair"].get("status"))
    if args.mode == "repair":
        print("Misiones creadas:", report["repair"].get("created_neuron_ids", []))
    print("Activaciones registradas:", before["counts"].get("neuron_activity"))
    print("Runs neuronales verificables:", before["verifiable_neural_runs"])
    print(
        "Aplicaciones educativas:",
        before["counts"].get("neuron_education_applications"),
    )
    print(
        "Deuda de grafos:",
        report["graph_debt"].get("status"),
        "real:",
        report["graph_debt"].get("debt_real_total"),
    )
    print("Servicios HTTP:", {k: v.get("http") for k, v in report["services"].items()})
    print("Informe:", report_file)
    for w in before["warnings"]:
        print("ADVERTENCIA:", w)
    print("No se reiniciaron workers, API, Ollama ni el metabolismo.")
    return report


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("BLOQUEADO:", f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
