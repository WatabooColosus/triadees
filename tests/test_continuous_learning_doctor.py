"""El doctor del aprendizaje continuo tiene que distinguir apagado de atascado.

Un diagnóstico que dice «sano» porque no encuentra errores es exactamente lo que
permitió que un circuito roto sobreviviera semanas. Estas pruebas fijan que
`status` sale de las señales y no de una impresión, y que cada apartado declara
su procedencia.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from triade.learning.doctor import ContinuousLearningDoctor

ESQUEMA = """
CREATE TABLE learning_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT UNIQUE,
    source_type TEXT, source_ref TEXT, title TEXT, content TEXT,
    normalized_summary TEXT, domain TEXT, risk_level TEXT, confidence REAL,
    utility REAL, status TEXT, verification_notes TEXT, created_at TEXT,
    updated_at TEXT, run_use_count INTEGER DEFAULT 0,
    run_outcome_scores TEXT, avg_outcome_score REAL DEFAULT 0);
CREATE TABLE autonomous_tasks (
    task_id TEXT PRIMARY KEY, task_type TEXT, status TEXT, created_at TEXT,
    updated_at TEXT, last_error TEXT, lease_expires_at TEXT);
CREATE TABLE learning_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT, decision TEXT,
    updated_at TEXT);
CREATE TABLE learning_retrieval_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, injected_ids TEXT,
    created_at TEXT);
CREATE TABLE neuron_education_sessions (session_id TEXT, state TEXT);
CREATE TABLE neuron_education_applications (id INTEGER PRIMARY KEY);
"""


def _iso(horas: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=horas)).isoformat()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    ruta = tmp_path / "triade.db"
    with sqlite3.connect(ruta) as conn:
        conn.executescript(ESQUEMA)
        conn.commit()
    return ruta


def _candidato(db: Path, cid: str, status: str, horas: float = 1) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO learning_queue (candidate_id,source_type,status,content,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (cid, "experience", status, "algo", _iso(horas), _iso(horas)),
        )
        conn.commit()


def _tarea(db: Path, tid: str, tipo: str, status: str, horas: float = 1) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO autonomous_tasks (task_id,task_type,status,created_at,"
            "updated_at) VALUES (?,?,?,?,?)",
            (tid, tipo, status, _iso(horas), _iso(horas)),
        )
        conn.commit()


class TestStatus:
    def test_apagado_es_off(self, db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "0")
        assert ContinuousLearningDoctor(db).diagnose()["status"] == "off"

    def test_encendido_sin_trabajo_es_idle(
        self, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sin nada que hacer no es un fallo."""
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
        assert ContinuousLearningDoctor(db).diagnose()["status"] == "idle"

    def test_candidatos_esperando_sin_progreso_es_stalled(
        self, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La señal que importa: hay trabajo elegible y nada avanza."""
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
        for i in range(3):
            _candidato(db, f"c{i}", "internally_checked", horas=50)

        informe = ContinuousLearningDoctor(db).diagnose()

        assert informe["status"] == "stalled"
        assert any("esperando" in r for r in informe["reasons"])

    def test_con_progreso_es_healthy(
        self, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
        _candidato(db, "c1", "internally_checked")
        _tarea(db, "t1", "learning_candidate_generation", "completed")

        assert ContinuousLearningDoctor(db).diagnose()["status"] == "healthy"


class TestSenalesConcretas:
    def test_detecta_tipos_nunca_ejecutados(
        self, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
        _tarea(db, "t1", "learning_candidate_generation", "completed")

        nunca = ContinuousLearningDoctor(db).diagnose()["tasks"]["never_executed"]

        assert "learning_evidence_generation" in nunca
        assert "learning_candidate_generation" not in nunca

    def test_detecta_tareas_atascadas(
        self, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
        _tarea(db, "viva", "learning_candidate_generation", "running", horas=5)

        informe = ContinuousLearningDoctor(db).diagnose()

        assert len(informe["tasks"]["stuck_over_1h"]) == 1
        assert informe["tasks"]["stuck_over_1h"][0]["task_id"] == "viva"

    def test_detecta_la_ruta_antigua_activa(
        self, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO learning_queue (candidate_id,source_type,status,content,"
                "created_at,updated_at) VALUES ('v','conversation','internally_checked',"
                "'run_id: x input: y response: z',?,?)",
                (_iso(1), _iso(1)),
            )
            conn.commit()

        legacy = ContinuousLearningDoctor(db).diagnose()["legacy_route"]

        assert legacy["legacy_active"] is True
        assert legacy["transcript_dumps_total"] == 1

    def test_dice_si_el_circuito_neuronal_cierra(
        self, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`lesson_prepared` sin aplicaciones no es un circuito cerrado."""
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO neuron_education_sessions VALUES ('s1','lesson_prepared')"
            )
            conn.commit()

        assert (
            ContinuousLearningDoctor(db).diagnose()["neuron_evaluator"][
                "circuit_closes"
            ]
            is False
        )


class TestProcedencia:
    def test_cada_apartado_declara_su_fuente(
        self, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un dato sin procedencia es otra pantalla que puede mentir."""
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
        informe = ContinuousLearningDoctor(db).diagnose()

        for apartado in (
            "config",
            "tasks",
            "candidates",
            "evidence",
            "consolidated",
            "later_use",
            "legacy_route",
            "neuron_evaluator",
            "errors",
        ):
            assert informe[apartado].get("source"), apartado

    def test_la_ventana_es_explicita(
        self, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
        informe = ContinuousLearningDoctor(db, window_hours=6).diagnose()
        assert informe["config"]["window_hours"] == 6

    def test_base_inexistente_no_revienta(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
        informe = ContinuousLearningDoctor(tmp_path / "no-existe.db").diagnose()
        assert informe["config"]["db_exists"] is False
        assert informe["status"] in {"idle", "stalled"}


class TestOrigenDeLaConfiguracion:
    """El doctor corre desde una shell sin las variables del runtime.

    Quien las tiene es el proceso de uvicorn, arrancado con
    `set -a && . ./.env`. Mirar sólo `os.environ` hacía que dijera `off` con el
    aprendizaje encendido: un falso negativo peor que no tener diagnóstico.
    """

    def test_lee_el_env_cuando_no_esta_en_el_entorno(
        self, db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TRIADE_POST_RUN_LEARNING", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "# comentario\nTRIADE_POST_RUN_LEARNING=1\n", encoding="utf-8"
        )

        config = ContinuousLearningDoctor(db).diagnose()["config"]

        assert config["learning_enabled"] is True
        assert config["learning_enabled_source"] == ".env"

    def test_el_entorno_manda_sobre_el_env(
        self, db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lo que el proceso tiene cargado es la verdad, no lo que diga el fichero."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("TRIADE_POST_RUN_LEARNING=0\n", encoding="utf-8")
        monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")

        config = ContinuousLearningDoctor(db).diagnose()["config"]

        assert config["learning_enabled"] is True
        assert config["learning_enabled_source"] == "os.environ"

    def test_sin_ninguna_fuente_es_el_defecto(
        self, db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TRIADE_POST_RUN_LEARNING", raising=False)
        monkeypatch.chdir(tmp_path)

        config = ContinuousLearningDoctor(db).diagnose()["config"]

        assert config["learning_enabled"] is False
        assert config["learning_enabled_source"] == "default"
