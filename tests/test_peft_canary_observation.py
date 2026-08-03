"""El canary PEFT tiene que acumular observaciones solo.

`GovernedPeftServing` está bien construido —integridad, dataset autorizado,
métricas OOD, rechazo de olvido catastrófico y activación con firma humana
nombrada— pero nadie lo alimentaba: su único llamador era
`scripts/run_phase_13_lora_canary.py`, un script de fase.

Estado real el 2026-08-03: la versión inscrita el 29-jul llevaba cinco días en
`canary` al 5 % con **una** observación, la de su propio minuto de creación.
Ni graduaba ni revertía. Es el mismo agujero que tenía
`self_improvement_canary_observation` antes de tener productor.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.workers.concurrency import policy_for
from triade.workers.contracts import WORKER_TASK_TYPES
from triade.workers.mission_planner import MissionPlanner
from triade.workers.worker_loop import WorkerLoop


def _db_con_canary(tmp_path: Path, *, status: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE governed_peft_versions (
                version_id TEXT PRIMARY KEY, adapter_path TEXT, integrity_sha256 TEXT,
                dataset_id TEXT, status TEXT, traffic_percent REAL,
                baseline_quality REAL, rollback_ref TEXT, approved_by TEXT,
                previous_version_id TEXT, created_at TEXT, updated_at TEXT,
                base_model TEXT DEFAULT '')"""
        )
        conn.execute(
            "INSERT INTO governed_peft_versions VALUES "
            "('peft-abc','/adapters/x','sha','ds',?,5.0,-4.087,'rb',NULL,NULL,"
            "'2026-07-29T23:57:35Z','2026-07-29T23:57:35Z','Qwen/Qwen2.5-0.5B-Instruct')",
            (status,),
        )
    return db


def test_el_tipo_de_tarea_existe_y_es_serial_en_gpu() -> None:
    """Carga modelo base más adaptador: dos a la vez se pelean por la VRAM."""
    assert "peft_canary_observation" in WORKER_TASK_TYPES
    politica = policy_for("peft_canary_observation")
    assert politica.max_concurrency == 1
    assert politica.resource_class == "model"
    assert "version_id" in politica.exclusive_keys
    assert callable(getattr(WorkerLoop, "_peft_canary_observation", None))


def test_un_canary_abierto_se_planifica(tmp_path: Path) -> None:
    db = _db_con_canary(tmp_path, status="canary")

    planeadas = MissionPlanner(db_path=db)._plan_peft_canary_observation()

    assert [t.task_type for t in planeadas] == ["peft_canary_observation"]
    assert planeadas[0].payload["version_id"] == "peft-abc"
    assert planeadas[0].payload["adapter_path"] == "/adapters/x"


def test_sin_canary_abierto_no_se_planifica_nada(tmp_path: Path) -> None:
    """Ni graduado ni fallido se vuelven a observar: sería girar en vacío."""
    for estado in ("active", "canary_failed", "retired"):
        db = _db_con_canary(tmp_path / estado, status=estado)
        assert MissionPlanner(db_path=db)._plan_peft_canary_observation() == []


def test_sin_la_tabla_el_planner_no_revienta(tmp_path: Path) -> None:
    """En una instalación recién montada la gobernanza PEFT no existe todavía."""
    db = tmp_path / "vacia.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE cualquiera (id INTEGER)")
    assert MissionPlanner(db_path=db)._plan_peft_canary_observation() == []


def test_un_adaptador_ausente_no_gasta_la_gpu(tmp_path: Path) -> None:
    """El disco puede no tener el adaptador que la base declara.

    Salir con `no_op` es mejor que cargar medio modelo para fallar después.
    """
    db = _db_con_canary(tmp_path, status="canary")
    loop = WorkerLoop(db_path=db, runs_dir=tmp_path / "runs")

    class _Task:
        def __init__(self) -> None:
            self.payload = {
                "version_id": "peft-abc",
                "adapter_path": str(tmp_path / "no-existe"),
            }

    resultado = loop._peft_canary_observation(_Task(), "run-test", tmp_path, _config())
    assert resultado["effect"] == "no_op"
    assert resultado["skipped_reason"] == "adaptador_ausente_en_disco"


def _config():
    from triade.workers.contracts import WorkerRunConfig

    return WorkerRunConfig()
