"""La lección preparada tiene que resolverse, no quedarse en `uncertain`.

Auditoría 2026-08-02, P1-01. El circuito de educación neuronal moría en
`lesson_prepared`: 7 sesiones con `baseline_score` y `post_score` a NULL,
`applied_run_count` 0, `result='uncertain'`, y `neuron_education_applications`
con **cero filas**. `learning_evidence` acumulaba hipótesis en `pending` que
nadie resolvía nunca.

`lesson_prepared` no es prueba de aprendizaje efectivo: es prueba de que se
preparó material.

Contrato que se fija aquí:

* **Sin aplicaciones suficientes no se decide.** `insufficient_evidence` es una
  respuesta legítima y explícita; `improved` por defecto sería exactamente el
  autorreporte que el encargo prohíbe.
* **`degraded` revierte solo**, y deja constancia de por qué.
* Una mejora funcional sin control causal conserva la hipótesis pendiente;
  la telemetría histórica por sí sola no acredita aprendizaje.
* **Idempotente**: resolver dos veces no duplica decisiones ni promociones.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.neurons.education_resolver import (
    MIN_APPLIED_RUNS,
    NeuronEducationResolver,
)
from triade.neurons.functional_evidence import VERSION, ensure_schema

ESQUEMA = """
-- Copiado del esquema REAL de produccion, incluidos los NOT NULL: un
-- esquema de prueba mas permisivo deja pasar fallos que solo aparecen contra
-- la base de verdad.
CREATE TABLE neuron_education_sessions (
    session_id TEXT PRIMARY KEY, curriculum_id TEXT NOT NULL,
    neuron_id INTEGER NOT NULL, competency_id TEXT NOT NULL, state TEXT NOT NULL,
    material_refs_json TEXT NOT NULL DEFAULT '[]',
    independent_source_count INTEGER NOT NULL DEFAULT 0,
    lesson_json TEXT NOT NULL DEFAULT '{}', exercise_json TEXT NOT NULL DEFAULT '{}',
    evaluation_json TEXT NOT NULL DEFAULT '{}', baseline_score REAL,
    post_score REAL, applied_run_count INTEGER NOT NULL DEFAULT 0,
    regression_count INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL,
    rollback_ref TEXT, created_at TEXT NOT NULL, finished_at TEXT NOT NULL);
CREATE TABLE neuron_education_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, run_id TEXT,
    outcome_score REAL, evidence_ref TEXT, created_at TEXT);
CREATE TABLE neuron_education_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, neuron_id INTEGER,
    event_type TEXT, payload_json TEXT, created_at TEXT);
CREATE TABLE learning_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT, decision TEXT,
    updated_at TEXT);
CREATE TABLE neurons (
    id INTEGER PRIMARY KEY, name TEXT, status TEXT, version TEXT);
"""

SESSION = "education-test"
NEURON = 7


def _db(
    tmp_path: Path,
    *,
    baseline: float | None = 0.5,
    aplicaciones: list[float] | None = None,
    state: str = "lesson_prepared",
) -> Path:
    ruta = tmp_path / "triade.db"
    with sqlite3.connect(ruta) as conn:
        conn.executescript(ESQUEMA)
        conn.execute(
            "INSERT INTO neurons VALUES (?,?,?,?)",
            (NEURON, "neurona-test", "experimental", "v1"),
        )
        conn.execute(
            "INSERT INTO neuron_education_sessions (session_id,curriculum_id,"
            "neuron_id,competency_id,state,baseline_score,result,created_at,"
            "finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                SESSION,
                "cur-1",
                NEURON,
                "comp-1",
                state,
                baseline,
                "uncertain",
                "2026-08-02T00:00:00+00:00",
                "2026-08-02T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO learning_evidence (candidate_id,decision,updated_at) "
            "VALUES (?,'pending','2026-08-02T00:00:00+00:00')",
            (f"neuron-education:{SESSION}",),
        )
        for i, score in enumerate(aplicaciones or []):
            conn.execute(
                "INSERT INTO neuron_education_applications (session_id,run_id,"
                "outcome_score,created_at) VALUES (?,?,?,?)",
                (SESSION, f"run-{i}", score, "2026-08-02T01:00:00+00:00"),
            )
        conn.commit()
    return ruta


def _functional(
    db: Path,
    *,
    before: int,
    after: int,
    session_id: str = SESSION,
    neuron_id: int = NEURON,
) -> None:
    """Observaciones binarias de prueba en SQLite temporal, nunca memoria real.

    Ejercita el comparador real: tres casos pre y seis runs post emparejados,
    rubricados, con fechas a ambos lados de la lección. No simula causalidad.
    """
    with sqlite3.connect(db) as conn:
        ensure_schema(conn)
        for phase, count, score, when in (
            ("pre", 3, before, "2026-08-01T00:00:00+00:00"),
            ("post", 6, after, "2026-08-03T00:00:00+00:00"),
        ):
            for i in range(count):
                conn.execute(
                    "INSERT INTO neuron_functional_assessments "
                    "(run_id,neuron_id,case_id,domain,phase,session_id,score,"
                    "rubric_version,answer_digest,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"{session_id}-{phase}-{i}",
                        neuron_id,
                        f"py{i % 3 + 1}",
                        "python_text",
                        phase,
                        None if phase == "pre" else session_id,
                        score,
                        VERSION,
                        f"fixture-{phase}-{i}",
                        when,
                    ),
                )


def _sesion(db: Path) -> sqlite3.Row:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM neuron_education_sessions WHERE session_id=?", (SESSION,)
        ).fetchone()


class TestSinEvidenciaNoSeDecide:
    def test_cero_aplicaciones_es_insufficient_evidence(self, tmp_path: Path) -> None:
        """Es el estado real hoy: 7 sesiones, cero aplicaciones."""
        db = _db(tmp_path, aplicaciones=[])

        resultado = NeuronEducationResolver(db).resolve_once()

        assert resultado["decision"] == "insufficient_evidence"
        assert resultado["applied_runs"] == 0
        assert _sesion(db)["result"] == "insufficient_evidence"

    def test_menos_del_minimo_tampoco_decide(self, tmp_path: Path) -> None:
        db = _db(tmp_path, aplicaciones=[0.9] * (MIN_APPLIED_RUNS - 1))

        assert (
            NeuronEducationResolver(db).resolve_once()["decision"]
            == "insufficient_evidence"
        )

    def test_no_promueve_por_autorreporte(self, tmp_path: Path) -> None:
        """Sin runs medidos, un 'la lección es buena' no vale nada."""
        db = _db(tmp_path, aplicaciones=[])
        NeuronEducationResolver(db).resolve_once()
        assert _sesion(db)["post_score"] is None


class TestDecisionPorMedicion:
    def test_mejora_funcional_sin_control_no_es_causal(self, tmp_path: Path) -> None:
        db = _db(tmp_path, baseline=0.0, aplicaciones=[0.9] * MIN_APPLIED_RUNS)
        _functional(db, before=0, after=1)

        resultado = NeuronEducationResolver(db).resolve_once()

        assert resultado["decision"] == "insufficient_evidence"
        assert resultado["functional_assessment"]["ready"] is True
        assert resultado["functional_assessment"]["causal_attribution"] is False
        assert "control causal" in resultado["reason"]
        assert resultado["state"] == "lesson_prepared"
        fila = _sesion(db)
        assert fila["post_score"] == pytest.approx(1.0)
        assert fila["baseline_score"] == pytest.approx(0.0)

    def test_sin_cambio_es_neutral(self, tmp_path: Path) -> None:
        db = _db(tmp_path, baseline=1.0, aplicaciones=[0.6] * MIN_APPLIED_RUNS)
        _functional(db, before=1, after=1)
        assert NeuronEducationResolver(db).resolve_once()["decision"] == "neutral"

    def test_empeora_es_degraded(self, tmp_path: Path) -> None:
        db = _db(tmp_path, baseline=1.0, aplicaciones=[0.2] * MIN_APPLIED_RUNS)
        _functional(db, before=1, after=0)
        assert NeuronEducationResolver(db).resolve_once()["decision"] == "degraded"

    def test_sin_baseline_no_hay_comparacion(self, tmp_path: Path) -> None:
        """Comparar contra nada no es medir."""
        db = _db(tmp_path, baseline=None, aplicaciones=[0.9] * MIN_APPLIED_RUNS)

        resultado = NeuronEducationResolver(db).resolve_once()

        assert resultado["decision"] == "insufficient_evidence"
        assert resultado["functional_assessment"] == {
            "ready": False,
            "reason": "no_functional_assessments",
        }


class TestRollbackYPromocion:
    def test_degraded_revierte_solo(self, tmp_path: Path) -> None:
        db = _db(tmp_path, baseline=1.0, aplicaciones=[0.2] * MIN_APPLIED_RUNS)
        _functional(db, before=1, after=0)

        resultado = NeuronEducationResolver(db).resolve_once()

        assert resultado["rolled_back"] is True
        fila = _sesion(db)
        assert fila["rollback_ref"], (
            "una degradación sin rollback_ref no se puede revertir"
        )
        assert fila["state"] == "rolled_back"

    def test_revision_conserva_la_version_anterior(self, tmp_path: Path) -> None:
        """Sin la versión previa guardada no hay rollback posible después."""
        db = _db(tmp_path, baseline=0.4, aplicaciones=[0.9] * MIN_APPLIED_RUNS)

        NeuronEducationResolver(db).resolve_once()

        assert _sesion(db)["rollback_ref"], "no se conservó a qué versión volver"

    def test_cada_decision_deja_evento(self, tmp_path: Path) -> None:
        db = _db(tmp_path, baseline=1.0, aplicaciones=[0.9] * MIN_APPLIED_RUNS)
        _functional(db, before=1, after=1)
        NeuronEducationResolver(db).resolve_once()

        with sqlite3.connect(db) as conn:
            tipos = [
                r[0]
                for r in conn.execute(
                    "SELECT event_type FROM neuron_education_events WHERE session_id=?",
                    (SESSION,),
                )
            ]
        assert any("neutral" in t for t in tipos), tipos


class TestIdempotencia:
    def test_resolver_dos_veces_no_duplica(self, tmp_path: Path) -> None:
        db = _db(tmp_path, baseline=1.0, aplicaciones=[0.9] * MIN_APPLIED_RUNS)
        _functional(db, before=1, after=1)
        r = NeuronEducationResolver(db)

        primera = r.resolve_once()
        segunda = r.resolve_once()

        assert primera["decision"] == "neutral"
        assert segunda["decision"] == "no_target", (
            "una sesión ya resuelta se volvió a resolver: se duplicaría la "
            "promoción y la evidencia"
        )

    def test_resuelve_la_evidencia_pendiente(self, tmp_path: Path) -> None:
        """Las hipótesis en `pending` eran las que nadie cerraba nunca."""
        db = _db(tmp_path, baseline=1.0, aplicaciones=[0.9] * MIN_APPLIED_RUNS)
        _functional(db, before=1, after=1)
        NeuronEducationResolver(db).resolve_once()

        with sqlite3.connect(db) as conn:
            decision = conn.execute(
                "SELECT decision FROM learning_evidence WHERE candidate_id=?",
                (f"neuron-education:{SESSION}",),
            ).fetchone()[0]
        assert decision == "neutral"


class TestNoGiraEnVacio:
    def test_sin_sesiones_pendientes(self, tmp_path: Path) -> None:
        db = _db(tmp_path, state="insufficient_material", aplicaciones=[])
        assert NeuronEducationResolver(db).resolve_once()["decision"] == "no_target"

    def test_sin_tablas_no_revienta(self, tmp_path: Path) -> None:
        ruta = tmp_path / "vacia.db"
        sqlite3.connect(ruta).close()
        assert NeuronEducationResolver(ruta).resolve_once()["decision"] == "no_target"


class TestRotaEntreSesiones:
    """Una sesión sin evidencia no puede acaparar el resolutor.

    `insufficient_evidence` conserva el estado `lesson_prepared` a propósito
    —la sesión sigue viva esperando más runs—, así que ordenar sólo por
    `created_at` hacía que la más antigua se eligiera siempre y las demás no se
    miraran nunca. Se vio contra una copia de producción: 7 sesiones y el
    resolutor devolvía la misma tres veces seguidas.
    """

    def test_la_segunda_llamada_mira_otra_sesion(self, tmp_path: Path) -> None:
        db = _db(tmp_path, aplicaciones=[])
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO neuron_education_sessions (session_id,curriculum_id,"
                "neuron_id,competency_id,state,result,created_at,finished_at) "
                "VALUES ('otra','cur-2',8,'comp-2','lesson_prepared','uncertain',"
                "'2026-08-02T00:00:01+00:00','2026-08-02T00:00:01+00:00')"
            )
            conn.commit()

        resolver = NeuronEducationResolver(db)
        vistas = {resolver.resolve_once()["session_id"] for _ in range(2)}

        assert len(vistas) == 2, f"el resolutor se quedó atascado en {vistas}"

    def test_una_sesion_resoluble_precede_a_otra_sin_evidencia(
        self, tmp_path: Path
    ) -> None:
        db = _db(tmp_path, aplicaciones=[])
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO neuron_education_sessions (session_id,curriculum_id,"
                "neuron_id,competency_id,state,baseline_score,result,created_at,"
                "finished_at) VALUES ('ready','cur-2',8,'comp-2','lesson_prepared',"
                "1.0,'uncertain','2026-08-02T00:00:01+00:00',"
                "'2026-08-02T00:00:01+00:00')"
            )
            conn.executemany(
                "INSERT INTO neuron_education_applications "
                "(session_id,run_id,outcome_score,created_at) VALUES "
                "('ready',?,?, '2026-08-02T01:00:00+00:00')",
                [(f"run-ready-{index}", 0.9) for index in range(MIN_APPLIED_RUNS)],
            )

        _functional(db, before=1, after=1, session_id="ready", neuron_id=8)
        result = NeuronEducationResolver(db).resolve_once()

        assert result["session_id"] == "ready"
        assert result["decision"] == "neutral"
