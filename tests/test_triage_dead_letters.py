"""La cola de muertos clasificada por si la causa sigue mordiendo.

Contar 181 no dice nada: puede ser una hemorragia abierta o la cicatriz de una
cerrada, y el número es idéntico. Lo que las separa es si el tipo que sangraba
vuelve a completar después de esa muerte.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.triage_dead_letters import triage

ESQUEMA = """
CREATE TABLE autonomous_tasks (
    task_id TEXT PRIMARY KEY, task_type TEXT, status TEXT, attempt INTEGER,
    max_attempts INTEGER, created_at TEXT, updated_at TEXT, last_error TEXT
)
"""


def _base(tmp_path: Path, filas: list[tuple[str, str, str, str, str | None]]) -> Path:
    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    with conn:
        conn.execute(ESQUEMA)
        for i, (tipo, estado, creada, actualizada, error) in enumerate(filas):
            conn.execute(
                "INSERT INTO autonomous_tasks VALUES(?,?,?,3,3,?,?,?)",
                (f"task-{i}", tipo, estado, creada, actualizada, error),
            )
    conn.close()
    return db


def test_a_type_that_completed_afterwards_is_a_scar_not_a_wound(
    tmp_path: Path,
) -> None:
    db = _base(
        tmp_path,
        [
            (
                "system_debt_scan",
                "dead_letter",
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:05:00+00:00",
                "expired_lease_attempts_exhausted",
            ),
            (
                "system_debt_scan",
                "completed",
                "2020-01-02T00:00:00+00:00",
                "2020-01-02T00:01:00+00:00",
                None,
            ),
        ],
    )

    informe = triage(db)

    assert informe["by_classification"] == {"superseded_periodic": 1}
    assert informe["retryable_total"] == 0
    assert informe["new_dead_letters_in_window"] == 0


def test_a_recent_death_with_no_recovery_is_an_active_bug(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    ahora = datetime.now(UTC).isoformat()
    db = _base(
        tmp_path,
        [("system_debt_scan", "dead_letter", ahora, ahora, "timeout:task_timeout")],
    )

    informe = triage(db)

    assert informe["by_classification"] == {"active_bug": 1}
    assert informe["retryable_total"] == 1
    assert informe["new_dead_letters_in_window"] == 1


def test_governance_refusals_are_not_counted_as_breakage(tmp_path: Path) -> None:
    """Cerrar una tarea que no pudo demostrar su efecto es el sistema acertando."""
    db = _base(
        tmp_path,
        [
            (
                "pulse_check",
                "dead_letter",
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:05:00+00:00",
                "recovery:no_artifact_found; uncertain_without_artifact:no_evidence",
            ),
            (
                "pulse_check",
                "completed",
                "2020-01-02T00:00:00+00:00",
                "2020-01-02T00:01:00+00:00",
                None,
            ),
        ],
    )

    informe = triage(db)

    assert informe["by_cause"] == {"uncertain_quarantined": 1}
    assert informe["by_classification"] == {"uncertain_quarantined": 1}
    assert informe["retryable_total"] == 0


def test_nothing_is_ever_deleted(tmp_path: Path) -> None:
    """El registro de lo que salió mal es la única prueba de que ocurrió."""
    db = _base(
        tmp_path,
        [
            (
                "system_debt_scan",
                "dead_letter",
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:05:00+00:00",
                "expired_lease_attempts_exhausted",
            )
        ],
    )

    triage(db)

    conn = sqlite3.connect(db)
    quedan = conn.execute(
        "SELECT COUNT(*) FROM autonomous_tasks WHERE status='dead_letter'"
    ).fetchone()[0]
    conn.close()
    assert quedan == 1
