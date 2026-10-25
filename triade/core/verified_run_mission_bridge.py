"""Vincula contribuciones neuronales de runs de usuario a misiones reales.

No deduce independencia de fuentes a partir del verificador local: 'verified'
significa que existe un informe técnico para un run auténtico de usuario.
Nunca convierte eventos worker, pulsos ni verificaciones sintéticas en entrada externa.
No inserta aplicaciones educativas ni cambia memoria estable.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_SOURCE_ALLOWLIST = frozenset({"react-ui"})
_SOURCE_EVIDENCE = "user_run_locally_verified"
_EVIDENCE_TYPE = "user_neuron_contribution"
_SCORE_FIELDS = (
    "coherence_score", "memory_score", "safety_score",
    "usefulness_score", "traceability_score",
)


def bridge_verified_user_run(db_path: str | Path, run_id: str) -> dict:
    """Inserta una evidencia por misión/ejecución validada e idempotente.

    No llama al planificador, modelo o red. Los datos proceden solo de la DB.
    Evita duplicados en reintentos o llamadas repetidas del mismo run.
    """
    result = {"run_id": str(run_id), "created": [], "status": "not_eligible"}
    if not run_id:
        return result
    with sqlite3.connect(str(db_path), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA foreign_keys=ON")
        # Este puente no crea tablas, ni usa la ruta de migración en producción.
        needed = {"runs", "verification_reports", "neuron_activity", "neuron_missions", "neuron_evidence"}
        actual = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not needed.issubset(actual):
            result["reason"] = "missing_runtime_tables"
            return result
        origin = conn.execute("SELECT source FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if origin is None or str(origin["source"] or "") not in _SOURCE_ALLOWLIST:
            result["reason"] = "not_user_react_run"
            return result
        vcols = ",".join(_SCORE_FIELDS)
        verified = conn.execute(
            f"SELECT id,status,{vcols} FROM verification_reports WHERE run_id=? AND status='ok' "
            "ORDER BY id DESC LIMIT 1", (run_id,)
        ).fetchone()
        if verified is None:
            result["reason"] = "no_valid_verification_report"
            return result
        if any(verified[field] is None for field in _SCORE_FIELDS):
            result["reason"] = "missing_measured_score"
            return result
        score = sum(max(0.0, min(1.0, float(verified[field]))) for field in _SCORE_FIELDS) / len(_SCORE_FIELDS)
        if float(verified["safety_score"]) < 0.5:
            result["reason"] = "unsafe_verification"
            return result
        activations = conn.execute(
            "SELECT DISTINCT m.id AS mission_id,m.neuron_id "
            "FROM neuron_activity a JOIN neuron_missions m ON m.neuron_id=a.neuron_id "
            "WHERE a.run_id=? AND a.activated=1 AND m.status IN ('experimental','stable') "
            "ORDER BY m.id", (run_id,)
        ).fetchall()
        if not activations:
            result["reason"] = "no_matching_neuronal_activation"
            return result
        conn.execute("BEGIN IMMEDIATE") if not conn.in_transaction else None
        for row in activations:
            mid, nid = int(row["mission_id"]), int(row["neuron_id"])
            evidence_ref = f"run:{run_id}"
            ref_fragment = '%"' + evidence_ref + '"%'
            already = conn.execute(
                "SELECT id FROM neuron_evidence WHERE mission_id=? "
                "AND source=? AND evidence_type=? AND refs_json LIKE ? LIMIT 1",
                (mid, _SOURCE_EVIDENCE, _EVIDENCE_TYPE, ref_fragment),
            ).fetchone()
            if already:
                continue
            refs = [evidence_ref, f"verification_report:{verified['id']}", f"neuron_activity:neuron:{nid}:run:{run_id}"]
            content = json.dumps({
                "source_type": "authenticated_react_user_run",
                "run_id": run_id,
                "neuron_id": nid,
                "verification_report_id": int(verified["id"]),
                "assurance": "locally_verified_not_independent_third_party",
                "no_stable_memory_promotion": True,
            }, ensure_ascii=False)
            conn.execute(
                "INSERT INTO neuron_evidence "
                "(mission_id,neuron_id,evidence_type,source,content,refs_json,score,created_at) "
                "VALUES (?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (mid, nid, _EVIDENCE_TYPE, _SOURCE_EVIDENCE, content, json.dumps(refs), round(score, 4)),
            )
            result["created"].append({"mission_id": mid, "neuron_id": nid})
    result["status"] = "recorded" if result["created"] else "already_recorded"
    return result