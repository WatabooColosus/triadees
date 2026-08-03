"""La última etapa del aprendizaje: de `evidence_verified` a consolidación.

Auditoría del 2026-08-03 sobre la base viva. La cadena
`uso en runs → medición → consolidación` estaba cortada en tres sitios a la vez,
y cada corte bastaba por sí solo para dejar el resultado en cero:

1. El planner de evidencia ordenaba por `id DESC LIMIT 200`. Los 16 candidatos
   con uso real probado eran los ids 1..16 y caían en las posiciones 632..647:
   nunca entraban en la tanda. Resultado: los candidatos medidos y los usados
   eran poblaciones **disjuntas**, y ninguno tenía jamás los dos ejes.
2. `_plan_memory_consolidation` contaba `status = 'validated_in_runs'`, con cero
   filas desde siempre. La tarea no se encoló ni una vez.
3. `consolidate()` y `mark_used_in_run()` no aceptaban `evidence_verified`, que
   es donde termina hoy la medición. Seis candidatos quedaron ahí atrapados: ni
   sumaban usos ni podían consolidarse.

Ningún umbral se relaja: `MIN_RUN_USES` y `MIN_OUTCOME_SCORE` siguen decidiendo.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.learning.pipeline import LearningPipeline
from triade.workers.mission_planner import MissionPlanner

from tests.learning_evidence_helpers import attach_improved_evidence

#: Contiene `veredicto_triade`, que `extract_target` reconoce como dato
#: distintivo. Sin él el candidato no es medible y el planner lo salta.
CONTENIDO_MEDIBLE = "El veredicto_triade de este patrón es reproducible."


def _pipe(tmp_path: Path) -> LearningPipeline:
    return LearningPipeline(db_path=tmp_path / "triade.db")


def _candidato_verificado(pipe: LearningPipeline, ref: str) -> str:
    # El contenido debe ser único: `ingest` deduplica por contenido y devolvería
    # siempre el mismo candidato.
    cid = pipe.ingest(
        content=f"{CONTENIDO_MEDIBLE} Referencia {ref}.",
        source_type="document",
        source_ref=f"test:{ref}",
        title=f"Patrón {ref}",
        domain="test",
        risk_level="low",
    )["candidate_id"]
    pipe.evaluate(cid)
    pipe.verify(cid)
    return cid


def _forzar_uso(pipe: LearningPipeline, cid: str, *, usos: int, score: float) -> None:
    """Escribe el uso acumulado sin pasar por el gate de medición.

    `mark_used_in_run` mezcla dos cosas: sumar el uso y decidir la promoción.
    Aquí sólo interesa el estado de partida, así que se escribe el contador.
    """
    with sqlite3.connect(pipe.db_path) as conn:
        conn.execute(
            "UPDATE learning_queue SET run_use_count = ?, avg_outcome_score = ?,"
            " run_outcome_scores = ? WHERE candidate_id = ?",
            (usos, score, "[%s]" % ", ".join([str(score)] * usos), cid),
        )


def _marcar_evidence_verified(pipe: LearningPipeline, cid: str) -> None:
    with sqlite3.connect(pipe.db_path) as conn:
        conn.execute(
            "UPDATE learning_queue SET status = 'evidence_verified'"
            " WHERE candidate_id = ?",
            (cid,),
        )


def test_evidence_verified_sigue_acumulando_uso(tmp_path: Path) -> None:
    """Corte 3a: un candidato promovido por evidencia dejaba de contar usos."""
    pipe = _pipe(tmp_path)
    cid = _candidato_verificado(pipe, "acumula")
    attach_improved_evidence(pipe, cid)
    _marcar_evidence_verified(pipe, cid)

    pipe.mark_used_in_run(cid, run_id="run-1", outcome_score=0.9, evidence_ref="ev:1")

    fila = pipe.get_candidate(cid)
    assert fila["run_use_count"] == 1
    assert fila["status"] == "evidence_verified"


def test_consolida_desde_evidence_verified_con_uso_suficiente(tmp_path: Path) -> None:
    """Corte 3b: el estado donde termina la medición no podía consolidarse."""
    pipe = _pipe(tmp_path)
    cid = _candidato_verificado(pipe, "consolida")
    attach_improved_evidence(pipe, cid)
    _marcar_evidence_verified(pipe, cid)
    _forzar_uso(pipe, cid, usos=LearningPipeline.MIN_RUN_USES, score=0.95)

    resultado = pipe.consolidate(cid, approved_by="test-suite")

    assert resultado.get("status") != "blocked"
    assert pipe.get_candidate(cid)["status"] != "evidence_verified"


def test_consolidacion_sigue_exigiendo_uso_minimo(tmp_path: Path) -> None:
    """El arreglo abre una puerta, no baja el listón: sin usos no se consolida."""
    pipe = _pipe(tmp_path)
    cid = _candidato_verificado(pipe, "sin-uso")
    attach_improved_evidence(pipe, cid)
    _marcar_evidence_verified(pipe, cid)
    _forzar_uso(pipe, cid, usos=LearningPipeline.MIN_RUN_USES - 1, score=0.95)

    with pytest.raises(ValueError, match="evidencia suficiente"):
        pipe.consolidate(cid, approved_by="test-suite")


def test_planner_encola_consolidacion_solo_si_el_handler_puede_actuar(
    tmp_path: Path,
) -> None:
    """Corte 2: contaba un estado con cero filas, y nunca encolaba.

    La otra mitad importa igual: con evidencia pero sin usos no debe encolar,
    porque el handler rechazaría la tanda entera y el planner volvería a
    encolarla cada ciclo — el livelock que ya costó 465 intentos idénticos.
    """
    pipe = _pipe(tmp_path)
    planner = MissionPlanner(db_path=pipe.db_path)

    cid = _candidato_verificado(pipe, "planner")
    attach_improved_evidence(pipe, cid)
    _marcar_evidence_verified(pipe, cid)

    _forzar_uso(pipe, cid, usos=LearningPipeline.MIN_RUN_USES - 1, score=0.95)
    assert planner._plan_memory_consolidation() == []

    _forzar_uso(pipe, cid, usos=LearningPipeline.MIN_RUN_USES, score=0.95)
    planeadas = planner._plan_memory_consolidation()
    assert [t.task_type for t in planeadas] == ["stable_consolidation_review"]


def test_la_evidencia_va_primero_a_lo_que_ya_se_usa(tmp_path: Path) -> None:
    """Corte 1: el escaneo por recencia mataba de hambre a los candidatos usados.

    Se reproduce la forma exacta de la base viva: el candidato con uso real es el
    más antiguo, y por delante hay más candidatos nuevos que el límite de
    escaneo. Con orden por recencia nunca se le mide; con el orden por uso, sale
    el primero.
    """
    pipe = _pipe(tmp_path)
    usado = _candidato_verificado(pipe, "antiguo-usado")
    _forzar_uso(pipe, usado, usos=44, score=0.934)

    for i in range(MissionPlanner.EVIDENCE_SCAN_LIMIT + 20):
        _candidato_verificado(pipe, f"nuevo-{i}")

    planner = MissionPlanner(db_path=pipe.db_path)
    planeadas = [
        t
        for t in planner._plan_baseline()
        if t.task_type == "learning_evidence_generation"
    ]

    assert planeadas, "el planner debe pedir evidencia de algún candidato"
    assert planeadas[0].payload["candidate_id"] == usado
