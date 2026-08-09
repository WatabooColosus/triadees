"""Ningún escritor vivo puede dejar filas sin padre.

`PRAGMA integrity_check` decía `ok` mientras `PRAGMA foreign_key_check` sacaba
10.562 violaciones: son preguntas distintas y la primera no cubre a la segunda.
Pasaban desapercibidas porque `PRAGMA foreign_keys` está en 0 —SQLite no fuerza
las claves foráneas salvo que se activen por conexión—, así que las huérfanas se
escribían en silencio.

Estas pruebas ejecutan los tres caminos que las producían y exigen cero
huérfanas. No comprueban un contador: activan la comprobación real de SQLite.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

MIGRACION = Path("triade/memory/migrations/032_metabolic_core.sql")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """Base limpia con el esquema metabólico y `runs`/`model_events`."""
    ruta = tmp_path / "triade.db"
    with sqlite3.connect(ruta) as conn:
        conn.executescript(MIGRACION.read_text(encoding="utf-8"))
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
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
            CREATE TABLE IF NOT EXISTS model_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                role TEXT NOT NULL,
                provider TEXT NOT NULL,
                model_name TEXT NOT NULL,
                ok INTEGER DEFAULT 0,
                error TEXT,
                quality_score REAL DEFAULT 0.0,
                latency_ms INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            );
            """
        )
    return ruta


def huerfanas(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("PRAGMA foreign_key_check").fetchall()


def test_la_base_de_pruebas_empieza_sin_huerfanas(db: Path) -> None:
    assert huerfanas(db) == []


def test_una_senal_fuera_de_ciclo_no_queda_huerfana(db: Path) -> None:
    """`cycle_id = 0` es el centinela del gobernador de workers.

    Era el caso real: 142 señales apuntando a un ciclo 0 que nadie declaró.
    """
    from triade.metabolism.signals import SignalBus

    bus = SignalBus(db_path=db)
    bus.emit(0, "worker_cycle_governor", "full_local_guarded", reason="hardware alto")
    bus.emit(0, "worker_cycle_governor", "cooldown", reason="load average alto")

    assert huerfanas(db) == []
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM metabolic_signals").fetchone()[0] == 2
        centinela = conn.execute(
            "SELECT status, mode FROM metabolic_cycle WHERE cycle_id=0"
        ).fetchone()
    assert centinela == ("out_of_cycle", "none")


def test_una_necesidad_descartada_deja_recibo_con_padre(db: Path) -> None:
    """El recibo de un descarte apuntaba a una necesidad nunca escrita.

    `_evaluate` registraba el recibo y hacía `continue`, así que la necesidad no
    llegaba a `_propose` —el único que la persistía—. 6.435 huérfanas.
    """
    from triade.metabolism.contracts import MetabolicNeed
    from triade.metabolism.needs import NeedsQueue
    from triade.metabolism.receipts import ReceiptLedger

    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO metabolic_cycle (cycle_id, started_at) VALUES (7, 'ahora')"
        )

    need = MetabolicNeed(need_id="need-descartada", kind="health_check", priority=10)
    NeedsQueue(db_path=db).persist_need(need, 7, status="skipped")
    ReceiptLedger(db_path=db).record(
        7, need.need_id, "evaluate", "skipped", error="on_cooldown"
    )

    assert huerfanas(db) == []


def test_la_necesidad_descartada_no_finge_estar_pendiente(db: Path) -> None:
    """Persistirla como `pending` la metería en una cola que nadie atiende."""
    from triade.metabolism.contracts import MetabolicNeed
    from triade.metabolism.needs import NeedsQueue

    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO metabolic_cycle (cycle_id, started_at) VALUES (7, 'ahora')"
        )

    cola = NeedsQueue(db_path=db)
    cola.persist_need(
        MetabolicNeed(need_id="need-viva", kind="health_check", priority=10), 7
    )
    cola.persist_need(
        MetabolicNeed(need_id="need-descartada", kind="health_check", priority=10),
        7,
        status="skipped",
    )

    pendientes = {n["need_id"] for n in cola.pending()}
    assert pendientes == {"need-viva"}


def test_el_ciclo_autonomo_da_padre_a_su_evento_de_modelo(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El supervisor escribía un `model_events` por vuelta sin fila en `runs`.

    Se ejecuta `_model_service` de verdad —es el camino que producía las 4.032
    huérfanas—, sólo con Ollama y el bus de eventos fuera de medio: lo que se
    prueba es la escritura, no de dónde salió el diagnóstico del modelo.
    """
    from triade.services import supervisor as sup

    monkeypatch.setattr(
        sup, "OllamaClient", lambda *a, **k: _OllamaFalso(), raising=True
    )
    monkeypatch.setattr(sup, "publish_event", lambda *a, **k: None, raising=True)

    supervisor = sup.InternalRuntimeSupervisor(
        db_path=db, runs_dir=tmp_path / "runs", mode="observe_only"
    )
    for _ in range(3):
        supervisor._model_service("observe_only")

    assert huerfanas(db) == []
    with sqlite3.connect(db) as conn:
        # Una sola fila padre para las tres vueltas: el `OR IGNORE` hace su parte.
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM model_events").fetchone()[0] == 3
        origen, estado = conn.execute(
            "SELECT source, status FROM runs WHERE run_id=?", (supervisor.runtime_id,)
        ).fetchone()
    assert origen == "runtime"
    assert estado == "running"


class _OllamaFalso:
    """Ollama sano sin red: el test mide la escritura, no la inferencia."""

    def health(self) -> dict:
        return {"ok": True, "models": ["qwen2.5:3b-instruct"]}
