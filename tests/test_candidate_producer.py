"""Un saber tiene que haberlo dicho la persona, no inferirlo el modelo.

Los 633 candidatos actuales son transcripciones de runs y plantillas: el
sistema copiándose a sí mismo. Estos casos fijan que eso no vuelva a entrar.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.learning.candidate_producer import (
    PRODUCER_VERSION,
    ExperienceLearningCandidateProducer,
)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    ruta = tmp_path / "triade.db"
    conn = sqlite3.connect(ruta)
    conn.execute(
        """CREATE TABLE learning_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT UNIQUE,
            source_type TEXT, source_ref TEXT, title TEXT, content TEXT,
            normalized_summary TEXT, domain TEXT, risk_level TEXT, confidence REAL,
            utility REAL, status TEXT, verification_notes TEXT, created_at TEXT,
            updated_at TEXT, run_use_count INTEGER DEFAULT 0,
            run_outcome_scores TEXT, avg_outcome_score REAL DEFAULT 0)"""
    )
    conn.commit()
    conn.close()
    return ruta


@pytest.fixture
def producer(db: Path) -> ExperienceLearningCandidateProducer:
    return ExperienceLearningCandidateProducer(db)


# ── lo que sí es aprendible ───────────────────────────────────────────


def test_extrae_una_preferencia_explicita(producer) -> None:
    r = producer.produce(
        run_id="r1",
        role="user",
        message="Para los informes de Tríade, usa primero el veredicto y después la evidencia.",
    )
    assert len(r.candidates) == 1
    c = r.candidates[0]
    assert c.type == "preference"
    assert c.source_role == "user"
    assert c.source_run_id == "r1"
    assert c.provenance == "run:r1|role:user"


def test_extrae_una_correccion_con_valor_viejo_y_nuevo(producer) -> None:
    r = producer.produce(
        run_id="r1",
        role="user",
        message="El puerto no es 8080, lo correcto es 8010.",
    )
    assert len(r.candidates) == 1
    c = r.candidates[0]
    assert c.type == "correction"
    assert c.previous_value
    assert c.corrected_value
    assert "8010" in c.corrected_value


def test_extrae_un_hecho(producer) -> None:
    r = producer.produce(
        run_id="r1",
        role="user",
        message="El identificador del runbook de recuperación es RBK-7731-QUETZAL.",
    )
    assert r.candidates[0].type == "fact"


def test_un_procedimiento_conserva_su_postcondicion(producer) -> None:
    r = producer.produce(
        run_id="r1",
        role="user",
        message="Para parar Tríade primero se drena la cola y después se liberan los leases.",
    )
    c = r.candidates[0]
    assert c.type == "procedure"
    assert c.postcondition


# ── lo que no puede entrar ────────────────────────────────────────────


def test_no_aprende_de_la_respuesta_del_modelo(producer) -> None:
    """Aprender del propio output es cómo se llenó la cola de transcripciones."""
    r = producer.produce(
        run_id="r1",
        role="assistant",
        message="El identificador del runbook es RBK-7731-QUETZAL.",
    )
    assert r.candidates == []
    assert "rol_no_confiable" in r.rejected[0]["reason"]


def test_no_copia_una_transcripcion_de_run(producer) -> None:
    r = producer.produce(
        run_id="r1",
        role="user",
        message="run_id: run-2026 source: api intent: conversation response: hola verification_status: ok",
    )
    assert r.candidates == []
    assert r.rejected[0]["reason"] == "autorreferencial_o_transcripcion"


def test_no_aprende_de_lenguaje_especulativo(producer) -> None:
    r = producer.produce(
        run_id="r1", role="user", message="Creo que quizás el puerto sea el 8010."
    )
    assert r.candidates == []
    assert r.rejected[0]["reason"] == "especulativo"


def test_no_aprende_de_una_frase_sin_proposicion(producer) -> None:
    r = producer.produce(run_id="r1", role="user", message="hola, buenos días a todos")
    assert r.candidates == []
    assert r.rejected[0]["reason"] == "sin_proposicion_explicita"


def test_una_correccion_sin_valor_nuevo_no_cuenta(producer) -> None:
    r = producer.produce(run_id="r1", role="user", message="eso está mal")
    assert r.candidates == []


def test_no_aprende_de_un_texto_larguisimo(producer) -> None:
    r = producer.produce(run_id="r1", role="user", message="El puerto es 8010. " * 60)
    assert r.candidates == []
    assert r.rejected[0]["reason"] == "demasiado_largo"


# ── persistencia ──────────────────────────────────────────────────────


def test_persiste_por_la_cola_existente_sin_crear_otra(producer, db: Path) -> None:
    r = producer.produce(
        run_id="r1",
        role="user",
        message="Para los informes, usa primero el veredicto y después la evidencia.",
    )
    assert producer.persist(r.candidates[0]) is True

    conn = sqlite3.connect(db)
    fila = conn.execute(
        "SELECT source_type, source_ref, status, verification_notes FROM learning_queue"
    ).fetchone()
    conn.close()
    assert fila[0] == "experience"
    assert fila[1] == "run:r1"
    assert fila[2] == "internally_checked"
    assert PRODUCER_VERSION in fila[3]


def test_persistir_dos_veces_el_mismo_contenido_es_idempotente(
    producer, db: Path
) -> None:
    mensaje = "Para los informes, usa primero el veredicto y después la evidencia."
    a = producer.produce(run_id="r1", role="user", message=mensaje).candidates[0]
    b = producer.produce(run_id="r2", role="user", message=mensaje).candidates[0]
    assert producer.persist(a) is True
    assert producer.persist(b) is False

    conn = sqlite3.connect(db)
    n = conn.execute("SELECT count(*) FROM learning_queue").fetchone()[0]
    conn.close()
    assert n == 1


def test_cada_candidato_lleva_hash_y_version_del_productor(producer) -> None:
    c = producer.produce(
        run_id="r1", role="user", message="El puerto de Tríade es 8010."
    ).candidates[0]
    assert len(c.content_hash) == 64
    assert c.producer_version == PRODUCER_VERSION
    assert 0.0 < c.explicitness_score <= 1.0


@pytest.mark.parametrize(
    "mensaje",
    [
        "Para los informes, empieza siempre con la etiqueta VEREDICTO-TRIADE.",
        "Siempre usa el prefijo WRK:: al reportar un worker.",
        "A partir de ahora ordena el informe por severidad.",
        "Nunca incluyas el volcado completo en el resumen.",
    ],
)
def test_reconoce_las_formas_normales_de_declarar_una_preferencia(
    producer, mensaje: str
) -> None:
    """La primera versión sólo conocía `siempre usa/pon/escribe`.

    Una preferencia real se dice de muchas maneras; si el productor sólo
    entiende una, el usuario declara algo y Tríade no lo recoge.
    """
    r = producer.produce(run_id="r1", role="user", message=mensaje)
    assert len(r.candidates) == 1, r.rejected
    assert r.candidates[0].type == "preference"
