"""Lo que espera una firma tiene que verse, y decir si de verdad se puede firmar.

Las compuertas humanas estaban repartidas y sólo una se veía: el adaptador PEFT
tenía tarjeta en Cabina Viva y la aprobación de una propuesta de auto-mejora
sólo existía como ruta HTTP, sin ningún sitio donde apareciera que estaba
esperando. Una compuerta que nadie ve no gobierna: deja el circuito parado con
aspecto de estar funcionando.

Y la parte que faltaba del todo: decir por qué **no** se puede firmar. El canary
de la base viva llevaba desde el 2026-07-29 acumulando observaciones —305 al
27-ago— y `activate()` lo habría rechazado igual cualquiera de esos días.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from triade.core.human_gates import pending_human_gates


def _base_con_canary(tmp_path: Path, *, base_model: str) -> Path:
    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE governed_peft_versions (
            version_id TEXT PRIMARY KEY, adapter_path TEXT, integrity_sha256 TEXT,
            dataset_id TEXT, status TEXT, traffic_percent REAL, baseline_quality REAL,
            rollback_ref TEXT, approved_by TEXT, previous_version_id TEXT,
            created_at TEXT, updated_at TEXT, base_model TEXT)"""
    )
    conn.execute(
        """CREATE TABLE governed_peft_observations (
            observation_id TEXT PRIMARY KEY, version_id TEXT, quality REAL,
            latency_ms REAL, success INTEGER, evidence_ref TEXT, created_at TEXT)"""
    )
    conn.execute(
        "INSERT INTO governed_peft_versions VALUES"
        " ('v1','/no/existe','sha','ds','canary',5.0,-4.0,'rb',NULL,NULL,"
        " '2026-07-29T00:00:00+00:00','2026-07-29T00:00:00+00:00',?)",
        (base_model,),
    )
    conn.execute(
        "INSERT INTO governed_peft_observations VALUES"
        " ('o1','v1',1.0,10.0,1,'ev','2026-08-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()
    return db


def test_un_canary_sobre_un_modelo_no_servido_no_se_puede_firmar(
    tmp_path: Path,
) -> None:
    """Y el motivo tiene que ser el real, no «no declara base_model».

    El adaptador de producción se entrenó sobre `Qwen/Qwen2.5-0.5B-Instruct`
    mientras el runtime sirve `qwen2.5:3b-instruct`. `activate()` lo bloquea con
    razón —un adaptador sobre un modelo que nadie sirve dejaría el slot de
    producción apuntando a algo inservible— pero nadie lo decía.
    """
    db = _base_con_canary(tmp_path, base_model="Qwen/Qwen2.5-0.5B-Instruct")
    resultado = pending_human_gates(db)
    peft = [g for g in resultado["gates"] if g["kind"] == "peft_activation"]
    assert len(peft) == 1
    assert peft[0]["ready"] is False
    assert any("no sirve" in b for b in peft[0]["blockers"]), peft[0]["blockers"]


def test_leer_la_compuerta_no_aprueba_nada(tmp_path: Path) -> None:
    """Un observador que altera lo observado no sirve para observar."""
    db = _base_con_canary(tmp_path, base_model="Qwen/Qwen2.5-0.5B-Instruct")
    antes = (
        sqlite3.connect(db)
        .execute("SELECT status, approved_by FROM governed_peft_versions")
        .fetchone()
    )
    pending_human_gates(db)
    despues = (
        sqlite3.connect(db)
        .execute("SELECT status, approved_by FROM governed_peft_versions")
        .fetchone()
    )
    assert antes == despues


def test_una_propuesta_sin_destino_se_marca_como_no_firmable(tmp_path: Path) -> None:
    """Aprobarla no la haría avanzar: el handler la bloquearía igual."""
    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE improvement_proposals (
            proposal_id TEXT PRIMARY KEY, signal_id TEXT, status TEXT,
            payload_json TEXT, created_at TEXT)"""
    )
    conn.execute(
        """CREATE TABLE improvement_signals (
            signal_id TEXT PRIMARY KEY, capability_id TEXT, metric_id TEXT,
            status TEXT, priority REAL, payload_json TEXT, created_at TEXT)"""
    )
    conn.execute(
        "INSERT INTO improvement_signals VALUES ('s1','cap','met','open',0.1,?,'0')",
        (json.dumps({"confidence": 0.4, "capability_id": "cap"}),),
    )
    conn.execute(
        "INSERT INTO improvement_proposals VALUES ('p1','s1','open',?,'0')",
        (json.dumps({"hypothesis": "algo", "requested_capability": "cap"}),),
    )
    conn.commit()
    conn.close()

    gates = pending_human_gates(db)["gates"]
    prop = [g for g in gates if g["kind"] == "improvement_proposal"]
    assert len(prop) == 1
    assert prop[0]["ready"] is False
    assert any("neurona destino" in b for b in prop[0]["blockers"])
    assert prop[0]["policy_would_approve"] is False


def test_sin_base_viva_no_revienta(tmp_path: Path) -> None:
    assert pending_human_gates(tmp_path / "no-existe.db")["count"] == 0
