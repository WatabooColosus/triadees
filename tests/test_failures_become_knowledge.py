"""F-018: los errores y los gates bajos generan conocimiento.

Aprobado por el operador el 2026-08-03. Antes de esto un fallo se escribía en
`worker_events` y ahí moría: el sistema volvía a equivocarse igual porque nada
de lo ocurrido sobrevivía al evento.

La aprobación tiene un límite que estas pruebas fijan: el conocimiento entra
como `candidate`, nunca como evidencia. Sólo `evidence_verified` y `stable`
llegan al prompt de una conversación, así que un error se acumula hacia el
umbral sin convertirse en doctrina por el mero hecho de haber ocurrido.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.learning.production_injection import PRODUCTION_STATES
from triade.workers.contracts import WorkerTask
from triade.workers.worker_loop import _STATUSES_WORTH_LEARNING


def _db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def test_only_failures_and_low_gates_are_worth_learning() -> None:
    """Un `completed` no enseña nada; un fallo o un bloqueo sí."""
    assert "failed" in _STATUSES_WORTH_LEARNING
    assert "timeout" in _STATUSES_WORTH_LEARNING
    assert "dead_letter" in _STATUSES_WORTH_LEARNING
    assert "blocked" in _STATUSES_WORTH_LEARNING
    assert "completed" not in _STATUSES_WORTH_LEARNING
    assert "observed" not in _STATUSES_WORTH_LEARNING
    # `skipped` es trámite, no incidente: aprender de él llenaría la cola.
    assert "skipped" not in _STATUSES_WORTH_LEARNING


def test_failure_becomes_a_candidate_never_evidence(tmp_path: Path) -> None:
    """El límite de la aprobación: candidato sí, evidencia no."""
    from triade.workers.worker_loop import WorkerLoop

    db_path = _db(tmp_path)
    loop = WorkerLoop.__new__(WorkerLoop)
    loop.db_path = str(db_path)
    loop.runs_dir = tmp_path / "runs"

    published = loop._learn_from_failure(
        "worker-test",
        WorkerTask(task_type="goal_lora_train"),
        "dead_letter",
        {"error": "el adaptador no superó el gate de regresión"},
    )

    assert published and published.get("published") is True
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM learning_queue")]
    assert rows, "el fallo debe dejar un candidato de aprendizaje"
    for row in rows:
        assert row["status"] not in PRODUCTION_STATES, (
            "un fallo recién ocurrido no puede influir en una respuesta"
        )
    # La causa viaja con el candidato: sin ella no se puede evaluar después.
    assert any("gate de regresión" in str(r.get("content") or "") for r in rows)


def test_a_completed_task_leaves_no_candidate(tmp_path: Path) -> None:
    """Aprender de todo llenaría la cola de ruido y ahogaría lo que importa."""
    from triade.workers.worker_loop import WorkerLoop

    db_path = _db(tmp_path)
    loop = WorkerLoop.__new__(WorkerLoop)
    loop.db_path = str(db_path)
    loop.runs_dir = tmp_path / "runs"

    assert "completed" not in _STATUSES_WORTH_LEARNING
    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM learning_queue").fetchone()[0]
    assert before == 0
