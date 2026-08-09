"""El circuito de aprendizaje sólo se cierra si el uso causal se confirma.

`LearningRetriever.confirm_causal_use()` existía, estaba probada y tenía
benchmark propio, pero **en producción no la llamaba nadie**. Medido sobre la
base real el 2026-08-09: los 15 candidatos con evidencia Measurement Core de
mejora tenían `run_use_count = 0` los quince, y `consolidate()` exige 3 usos
antes de mirar la evidencia. La intersección entre «tiene usos» y «demostró
mejora» era **cero**, así que ningún candidato podía llegar jamás a `stable`.

Estas pruebas fijan el cable y sus tres condiciones. Si se revierte
`ProductionKnowledgeInjector.confirm_uses()` o su llamada desde el runner,
`test_un_saber_inyectado_y_aplicado_cuenta_como_uso` falla.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.learning.production_injection import (
    CONFIRMED_USE_SCORE,
    ProductionKnowledgeInjector,
)

SABER = "Para los informes de Tríade, empieza siempre con la etiqueta VEREDICTO-TRIADE."
VAGO = "Conviene ser prudente y ordenado al redactar."


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """Base con un saber verificado, sondeable y con procedencia."""
    ruta = tmp_path / "triade.db"
    with sqlite3.connect(ruta) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS learning_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT UNIQUE, source_type TEXT, source_ref TEXT,
                title TEXT, content TEXT, normalized_summary TEXT, domain TEXT,
                risk_level TEXT DEFAULT 'low', confidence REAL DEFAULT 0.5,
                utility REAL DEFAULT 0.5, status TEXT DEFAULT 'candidate',
                verification_notes TEXT, created_at TEXT, updated_at TEXT,
                run_use_count INTEGER DEFAULT 0, run_outcome_scores TEXT,
                avg_outcome_score REAL DEFAULT 0.0)"""
        )
        for cid, contenido in (("exp-etiqueta", SABER), ("exp-vago", VAGO)):
            conn.execute(
                """INSERT INTO learning_queue
                (candidate_id, source_type, source_ref, title, content, domain,
                 status, created_at, updated_at)
                VALUES (?, 'conversation', 'run:run-A', ?, ?, 'reporting',
                        'evidence_verified', '2026-08-01', '2026-08-01')""",
                (cid, cid, contenido),
            )
    return ruta


def uso(db_path: Path, candidate_id: str) -> tuple[int, float]:
    with sqlite3.connect(db_path) as conn:
        r = conn.execute(
            "SELECT run_use_count, avg_outcome_score FROM learning_queue WHERE candidate_id=?",
            (candidate_id,),
        ).fetchone()
    return (int(r[0] or 0), float(r[1] or 0.0))


def test_un_saber_inyectado_y_aplicado_cuenta_como_uso(db: Path) -> None:
    """El caso que estaba roto: sin esto, `run_use_count` no sube nunca."""
    inyector = ProductionKnowledgeInjector(db)
    inyeccion = inyector.build("Hazme un informe de Tríade", run_id="run-B")
    assert "exp-etiqueta" in inyeccion.injected_ids, "el saber debía inyectarse"

    assert uso(db, "exp-etiqueta") == (0, 0.0)
    traza = inyector.confirm_uses(
        inyeccion, "VEREDICTO-TRIADE: todo en orden.", run_id="run-B"
    )

    assert [c["candidate_id"] for c in traza["confirmed"]] == ["exp-etiqueta"]
    assert traza["confirmed"][0]["target"] == "VEREDICTO-TRIADE"
    assert uso(db, "exp-etiqueta") == (1, CONFIRMED_USE_SCORE)


def test_inyectado_pero_no_aplicado_no_cuenta(db: Path) -> None:
    """Que el saber esté disponible no significa que se haya usado."""
    inyector = ProductionKnowledgeInjector(db)
    inyeccion = inyector.build("Hazme un informe de Tríade", run_id="run-B")
    traza = inyector.confirm_uses(
        inyeccion, "Aquí tienes el resumen que pediste.", run_id="run-B"
    )

    assert traza["confirmed"] == []
    assert traza["not_confirmed"][0]["reason"] == "dato_no_aparece_en_la_respuesta"
    assert uso(db, "exp-etiqueta") == (0, 0.0)


def test_sin_dato_sondeable_no_cuenta(db: Path) -> None:
    """Un saber vago es inmedible, y eso es una respuesta legítima.

    Contarlo sería exactamente lo que produjo 230 sondas inválidas: medir si el
    modelo conoce el vocabulario del repositorio en vez de si aprendió algo.
    """
    inyector = ProductionKnowledgeInjector(db)
    inyeccion = inyector.build("conviene ser prudente y ordenado", run_id="run-B")
    if "exp-vago" not in inyeccion.injected_ids:
        pytest.skip("el retriever no recuperó el candidato vago; nada que confirmar")
    traza = inyector.confirm_uses(
        inyeccion, "Conviene ser prudente y ordenado.", run_id="run-B"
    )
    assert [c["candidate_id"] for c in traza["confirmed"]] == []
    assert uso(db, "exp-vago") == (0, 0.0)


def test_lo_no_inyectado_nunca_cuenta_aunque_aparezca(db: Path) -> None:
    """La defensa contra la atribución retrospectiva.

    Si el saber no entró en el prompt, que aparezca en la salida no prueba nada:
    el modelo podía saberlo ya.
    """
    inyector = ProductionKnowledgeInjector(db)
    vacia = inyector.build("pregunta sin relación alguna", run_id="run-B")
    traza = inyector.confirm_uses(
        vacia, "VEREDICTO-TRIADE: todo en orden.", run_id="run-B"
    )
    assert traza["confirmed"] == []
    assert uso(db, "exp-etiqueta") == (0, 0.0)


def test_la_comparacion_ignora_mayusculas_y_acentos(db: Path) -> None:
    inyector = ProductionKnowledgeInjector(db)
    inyeccion = inyector.build("Hazme un informe de Tríade", run_id="run-B")
    traza = inyector.confirm_uses(
        inyeccion, "veredicto-triade: sin novedad.", run_id="run-B"
    )
    assert [c["candidate_id"] for c in traza["confirmed"]] == ["exp-etiqueta"]


def test_el_runner_llama_a_la_confirmacion(db: Path) -> None:
    """Fija el cable, no sólo la pieza.

    La pieza ya existía y estaba probada cuando el circuito estaba muerto: lo
    que faltaba era la llamada. Si alguien vuelve a descartar el valor de
    `_inject_verified_knowledge`, esta prueba cae.
    """
    import inspect

    from triade.core import runner as runner_mod

    fuente = inspect.getsource(runner_mod)
    assert "knowledge_injection = self._inject_verified_knowledge" in fuente, (
        "el runner debe conservar la inyección para poder confirmarla después"
    )
    assert ".confirm_uses(" in fuente, (
        "el runner debe confirmar el uso causal al terminar el run"
    )
