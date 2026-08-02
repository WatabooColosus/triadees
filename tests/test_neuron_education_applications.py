"""Registrar cómo le fue a la neurona después de la lección.

Auditoría 2026-08-02, última pieza de P1-01. El resolutor decidía sobre
`neuron_education_applications`, y esa tabla tenía **cero filas**: sin runs
medidos sólo podía responder `insufficient_evidence`.

No se inventa métrica. Los dos datos ya existían por separado y nadie los unía:

* `neuron_activity` registra qué neurona se activó en qué run (287 filas);
* `verification_reports` guarda cinco puntuaciones por run, escritas por el
  Verifier durante runs reales (235 filas).

En producción **162 filas cruzan por `run_id`**. El productor es esa unión.

Sobre la atribución
-------------------
Que una neurona participe en un run no significa que ese run saliera bien *por
ella*. Es un proxy, no una prueba de causalidad, y por eso el resolutor es
conservador y `neutral` es un resultado legítimo. Lo que sí se controla:

* sólo cuentan runs donde la neurona **se activó** de verdad;
* el baseline usa **la misma neurona y la misma métrica**, antes de la lección;
* un run sin informe de verificación no se cuenta como cero — se ignora, porque
  «no medido» no es «malo».
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.neurons.education_applications import (
    NeuronEducationApplicationRecorder,
)

ESQUEMA = """
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
CREATE TABLE neuron_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, neuron_id INTEGER,
    name TEXT, domain TEXT, status TEXT, activation_type TEXT,
    activated INTEGER, created_at TEXT);
CREATE TABLE verification_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, status TEXT,
    coherence_score REAL, memory_score REAL, safety_score REAL,
    usefulness_score REAL, traceability_score REAL, created_at TEXT);
"""

SESSION = "education-app"
NEURON = 11
LECCION = "2026-07-30T00:00:00+00:00"


def _db(tmp_path: Path) -> Path:
    ruta = tmp_path / "triade.db"
    with sqlite3.connect(ruta) as conn:
        conn.executescript(ESQUEMA)
        conn.execute(
            "INSERT INTO neuron_education_sessions (session_id,curriculum_id,"
            "neuron_id,competency_id,state,result,created_at,finished_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                SESSION,
                "cur",
                NEURON,
                "comp",
                "lesson_prepared",
                "uncertain",
                LECCION,
                LECCION,
            ),
        )
        conn.commit()
    return ruta


def _run(
    db: Path,
    run_id: str,
    *,
    cuando: str,
    neuron: int = NEURON,
    activated: int = 1,
    scores: tuple[float, ...] | None = (0.8, 0.8, 0.8, 0.8, 0.8),
) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO neuron_activity (run_id,neuron_id,activated,created_at) "
            "VALUES (?,?,?,?)",
            (run_id, neuron, activated, cuando),
        )
        if scores is not None:
            conn.execute(
                "INSERT INTO verification_reports (run_id,status,coherence_score,"
                "memory_score,safety_score,usefulness_score,traceability_score,"
                "created_at) VALUES (?,'ok',?,?,?,?,?,?)",
                (run_id, *scores, cuando),
            )
        conn.commit()


def _aplicaciones(db: Path) -> list[sqlite3.Row]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return list(
            conn.execute(
                "SELECT * FROM neuron_education_applications WHERE session_id=? "
                "ORDER BY run_id",
                (SESSION,),
            )
        )


def _sesion(db: Path) -> sqlite3.Row:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM neuron_education_sessions WHERE session_id=?", (SESSION,)
        ).fetchone()


class TestRegistraRunsPosteriores:
    def test_un_run_posterior_se_registra(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _run(db, "run-post", cuando="2026-07-30T10:00:00+00:00")

        resultado = NeuronEducationApplicationRecorder(db).record_once()

        assert resultado["applications_added"] == 1
        filas = _aplicaciones(db)
        assert filas[0]["run_id"] == "run-post"
        assert filas[0]["outcome_score"] == pytest.approx(0.8)

    def test_los_runs_anteriores_no_son_aplicaciones(self, tmp_path: Path) -> None:
        """Un run de antes de la lección no puede probar que la lección sirvió."""
        db = _db(tmp_path)
        _run(db, "run-previo", cuando="2026-07-29T10:00:00+00:00")

        NeuronEducationApplicationRecorder(db).record_once()

        assert _aplicaciones(db) == []

    def test_otra_neurona_no_cuenta(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _run(db, "run-ajeno", cuando="2026-07-30T10:00:00+00:00", neuron=99)

        NeuronEducationApplicationRecorder(db).record_once()

        assert _aplicaciones(db) == []

    def test_una_neurona_no_activada_no_cuenta(self, tmp_path: Path) -> None:
        """Estar en la tabla no es haber participado."""
        db = _db(tmp_path)
        _run(db, "run-inactivo", cuando="2026-07-30T10:00:00+00:00", activated=0)

        NeuronEducationApplicationRecorder(db).record_once()

        assert _aplicaciones(db) == []


class TestNoMedidoNoEsMalo:
    def test_un_run_sin_informe_se_ignora(self, tmp_path: Path) -> None:
        """Contarlo como cero hundiría la media y fabricaría una degradación."""
        db = _db(tmp_path)
        _run(db, "run-sin-informe", cuando="2026-07-30T10:00:00+00:00", scores=None)

        resultado = NeuronEducationApplicationRecorder(db).record_once()

        assert resultado["applications_added"] == 0
        assert _aplicaciones(db) == []


class TestBaseline:
    def test_el_baseline_sale_de_runs_anteriores(self, tmp_path: Path) -> None:
        """Misma neurona, misma métrica, antes de la lección."""
        db = _db(tmp_path)
        _run(
            db,
            "prev-1",
            cuando="2026-07-29T10:00:00+00:00",
            scores=(0.4, 0.4, 0.4, 0.4, 0.4),
        )
        _run(
            db,
            "prev-2",
            cuando="2026-07-29T11:00:00+00:00",
            scores=(0.6, 0.6, 0.6, 0.6, 0.6),
        )

        NeuronEducationApplicationRecorder(db).record_once()

        assert _sesion(db)["baseline_score"] == pytest.approx(0.5)

    def test_sin_runs_previos_no_se_inventa_baseline(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _run(db, "run-post", cuando="2026-07-30T10:00:00+00:00")

        NeuronEducationApplicationRecorder(db).record_once()

        assert _sesion(db)["baseline_score"] is None

    def test_el_baseline_no_se_recalcula(self, tmp_path: Path) -> None:
        """Moverlo después invalidaría la comparación ya hecha."""
        db = _db(tmp_path)
        _run(db, "prev-1", cuando="2026-07-29T10:00:00+00:00", scores=(0.4,) * 5)
        recorder = NeuronEducationApplicationRecorder(db)
        recorder.record_once()

        _run(db, "prev-2", cuando="2026-07-29T11:00:00+00:00", scores=(1.0,) * 5)
        recorder.record_once()

        assert _sesion(db)["baseline_score"] == pytest.approx(0.4)


class TestIdempotencia:
    def test_el_mismo_run_no_se_registra_dos_veces(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _run(db, "run-post", cuando="2026-07-30T10:00:00+00:00")
        recorder = NeuronEducationApplicationRecorder(db)

        recorder.record_once()
        segunda = recorder.record_once()

        assert segunda["applications_added"] == 0
        assert len(_aplicaciones(db)) == 1

    def test_actualiza_el_contador_de_la_sesion(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        for i in range(3):
            _run(db, f"run-{i}", cuando=f"2026-07-30T1{i}:00:00+00:00")

        NeuronEducationApplicationRecorder(db).record_once()

        assert _sesion(db)["applied_run_count"] == 3


class TestRegresiones:
    def test_una_caida_de_safety_cuenta_como_regresion(self, tmp_path: Path) -> None:
        """Mejorar la media no vale si la seguridad baja."""
        db = _db(tmp_path)
        _run(
            db,
            "run-malo",
            cuando="2026-07-30T10:00:00+00:00",
            scores=(0.9, 0.9, 0.3, 0.9, 0.9),
        )

        NeuronEducationApplicationRecorder(db).record_once()

        assert _sesion(db)["regression_count"] == 1


class TestNoGiraEnVacio:
    def test_sin_sesiones_no_hace_nada(self, tmp_path: Path) -> None:
        ruta = tmp_path / "vacia.db"
        with sqlite3.connect(ruta) as conn:
            conn.executescript(ESQUEMA)
            conn.commit()

        resultado = NeuronEducationApplicationRecorder(ruta).record_once()

        assert resultado["sessions_seen"] == 0

    def test_sin_tablas_no_revienta(self, tmp_path: Path) -> None:
        ruta = tmp_path / "nada.db"
        sqlite3.connect(ruta).close()
        assert (
            NeuronEducationApplicationRecorder(ruta).record_once()["sessions_seen"] == 0
        )
