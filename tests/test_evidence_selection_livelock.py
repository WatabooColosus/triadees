"""El planner elegía un candidato inmedible y lo reintentaba para siempre.

F-037, medido el 2026-08-03 sobre la base viva: de los 665 candidatos
`internally_checked`, el filtro `source_type='experience'` dejaba **uno**
elegible, y ese uno no era medible. Como el handler salía sin escribir en
`learning_evidence`, el `NOT EXISTS` de la consulta seguía siendo cierto y el
planner volvía a elegirlo: 400 de las 400 últimas tareas sobre el mismo
`candidate_id`, y 465 eventos diciendo `sin_prueba_objetiva`. Mientras tanto 420
candidatos medibles esperaban fuera del filtro.

Estas pruebas fijan las dos mitades del arreglo: elegir por medibilidad, y dejar
constancia del intento para que ningún candidato pueda volver a bloquear la cola.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.learning.evidence_bridge import LearningEvidenceBridge
from triade.workers.mission_planner import MissionPlanner

#: Contenido con un token distintivo: `build_probe` sabe preguntarlo.
MEDIBLE = "El worker de evidencia se identifica con worker_evidence_tag"
#: Prosa sin ningún dato comprobable: no hay experimento posible.
INMEDIBLE = "conviene ser prudente y revisar todo con calma antes de decidir"


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def add_candidate(
    db_path: Path, candidate_id: str, content: str, source_type: str = "tool"
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO learning_queue
            (candidate_id, title, content, status, source_type, confidence)
            VALUES (?, ?, ?, 'internally_checked', ?, 0.9)""",
            (candidate_id, f"t-{candidate_id}", content, source_type),
        )


def evidence_tasks(db_path: Path) -> list[str]:
    planner = MissionPlanner(db_path=db_path)
    return [
        str(t.payload.get("candidate_id"))
        for t in planner.plan_cycle()
        if t.task_type == "learning_evidence_generation"
    ]


def test_no_elige_un_candidato_sin_dato_comprobable(tmp_path: Path) -> None:
    """Elegirlo costaba un ciclo entero para volver a decir que no se puede."""
    db = make_db(tmp_path)
    add_candidate(db, "learn-inmedible", INMEDIBLE)

    assert evidence_tasks(db) == []


def test_salta_los_inmedibles_y_elige_el_medible(tmp_path: Path) -> None:
    """El inmedible es el más reciente: antes bloqueaba a todos los demás."""
    db = make_db(tmp_path)
    add_candidate(db, "learn-viejo-medible", MEDIBLE)
    add_candidate(db, "learn-nuevo-inmedible", INMEDIBLE)

    assert evidence_tasks(db) == ["learn-viejo-medible"]


def test_el_source_type_ya_no_excluye_al_99_por_ciento(tmp_path: Path) -> None:
    """`experience` era 1 de 665. Los otros no eran menos aprendizaje."""
    db = make_db(tmp_path)
    for source in ("tool", "conversation", "qualia_bus", "web"):
        add_candidate(db, f"learn-{source}", MEDIBLE, source_type=source)

    elegidos = evidence_tasks(db)
    assert len(elegidos) == 1, "sigue siendo un candidato por ciclo"
    assert elegidos[0].startswith("learn-")


def test_un_candidato_con_evidencia_ya_no_se_reelige(tmp_path: Path) -> None:
    """Es la salida del bucle: haber intentado tiene que dejar rastro."""
    db = make_db(tmp_path)
    add_candidate(db, "learn-intentado", MEDIBLE)
    assert evidence_tasks(db) == ["learn-intentado"]

    LearningEvidenceBridge(db_path=db).record_inconclusive(
        "learn-intentado",
        decision="blocked",
        reason="el filtro de recuperación lo retiene",
    )

    assert evidence_tasks(db) == [], "un intento registrado no se repite"


def test_el_veredicto_registrado_no_puede_promocionar(tmp_path: Path) -> None:
    """Dejar constancia no puede convertirse en dar por buena una mejora."""
    db = make_db(tmp_path)
    add_candidate(db, "learn-bloqueado", MEDIBLE)
    bridge = LearningEvidenceBridge(db_path=db)

    fila = bridge.record_inconclusive(
        "learn-bloqueado", decision="not_measurable", reason="sin dato distintivo"
    )
    assert fila["decision"] == "not_measurable"

    with pytest.raises(ValueError, match="no demuestra mejora"):
        bridge.require_improvement("learn-bloqueado")


def test_no_se_puede_declarar_improved_sin_comparacion(tmp_path: Path) -> None:
    """El atajo de registro no puede usarse para saltarse el experimento."""
    db = make_db(tmp_path)
    add_candidate(db, "learn-tramposo", MEDIBLE)

    with pytest.raises(ValueError, match="promocionable"):
        LearningEvidenceBridge(db_path=db).record_inconclusive(
            "learn-tramposo", decision="improved", reason="sin medir nada"
        )
