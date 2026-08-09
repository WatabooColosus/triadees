"""El ciclo de educación neuronal se cierra: lección → medición → veredicto.

Medido en producción el 2026-08-09, el circuito estaba partido en dos mitades
que no se tocaban:

* neuronas 11 y 12 (`vision_image_understanding`, `code_repair_build_tests`)
  eran las **únicas** que llegaban a `lesson_prepared` — 13 sesiones — y no se
  pueden medir: sus 47 activaciones son todas de runs `pulse-*`, y
  `verification_reports` no tiene ni una fila `pulse-*` de 412;
* las seis neuronas que **sí** se miden (6471, 6871, 7052, 7053, 8399, 8400,
  130/84/71/71/6/5 runs con informe) son todas de dominio `system_governance`,
  y sus 29 sesiones murieron en `insufficient_material`.

La causa de la segunda mitad: de los cinco hosts de `TRUSTED_RESEARCH_HOSTS`,
cuatro eran documentación de Python y visión. Para un objetivo de gobernanza
sólo Wikipedia resultaba **relevante**, y una fuente independiente nunca
satisface la puerta de dos. Consecuencia:
`neuron_education_applications` con 0 filas, el resolutor devolviendo
`education_insufficient_evidence` 31 veces y 11 hipótesis en `pending`.

El arreglo no baja el umbral de dos fuentes —esa puerta es lo que impide
certificar una lección por autorreporte—: le da al dominio la segunda fuente
que nunca tuvo.

Estas pruebas recorren la cadena entera sobre una base de prueba. No hacen red:
el material se siembra como ya lo dejaría la investigación gobernada.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from triade.core.bodega import Bodega
from triade.core.guarded_web import TRUSTED_RESEARCH_HOSTS
from triade.neurons.curriculum import relevant_material, source_domain
from triade.neurons.education_applications import NeuronEducationApplicationRecorder
from triade.neurons.education_cycle import NeuronEducationCycle
from triade.neurons.education_resolver import (
    MIN_APPLIED_RUNS,
    NeuronEducationResolver,
)

#: La lección se crea "ahora"; el baseline queda claramente antes y las
#: aplicaciones claramente después. Sin ese margen, todo cae en el mismo
#: segundo y el registrador no puede separar las dos tandas.
ANTES = datetime.now(UTC) - timedelta(days=2)
DESPUES = datetime.now(UTC) + timedelta(hours=1)

DOMINIO = "system_governance"
OBJETIVO = "Gobernar la trazabilidad y la auditoría del sistema"

#: Lo único que la investigación gobernada podía traer y resultar relevante
#: para un objetivo de gobernanza: Wikipedia. Una sola fuente independiente.
MATERIAL_VIEJO = [
    (
        "cand-wiki",
        "Gobernanza",
        "La gobernanza de sistemas define auditoría y trazabilidad de software.",
        "https://es.wikipedia.org/wiki/Gobernanza",
    ),
]

#: La segunda fuente independiente, autorizada por el operador el 2026-08-09.
MATERIAL_NUEVO = [
    (
        "cand-owasp",
        "OWASP Top Ten",
        "Riesgos de seguridad: control de acceso, auditoría y trazabilidad del sistema.",
        "https://owasp.org/www-project-top-ten/",
    ),
]


def _material(filas: list[tuple[str, str, str, str]]) -> list[dict[str, object]]:
    return [
        {
            "candidate_id": cid,
            "title": titulo,
            "content": contenido,
            "domain": DOMINIO,
            "source_type": "web",
            "source_ref": ref,
            "status": "internally_checked",
        }
        for cid, titulo, contenido, ref in filas
    ]


def _base(tmp_path: Path) -> Path:
    """Base con el esquema real; el mismo que usa el runtime."""
    db_path = tmp_path / "triade.db"
    Bodega(db_path=db_path)
    return db_path


def _sembrar_neurona(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO neurons (name,mission,domain,status,created_by,created_at)"
            " VALUES (?,?,?,?,?,datetime('now'))",
            ("neurona-gobernanza", OBJETIVO, DOMINIO, "experimental", "test"),
        )
        return int(cur.lastrowid or 0)


def _sembrar_material(db_path: Path, filas: list[tuple[str, str, str, str]]) -> None:
    with sqlite3.connect(db_path) as conn:
        for cid, titulo, contenido, ref in filas:
            conn.execute(
                "INSERT INTO learning_queue (candidate_id,title,content,domain,"
                "source_type,source_ref,status,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
                (cid, titulo, contenido, DOMINIO, "web", ref, "internally_checked"),
            )


def _sembrar_runs(
    db_path: Path,
    neuron_id: int,
    *,
    prefijo: str,
    cuantos: int,
    score: float,
    cuando: datetime,
) -> None:
    """Runs medidos de esa neurona: actividad + informe del Verifier.

    Es el cruce que el registrador necesita; sin las dos mitades un run no
    cuenta como medido.

    `cuando` es explícito y no `datetime('now')`: el registrador separa baseline
    de aplicaciones por si el run cae antes o después de la lección, y con
    resolución de un segundo las dos tandas caerían en el mismo instante.
    """
    marca = cuando.strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db_path) as conn:
        for i in range(cuantos):
            run_id = f"{prefijo}-{i}"
            conn.execute(
                "INSERT INTO runs (run_id,source,user_input,status,created_at)"
                " VALUES (?,?,?,?,?)",
                (run_id, "test", "consulta", "completed", marca),
            )
            conn.execute(
                "INSERT INTO neuron_activity (neuron_id,run_id,activated,created_at)"
                " VALUES (?,?,1,?)",
                (neuron_id, run_id, marca),
            )
            conn.execute(
                "INSERT INTO verification_reports (run_id,coherence_score,"
                "memory_score,safety_score,usefulness_score,traceability_score,"
                "status,created_at) VALUES (?,?,?,?,?,?,?,datetime('now'))",
                (run_id, score, score, score, score, score, "verified"),
            )


def _evidencia(db_path: Path, session_id: str) -> str | None:
    with sqlite3.connect(db_path) as conn:
        fila = conn.execute(
            "SELECT decision FROM learning_evidence WHERE candidate_id = ?",
            (f"neuron-education:{session_id}",),
        ).fetchone()
    return None if fila is None else str(fila[0])


def _sesion(db_path: Path, session_id: str) -> sqlite3.Row:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM neuron_education_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()


# --- El corte, aislado -------------------------------------------------------


def test_una_sola_fuente_no_abre_la_puerta_de_dos(tmp_path: Path) -> None:
    """ANTES: sólo Wikipedia resultaba relevante y la lección no se creaba.

    La puerta sigue cerrada con una fuente: el arreglo no la debilitó.
    """
    material = relevant_material(_material(MATERIAL_VIEJO), OBJETIVO, DOMINIO)
    hosts = {source_domain(str(m["source_ref"])) for m in material}

    assert len(hosts) < 2


def test_la_segunda_fuente_autorizada_abre_la_puerta(tmp_path: Path) -> None:
    """DESPUÉS: con la fuente de gobernanza hay dos dominios independientes."""
    material = relevant_material(
        _material(MATERIAL_VIEJO + MATERIAL_NUEVO), OBJETIVO, DOMINIO
    )
    hosts = {source_domain(str(m["source_ref"])) for m in material}

    assert len(hosts) >= 2
    assert "owasp.org" in hosts
    assert hosts <= TRUSTED_RESEARCH_HOSTS, "ninguna fuente fuera de la lista vetada"


def test_los_hosts_de_gobernanza_estan_vetados() -> None:
    for host in ("owasp.org", "www.nist.gov", "docs.github.com", "martinfowler.com"):
        assert host in TRUSTED_RESEARCH_HOSTS


# --- La cadena entera --------------------------------------------------------


def test_sin_segunda_fuente_el_ciclo_no_produce_leccion(tmp_path: Path) -> None:
    """El estado en que llevaba 29 sesiones: material insuficiente, sin lección."""
    db_path = _base(tmp_path)
    _sembrar_neurona(db_path)
    _sembrar_material(db_path, MATERIAL_VIEJO)

    resultado = NeuronEducationCycle(db_path).run_once()

    assert resultado["status"] == "needs_research"
    assert resultado["independent_sources"] < 2


def test_ciclo_completo_mejora_se_consolida(tmp_path: Path) -> None:
    """GAP → LECCIÓN → EVIDENCIA → APLICACIÓN MEDIDA → DECISIÓN → CONSOLIDACIÓN."""
    db_path = _base(tmp_path)
    neuron_id = _sembrar_neurona(db_path)
    _sembrar_material(db_path, MATERIAL_VIEJO + MATERIAL_NUEVO)
    # Baseline: cómo le iba ANTES de la lección.
    _sembrar_runs(
        db_path, neuron_id, prefijo="antes", cuantos=6, score=0.50, cuando=ANTES
    )

    leccion = NeuronEducationCycle(db_path).run_once()
    session_id = str(leccion["session_id"])

    assert leccion["status"] == "lesson_prepared"
    assert leccion["independent_sources"] >= 2
    assert _evidencia(db_path, session_id) == "pending"

    # Runs posteriores a la lección, mejores. El registrador los cruza.
    _sembrar_runs(
        db_path,
        neuron_id,
        prefijo="despues",
        cuantos=MIN_APPLIED_RUNS,
        score=0.90,
        cuando=DESPUES,
    )
    registro = NeuronEducationApplicationRecorder(db_path).record_once()

    assert registro["applications_added"] >= MIN_APPLIED_RUNS
    assert _sesion(db_path, session_id)["baseline_score"] == 0.50

    veredicto = NeuronEducationResolver(db_path).resolve_once()

    assert veredicto["decision"] == "improved"
    assert veredicto["applied_runs"] >= MIN_APPLIED_RUNS
    assert veredicto["post_score"] == 0.90
    # La versión previa se conserva: sin ella no habría rollback después.
    assert veredicto["rollback_ref"]
    sesion = _sesion(db_path, session_id)
    assert sesion["state"] == "applied_improved"
    # La hipótesis deja de estar en `pending`: ése era el eslabón muerto.
    assert _evidencia(db_path, session_id) == "improved"


def test_ciclo_completo_regresion_se_revierte(tmp_path: Path) -> None:
    """El ciclo no está cerrado si sólo funciona cuando mejora."""
    db_path = _base(tmp_path)
    neuron_id = _sembrar_neurona(db_path)
    _sembrar_material(db_path, MATERIAL_VIEJO + MATERIAL_NUEVO)
    _sembrar_runs(
        db_path, neuron_id, prefijo="antes", cuantos=6, score=0.90, cuando=ANTES
    )

    leccion = NeuronEducationCycle(db_path).run_once()
    session_id = str(leccion["session_id"])
    assert leccion["status"] == "lesson_prepared"

    # Después de la lección le va PEOR.
    _sembrar_runs(
        db_path,
        neuron_id,
        prefijo="despues",
        cuantos=MIN_APPLIED_RUNS,
        score=0.40,
        cuando=DESPUES,
    )
    NeuronEducationApplicationRecorder(db_path).record_once()

    veredicto = NeuronEducationResolver(db_path).resolve_once()

    assert veredicto["decision"] == "degraded"
    assert veredicto["rolled_back"] is True
    assert veredicto["rollback_ref"]
    assert _sesion(db_path, session_id)["state"] == "rolled_back"
    assert _evidencia(db_path, session_id) == "degraded"


def test_sin_runs_medidos_no_se_promueve_por_autorreporte(tmp_path: Path) -> None:
    """La puerta conservadora sigue puesta: sin runs, no hay veredicto."""
    db_path = _base(tmp_path)
    neuron_id = _sembrar_neurona(db_path)
    _sembrar_material(db_path, MATERIAL_VIEJO + MATERIAL_NUEVO)
    _sembrar_runs(
        db_path, neuron_id, prefijo="antes", cuantos=6, score=0.50, cuando=ANTES
    )

    leccion = NeuronEducationCycle(db_path).run_once()
    session_id = str(leccion["session_id"])
    # Ningún run posterior: no hay nada que medir.
    NeuronEducationApplicationRecorder(db_path).record_once()

    veredicto = NeuronEducationResolver(db_path).resolve_once()

    assert veredicto["decision"] == "insufficient_evidence"
    assert _sesion(db_path, session_id)["state"] == "lesson_prepared"
    # La hipótesis sigue viva: cerrarla sería declarar un veredicto no alcanzado.
    assert _evidencia(db_path, session_id) == "pending"
