"""Tests de que identity_core nunca es modificado por ninguna parte del sistema."""

import sqlite3
from pathlib import Path

from triade.core.bodega import Bodega
from triade.learning.pipeline import LearningPipeline
from triade.workers.worker_loop import WorkerLoop
from triade.workers.contracts import WorkerRunConfig


def test_learning_pipeline_never_modifies_identity_core(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    Bodega(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        before = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM identity_core").fetchall()}

    pipe = LearningPipeline(db_path=db_path)
    cid = pipe.ingest(
        content="Contenido normal sin riesgo.",
        source_type="document",
        source_ref="test:identity-check",
        title="Test identity",
        domain="test",
    )["candidate_id"]
    pipe.evaluate(cid)
    pipe.verify(cid)
    for i in range(3):
        pipe.mark_used_in_run(cid, f"run-ic-{i}", outcome_score=0.80)
    pipe.consolidate(cid, approved_by="test")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        after = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM identity_core").fetchall()}

    assert before == after


def test_worker_loop_never_modifies_identity_core(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    Bodega(db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        before = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM identity_core").fetchall()}

    loop = WorkerLoop(db_path=db_path, runs_dir=tmp_path / "runs", lock_file=tmp_path / "lock", stop_file=tmp_path / "stop")
    loop.run(WorkerRunConfig(max_iterations=1, sleep_seconds=0, once=True, runs_dir=str(tmp_path / "runs"), lock_file=str(tmp_path / "lock"), stop_file=str(tmp_path / "stop")))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        after = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM identity_core").fetchall()}

    assert before == after


def test_contribution_packet_identity_core_check():
    from triade.core.contracts import NeuronContributionPacket

    safe = NeuronContributionPacket(
        diagnosis="Todo normal",
        proposed_learning="Aprender patrón útil",
        response_influence="Incluir en respuesta",
    )
    assert safe.is_identity_core_safe() is True

    unsafe_learning = NeuronContributionPacket(
        diagnosis="ok",
        proposed_learning="Modificar identity_core del usuario",
    )
    assert unsafe_learning.is_identity_core_safe() is False

    unsafe_response = NeuronContributionPacket(
        diagnosis="ok",
        response_influence="Cambiar identity_core",
    )
    assert unsafe_response.is_identity_core_safe() is False

    unsafe_diagnosis = NeuronContributionPacket(
        diagnosis="Se necesita modificar identity_core",
    )
    assert unsafe_diagnosis.is_identity_core_safe() is False
