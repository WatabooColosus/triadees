"""El ciclo de automejora conectado al 24/7.

Decisión explícita del responsable (2026-07-31): prefiere un **umbral de salida
altísimo** a una aprobación previa que no puede verificar de forma significativa.
Por eso la política puede aprobar propuestas sin firma humana.

Estos tests fijan lo que sustituye a esa firma:

1. La búsqueda **no** es libre: solo se aprueban propuestas ya existentes, que
   nacen de brechas medidas y están sujetas a cooldown por señal.
2. La aprobación automática queda **registrada como tal** (`auto:threshold_policy`):
   nunca puede parecer que un humano firmó algo que no firmó.
3. Se puede volver a exigir firma humana con
   `TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE=0`.
4. El rigor real vive en el gate de salida, no en la firma previa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from triade.self_improvement.bridge import ImprovementNeuronFactoryBridge
from triade.self_improvement.contracts import ImprovementProposal, ImprovementSignal
from triade.self_improvement.store import ImprovementStore
from triade.workers.contracts import WORKER_TASK_TYPES, WorkerTask
from triade.workers.mission_planner import MissionPlanner
from triade.workers.state_store import WorkerStateStore
from triade.workers.worker_loop import WorkerLoop


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "triade.db"
    WorkerStateStore(path)
    return path


def _propose(
    db: Path,
    proposal_id: str = "p1",
    *,
    confidence: float = 0.96,
    con_destino: bool = True,
) -> None:
    store = ImprovementStore(db)
    store.register_signal(
        ImprovementSignal(
            signal_id=f"sig-{proposal_id}",
            capability_id="triade_vitality",
            metric_id="coherence",
            observed_score=0.74,
            target_score=0.85,
            impact=0.9,
            # Por encima del umbral de aprobación por política (0.94 desde el
            # 2026-08-11). Estaba en 0.9 —justo en el listón anterior— y al
            # subirlo este fixture dejaba de probar lo que dice probar: la
            # propuesta se rechazaba por confianza y no se llegaba a aprobar
            # nada. La señal de este test es deliberadamente buena; el rechazo
            # por confianza baja tiene sus propios casos en
            # tests/test_auto_approval_gate.py.
            confidence=confidence,
            estimated_cost=1.0,
        )
    )
    store.create_proposal(
        ImprovementProposal(
            proposal_id=proposal_id,
            signal_id=f"sig-{proposal_id}",
            hypothesis="mejora la coherencia",
            requested_capability="triade_vitality",
            requires_human_approval=True,
            # A qué neurona apunta. Este fixture no lo declaraba y el test de
            # abajo daba por buena una tarea que en producción **siempre**
            # terminaba en `blocked`: el handler lee `neuron_id`/`version` de
            # `task.payload` y el planner encolaba sin payload. El test estaba
            # verde y la cadena muerta.
            neuron_id="7" if con_destino else None,
            version="1.0.0" if con_destino else None,
        )
    )


def test_el_task_type_esta_registrado():
    assert "self_improvement_evaluation" in WORKER_TASK_TYPES


def test_sin_propuestas_no_se_agenda(tmp_path: Path):
    """Sin brechas medidas no hay nada que intentar: el bucle no gira en vacío."""
    assert MissionPlanner(_db(tmp_path))._plan_self_improvement() == []


def test_confianza_baja_no_hace_girar_el_planificador(tmp_path: Path):
    """El caso vivo 0.40 queda abierto y bloqueado por el umbral común 0.94."""
    db = _db(tmp_path)
    _propose(db, confidence=0.40)

    assert MissionPlanner(db)._plan_self_improvement() == []


def test_la_politica_puede_aprobar_sin_humano_pero_queda_registrado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Corre sin firma humana, pero el aprobador queda marcado como política."""
    monkeypatch.setenv("TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE", "1")
    db = _db(tmp_path)
    _propose(db)
    loop = WorkerLoop(
        db_path=db,
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "l",
        stop_file=tmp_path / "s",
    )
    task = WorkerTask(
        id=7,
        task_type="self_improvement_evaluation",
        payload={"neuron_id": "neuron.inexistente", "version": "1.0.0"},
        status="claimed",
    )
    result = loop._self_improvement_evaluation(task, "run", tmp_path / "runs", None)
    # No promueve (la especificación no existe), pero sí aprobó por política:
    assert result["status"] == "observed"
    assert result.get("approved_by") == "auto:threshold_policy"
    assert result.get("human_approved_proposal") is False


def test_se_puede_volver_a_exigir_firma_humana(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE", "0")
    db = _db(tmp_path)
    _propose(db)
    loop = WorkerLoop(
        db_path=db,
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "l",
        stop_file=tmp_path / "s",
    )
    task = WorkerTask(
        id=8, task_type="self_improvement_evaluation", payload={}, status="claimed"
    )
    result = loop._self_improvement_evaluation(task, "run", tmp_path / "runs", None)
    assert result["status"] == "no_target"
    assert "humano" in result["reason"]


def test_con_aprobacion_humana_se_agenda(tmp_path: Path):
    db = _db(tmp_path)
    _propose(db)
    ImprovementNeuronFactoryBridge(db).approve("p1", approved_by="Santiago")
    planned = MissionPlanner(db)._plan_self_improvement()
    assert [t.task_type for t in planned] == ["self_improvement_evaluation"]
    assert planned[0].source == "human_approved_improvement"
    # Y llega sabiendo sobre qué trabajar, que es lo que faltaba.
    assert planned[0].payload["proposal_id"] == "p1"
    assert planned[0].payload["neuron_id"] == "7"
    assert planned[0].payload["version"] == "1.0.0"


def test_una_propuesta_sin_destino_no_se_agenda(tmp_path: Path):
    """Encolarla sería girar en vacío: la tarea no puede hacer nada con ella.

    `_self_improvement_evaluation` lee `neuron_id`/`version` de `task.payload`.
    Hasta el 2026-08-27 el planner encolaba **sin payload alguno**, así que toda
    propuesta —incluso aprobada a mano y correcta— salía por
    `blocked: no declara neuron_id/version`. Comprobado en la base viva: la
    única propuesta se auto-aprobó por primera vez y murió justo ahí.

    Ahora, sin destino no se encola. El estado queda legible en la propia fila de
    `improvement_proposals`, y no se repite por cuarta vez el patrón de reelegir
    cada ciclo lo que no puede avanzar.
    """
    db = _db(tmp_path)
    _propose(db, con_destino=False)
    ImprovementNeuronFactoryBridge(db).approve("p1", approved_by="Santiago")
    assert MissionPlanner(db)._plan_self_improvement() == []


def test_el_destino_se_declara_entero_o_no_se_declara() -> None:
    """Media terna rompe la clave de idempotencia del handler."""
    with pytest.raises(ValueError, match="neuron_id y version"):
        ImprovementProposal(
            proposal_id="p-medio",
            signal_id="sig",
            hypothesis="mejora la coherencia",
            requested_capability="triade_vitality",
            requires_human_approval=True,
            neuron_id="7",
        ).validate()


def test_no_se_acepta_aprobacion_anonima(tmp_path: Path):
    db = _db(tmp_path)
    _propose(db)
    with pytest.raises(ValueError, match="approved_by"):
        ImprovementNeuronFactoryBridge(db).approve("p1", approved_by="   ")


def test_handler_sin_propuesta_aprobada_no_hace_nada(tmp_path: Path):
    db = _db(tmp_path)
    loop = WorkerLoop(
        db_path=db,
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "l",
        stop_file=tmp_path / "s",
    )
    task = WorkerTask(
        id=1, task_type="self_improvement_evaluation", payload={}, status="claimed"
    )
    result = loop._self_improvement_evaluation(task, "run", tmp_path / "runs", None)
    assert result["status"] == "no_target"


def test_handler_degrada_a_observacion_si_el_ciclo_no_es_promovible(tmp_path: Path):
    """Evidencia insuficiente o contrato incumplido nunca promueve: observa."""
    db = _db(tmp_path)
    _propose(db)
    ImprovementNeuronFactoryBridge(db).approve("p1", approved_by="Santiago")
    loop = WorkerLoop(
        db_path=db,
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "l",
        stop_file=tmp_path / "s",
    )
    task = WorkerTask(
        id=2,
        task_type="self_improvement_evaluation",
        payload={"neuron_id": "neuron.inexistente", "version": "1.0.0"},
        status="claimed",
    )
    result = loop._self_improvement_evaluation(task, "run", tmp_path / "runs", None)
    assert result["status"] == "observed"
    assert "no promovible" in result["reason"]
