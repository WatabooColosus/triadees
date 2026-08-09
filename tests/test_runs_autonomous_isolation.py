"""Los ciclos autónomos viven en `runs` pero no son conversaciones.

Desde el 2026-08-09 la tabla `runs` tiene filas con `source='runtime'`: existen
para dar padre a los `model_events` del supervisor, que si no quedaban huérfanos
de su clave foránea. No hubo nadie al otro lado, no tienen directorio en `runs/`
ni episodio, señal o cristal.

Cuatro lectores usaban `ORDER BY id DESC` como atajo de "lo más reciente". El
atajo dejó de valer el mismo día: se reconstruyeron 719 filas de julio y, por
AUTOINCREMENT, se llevaron los ids más altos de la tabla. Las filas más viejas
pasaron a parecer las más nuevas.

Estas pruebas fijan las dos correcciones: filtrar lo autónomo y ordenar por
tiempo real.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

ESQUEMA = """
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    source TEXT DEFAULT 'console',
    user_input TEXT NOT NULL,
    status TEXT DEFAULT 'created',
    model_hypothalamus TEXT,
    model_central TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);
CREATE TABLE episodic_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, title TEXT,
    content TEXT, summary TEXT, tags TEXT, importance REAL,
    confidence REAL, created_at TEXT
);
CREATE TABLE signal_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, intent TEXT
);
CREATE TABLE crystal_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT,
    q_crystal REAL, stability REAL
);
"""


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """Una conversación real vieja y un ciclo autónomo reconstruido, nuevo de id.

    Reproduce exactamente la trampa: la fila autónoma tiene el `id` más alto
    —como las 719 del backfill— pero el `created_at` más antiguo.
    """
    ruta = tmp_path / "triade.db"
    with sqlite3.connect(ruta) as conn:
        conn.executescript(ESQUEMA)
        conn.execute(
            """INSERT INTO runs (run_id, source, user_input, status, created_at)
            VALUES ('run-real', 'react-ui', 'quiero hablar de neuronas', 'ok',
                    '2026-08-09T18:00:00+00:00')"""
        )
        conn.execute(
            "INSERT INTO episodic_memory (run_id, content) VALUES ('run-real', 'algo')"
        )
        # id más alto, fecha más antigua: la fila reconstruida.
        conn.execute(
            """INSERT INTO runs (run_id, source, user_input, status, created_at)
            VALUES ('runtime-viejo', 'runtime', 'ciclo autónomo del supervisor',
                    'closed', '2026-07-28T23:32:26+00:00')"""
        )
    return ruta


def test_la_novedad_no_se_mide_contra_ciclos_autonomos(db: Path) -> None:
    """Se le pasa al motor un texto calcado del ciclo autónomo.

    Si la fila `runtime` entrara en la comparación, el solapamiento sería total
    y la novedad se hundiría. Excluida, no hay nada parecido que comparar y la
    entrada resulta completamente nueva.
    """
    from triade.consciousness.salience import SalienceEngine

    novedad = SalienceEngine(db_path=db)._novelty_salience(
        "ciclo autónomo del supervisor"
    )
    assert novedad == 1.0


def test_el_ultimo_run_es_el_ultimo_real(db: Path) -> None:
    from triade.core.observability_view import TriadeObservabilityView

    vista = TriadeObservabilityView(db_path=db)
    ultimo = vista._last_run()
    assert ultimo is not None
    assert ultimo["run_id"] == "run-real", (
        "el 'último run' no puede ser un ciclo autónomo con id alto y fecha vieja"
    )


def test_la_continuidad_semantica_ignora_los_ciclos(db: Path) -> None:
    from triade.memory.semantic_continuity import SemanticContinuity

    filas = SemanticContinuity(db)._recent_runs(10)
    assert [f["run_id"] for f in filas] == ["run-real"]


def test_el_analizador_excluye_los_ciclos_salvo_que_se_pidan(db: Path) -> None:
    from triade.core.conversation_analyzer import ConversationAnalyzer

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        sin_filtro = ConversationAnalyzer._fetch_runs(conn, 10, None, None)
        pedidos = ConversationAnalyzer._fetch_runs(conn, 10, None, "runtime")

    assert [f["run_id"] for f in sin_filtro] == ["run-real"]
    # Quien los pide explícitamente sí los recibe: no se ocultan, se separan.
    assert [f["run_id"] for f in pedidos] == ["runtime-viejo"]


def test_ordenar_por_id_habria_dado_la_respuesta_contraria(db: Path) -> None:
    """Deja constancia de por qué el atajo dejó de valer."""
    with sqlite3.connect(db) as conn:
        por_id = conn.execute("SELECT run_id FROM runs ORDER BY id DESC").fetchall()
        por_fecha = conn.execute(
            "SELECT run_id FROM runs ORDER BY created_at DESC"
        ).fetchall()
    assert por_id[0][0] == "runtime-viejo"
    assert por_fecha[0][0] == "run-real"
