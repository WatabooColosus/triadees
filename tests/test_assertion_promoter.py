"""El hijo destilado: qué se escribe, qué no, y que el padre no se toca.

Medido el 2026-08-26 sobre la base real: 149 candidatos elegibles, 0 medibles,
`learning_evidence_generation` parada desde el 12 de agosto. Estos tests fijan
el comportamiento de la reparación.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.learning.assertion_promoter import AssertionPromoter
from triade.learning.knowledge_probe import build_probe, extract_target

# Fuente enciclopédica real: nombre propio capitalizado y recurrente.
FUENTE_WEB = (
    "El Cuarteto de Nos es una banda de rock uruguaya formada en Montevideo. "
    "El Cuarteto de Nos ha publicado numerosos discos a lo largo de su "
    "carrera, y la crítica considera al Cuarteto de Nos muy influyente."
)

# Transcripción de un run: salida del propio modelo, no fuente factual.
TRANSCRIPCION = (
    "run_id: run-20260728-234411-c6b24598\n"
    "source: react-ui\n"
    "intent: conversation\n"
    "input: hola como estas\n"
    "response: No siento como una persona, pero estoy operando.\n"
    "verification_status: ok"
)


def _seed(db: Path, filas: list[dict]) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS learning_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT UNIQUE, source_type TEXT, source_ref TEXT,
            title TEXT, content TEXT, normalized_summary TEXT, domain TEXT,
            risk_level TEXT, confidence REAL, utility REAL, status TEXT,
            verification_notes TEXT, created_at TEXT, updated_at TEXT,
            run_use_count INTEGER DEFAULT 0, run_outcome_scores TEXT,
            avg_outcome_score REAL DEFAULT 0)"""
    )
    for f in filas:
        conn.execute(
            "INSERT INTO learning_queue (candidate_id, source_type, source_ref,"
            " content, normalized_summary, status, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                f["candidate_id"],
                f.get("source_type", "web"),
                f.get("source_ref", "url:https://ejemplo/x"),
                f["content"],
                f["content"],
                f.get("status", "internally_checked"),
                "2026-08-20T00:00:00+00:00",
            ),
        )
    conn.commit()
    conn.close()


def _rows(db: Path, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute(sql, args))
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "triade.db"


def test_una_fuente_web_produce_un_hijo_sondeable(db: Path) -> None:
    """El desbloqueo entero: de un padre inmedible sale una sonda."""
    _seed(db, [{"candidate_id": "web-1", "content": FUENTE_WEB}])
    assert extract_target(FUENTE_WEB) is None, "el padre no era medible"

    reporte = AssertionPromoter(db).run()

    assert reporte.written == 1
    hijo = reporte.written_ids[0]
    sonda = build_probe(db, hijo)
    assert sonda is not None
    assert sonda.expected == "cuarteto_de_nos"
    # La pregunta no puede llevar la respuesta dentro, o el control acierta solo.
    assert "cuarteto_de_nos" not in sonda.question


def test_el_padre_no_se_toca(db: Path) -> None:
    """La transcripción cruda es la fuente: machacarla haría irrepetible la auditoría."""
    _seed(db, [{"candidate_id": "web-1", "content": FUENTE_WEB}])
    AssertionPromoter(db).run()

    padre = _rows(
        db, "SELECT content, status FROM learning_queue WHERE candidate_id='web-1'"
    )
    assert padre[0]["content"] == FUENTE_WEB
    assert padre[0]["status"] == "internally_checked"


def test_el_hijo_apunta_al_padre(db: Path) -> None:
    """Sin `source_ref` no se puede descartar una destilación mala sin perder la fuente."""
    _seed(db, [{"candidate_id": "web-1", "content": FUENTE_WEB}])
    hijo_id = AssertionPromoter(db).run().written_ids[0]

    hijo = _rows(
        db,
        "SELECT source_type, source_ref, status FROM learning_queue WHERE candidate_id=?",
        (hijo_id,),
    )[0]
    assert hijo["source_type"] == "distilled"
    assert hijo["source_ref"] == "candidate:web-1"
    # Hereda la verificación del padre, no se salta el gate de evidencia.
    assert hijo["status"] == "internally_checked"


def test_correr_dos_veces_no_duplica(db: Path) -> None:
    """La tarea corre en bucle: sin idempotencia llenaría la cola de copias."""
    _seed(db, [{"candidate_id": "web-1", "content": FUENTE_WEB}])

    primera = AssertionPromoter(db).run()
    segunda = AssertionPromoter(db).run()
    tercera = AssertionPromoter(db).run()

    assert primera.written == 1
    assert segunda.written == 0
    assert tercera.written == 0
    total = _rows(
        db, "SELECT COUNT(*) c FROM learning_queue WHERE source_type='distilled'"
    )
    assert total[0]["c"] == 1


def test_una_transcripcion_no_se_destila(db: Path) -> None:
    """Medir que el modelo repite lo que dijo demuestra memoria, no verdad.

    Las 60 conversacionales elegibles del 26-ago son exactamente esto. Se
    excluyen por `source_type`, antes incluso de mirar el texto.
    """
    _seed(
        db,
        [
            {
                "candidate_id": "conv-1",
                "source_type": "conversation",
                "content": TRANSCRIPCION,
            }
        ],
    )
    reporte = AssertionPromoter(db).run()

    assert reporte.inspected == 0, "ni se mira: no es fuente destilable"
    assert reporte.written == 0


def test_un_padre_ya_sondeable_no_recibe_hijo(db: Path) -> None:
    """Duplicarlo gastaría una medición en decir dos veces lo mismo."""
    _seed(
        db,
        [
            {
                "candidate_id": "web-1",
                "content": "el flujo usa payload_hash para deduplicar",
            }
        ],
    )
    reporte = AssertionPromoter(db).run()

    assert reporte.skipped_already_probeable == 1
    assert reporte.written == 0


def test_una_fuente_sin_sujeto_no_produce_nada(db: Path) -> None:
    """`no_op` es el resultado correcto y el más frecuente.

    Sin la verja, `muy notable` daría un cloze irresoluble para el control y
    trivial para el tratamiento —que lee la memoria inyectada—: un `improved`
    fabricado.
    """
    _seed(
        db,
        [
            {
                "candidate_id": "web-1",
                "content": (
                    "Lo que ocurre después supone un cambio muy notable es un "
                    "cambio de actitud o de ideas ante la realidad."
                ),
            }
        ],
    )
    reporte = AssertionPromoter(db).run()

    assert reporte.inspected == 1
    assert reporte.skipped_no_assertion == 1
    assert reporte.written == 0


def test_un_padre_esteril_solo_se_inspecciona_una_vez(db: Path) -> None:
    """Sin registrar el intento, la tarea gira en vacío para siempre.

    De 46 padres `web` reales sólo 6 dieron aserción el 2026-08-26. Los otros 40
    volverían a contarse como «sin destilar» en cada ciclo del planificador, y
    la tarea correría eternamente devolviendo `no_op` — justo lo que hace
    parecer vivo un panel muerto.
    """
    _seed(
        db,
        [
            {
                "candidate_id": "web-esteril",
                "content": (
                    "Lo que ocurre después supone un cambio muy notable es un "
                    "cambio de actitud o de ideas ante la realidad."
                ),
            }
        ],
    )

    primera = AssertionPromoter(db).run()
    segunda = AssertionPromoter(db).run()

    assert primera.inspected == 1
    assert primera.skipped_no_assertion == 1
    assert segunda.inspected == 0, "ya se intentó: no se vuelve a mirar"

    intento = _rows(
        db,
        "SELECT outcome, promoter_version FROM learning_distillation_attempts"
        " WHERE candidate_id='web-esteril'",
    )
    assert intento[0]["outcome"] == "no_assertion"


def test_subir_la_version_reabre_los_descartados(db: Path) -> None:
    """Al mejorar el destilador hay que poder reintentar sin borrar a mano."""
    from triade.learning import assertion_promoter as modulo

    _seed(
        db,
        [
            {
                "candidate_id": "web-esteril",
                "content": "Un texto cualquiera sin sujeto nombrable ni definición.",
            }
        ],
    )
    assert AssertionPromoter(db).run().inspected == 1
    assert AssertionPromoter(db).run().inspected == 0

    original = modulo.PROMOTER_VERSION
    try:
        modulo.PROMOTER_VERSION = "assertion-promoter-9.9.9"
        assert AssertionPromoter(db).run().inspected == 1, "otra versión, otro intento"
    finally:
        modulo.PROMOTER_VERSION = original
