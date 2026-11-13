"""`/api/learning/tasks` debe decir la verdad sobre su ventana y su efecto.

Auditoría 2026-08-02. El endpoint tenía dos afirmaciones falsas a la vez:

1. Los campos `*_24h` se calculaban con `SELECT ... FROM autonomous_tasks GROUP
   BY task_type, status`, **sin filtro temporal**. Eran totales de por vida con
   nombre de ventana. Medido en producción: `pending_learning_review` reportaba
   `scheduled_24h = 205` cuando en 24 h reales habían corrido 40.

2. `last_effect` no salía del efecto de la tarea, sino de un contador global de
   por vida: `if resumen.evidence_verified == 0 and resumen.stable == 0`. Con un
   único saber verificado —creado el 2026-08-01 por un script— **todos** los
   tipos quedaban etiquetados `produced_knowledge` para siempre, aunque en la
   ventana no hubieran producido nada. El panel reportaba `produced_knowledge`
   junto a `learned_today: 0`.

Lo segundo contradice el propio docstring del endpoint: "una tarea que corre y
no cambia nada se marca `alive_but_no_effect`; contarla como éxito es lo que
hace que un panel parezca vivo mientras no ocurre nada".
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TIPO = "pending_learning_review"


def _iso(delta_hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=delta_hours)).isoformat()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE learning_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT UNIQUE,
            source_type TEXT, source_ref TEXT, title TEXT, content TEXT,
            normalized_summary TEXT, domain TEXT, risk_level TEXT, confidence REAL,
            utility REAL, status TEXT, verification_notes TEXT, created_at TEXT,
            updated_at TEXT, run_use_count INTEGER DEFAULT 0,
            run_outcome_scores TEXT, avg_outcome_score REAL DEFAULT 0)"""
    )
    conn.execute(
        """CREATE TABLE autonomous_tasks (
            task_id TEXT PRIMARY KEY, task_type TEXT, status TEXT,
            created_at TEXT, updated_at TEXT)"""
    )
    # Un saber verificado de hace mucho: es el que volvía "productivas" a todas
    # las tareas para siempre.
    conn.execute(
        "INSERT INTO learning_queue (candidate_id, title, content, status, source_ref,"
        " created_at, updated_at) VALUES ('viejo','T','c','evidence_verified','run:o',?,?)",
        (_iso(72), _iso(72)),
    )
    # 2 ejecuciones dentro de la ventana, 5 fuera de ella.
    filas = [(f"t-in-{i}", TIPO, "completed", _iso(2)) for i in range(2)]
    filas += [(f"t-out-{i}", TIPO, "completed", _iso(50)) for i in range(5)]
    conn.executemany(
        "INSERT INTO autonomous_tasks (task_id,task_type,status,created_at,updated_at)"
        " VALUES (?,?,?,?,?)",
        [(a, b, c, d, d) for a, b, c, d in filas],
    )
    conn.commit()
    conn.close()

    import apps.routes.knowledge as mod

    monkeypatch.setattr(mod, "DB_PATH", str(db))
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app)


def _fila(client: TestClient, tipo: str = TIPO) -> dict:
    payload = client.get("/api/learning/tasks").json()
    return next(t for t in payload["tasks"] if t["task_type"] == tipo)


class TestVentanaDeclarada:
    def test_scheduled_24h_solo_cuenta_las_ultimas_24h(
        self, client: TestClient
    ) -> None:
        """Un campo que se llama `_24h` no puede contener el histórico entero."""
        fila = _fila(client)
        assert fila["scheduled_24h"] == 2, (
            "el campo `scheduled_24h` incluyó ejecuciones de hace 50 horas: "
            "es un total de por vida con nombre de ventana"
        )

    def test_completed_24h_respeta_la_ventana(self, client: TestClient) -> None:
        assert _fila(client)["completed_24h"] == 2

    def test_el_corte_usa_el_formato_que_se_almacena(self, client: TestClient) -> None:
        """El corte debe ser ISO con `T`, como lo que guardan las tablas.

        Trampa real, encontrada al verificar esta misma corrección:
        `datetime('now','-1 day')` de SQLite devuelve `2026-08-01 03:55:12` (con
        espacio) mientras `updated_at` guarda `2026-08-01T03:55:12.027832+00:00`
        (con `T`). Como `'T' > ' '` en comparación lexicográfica, ese corte deja
        pasar filas **del mismo día natural pero anteriores al corte**.

        Este caso es el único que lo detecta: una fila de hace 30 h cae en el día
        anterior y se excluye bien con cualquiera de los dos formatos. Una de
        hace 25 h, no.
        """
        import apps.routes.knowledge as mod

        with sqlite3.connect(mod.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO autonomous_tasks (task_id,task_type,status,created_at,"
                "updated_at) VALUES ('t-borde',?,'completed',?,?)",
                (TIPO, _iso(25), _iso(25)),
            )
            conn.commit()

        assert _fila(client)["scheduled_24h"] == 2, (
            "una ejecución de hace 25 h entró en la ventana de 24 h: el corte "
            "no está en el mismo formato que la columna que compara"
        )


class TestEfectoDeclarado:
    def test_sin_saber_nuevo_en_la_ventana_no_es_produced_knowledge(
        self, client: TestClient
    ) -> None:
        """Un saber de hace 72 h no vuelve productiva a la tarea de hoy."""
        fila = _fila(client)
        assert fila["last_effect"] == "alive_but_no_effect", (
            f"la tarea corrió sin producir saber en la ventana y se reportó "
            f"{fila['last_effect']!r}"
        )
        assert fila["reason"]

    def test_saber_nuevo_en_la_ventana_si_es_produced_knowledge(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """No es pesimismo fijo: con efecto real dentro de la ventana, lo dice."""
        import apps.routes.knowledge as mod

        with sqlite3.connect(mod.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO learning_queue (candidate_id,title,content,status,"
                "source_ref,created_at,updated_at) VALUES "
                "('nuevo','T','c','evidence_verified','run:o',?,?)",
                (_iso(1), _iso(1)),
            )
            conn.commit()

        assert _fila(client)["last_effect"] == "produced_knowledge"

    def test_tipo_sin_ejecuciones_en_la_ventana_es_never_scheduled(
        self, client: TestClient
    ) -> None:
        """Nunca programada en la ventana no puede confundirse con productiva."""
        fila = _fila(client, "stable_consolidation_review")
        assert fila["scheduled_24h"] == 0
        assert fila["last_effect"] == "never_scheduled"
