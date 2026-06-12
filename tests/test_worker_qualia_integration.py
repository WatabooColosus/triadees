"""Tests de integración Living Workers → QualiaBus."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from triade.qualia.store import QualiaStore
from triade.workers.worker_loop import WorkerLoop


def test_worker_publishes_qualia_experience_on_task_completion(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    loop = WorkerLoop(db_path=db, runs_dir=tmp_path / "runs")
    qualia = loop._publish_qualia_experience(
        run_ref="test-run-1",
        task_type="pending_learning_review",
        neuron_type="worker_learning",
        observation="Test de publicación QualiaBus desde worker.",
        proposed_learning="Mantener ciclo de aprendizaje controlado.",
    )
    assert qualia is not None
    assert qualia["published"] is True
    assert "experience_id" in qualia


def test_worker_qualia_experience_persisted_in_store(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    loop = WorkerLoop(db_path=db, runs_dir=tmp_path / "runs")
    loop._publish_qualia_experience(
        run_ref="test-run-2",
        task_type="semantic_memory_governance",
        neuron_type="worker_governance",
        observation="Test de persistencia QualiaBus.",
    )
    store = QualiaStore(db_path=db)
    experiences = store.list_experiences(run_id="test-run-2")
    assert len(experiences) >= 1
    assert experiences[0]["source_type"] == "worker_task"


def test_worker_qualia_experience_generates_signal(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    loop = WorkerLoop(db_path=db, runs_dir=tmp_path / "runs")
    loop._publish_qualia_experience(
        run_ref="test-run-3",
        task_type="neuron_candidate_formation",
        neuron_type="worker_formation",
        observation="Test de generación de señal QualiaBus.",
    )
    store = QualiaStore(db_path=db)
    signals = store.list_signals(run_id="test-run-3")
    assert len(signals) >= 1


def test_worker_qualia_experience_generates_central_packet(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    loop = WorkerLoop(db_path=db, runs_dir=tmp_path / "runs")
    loop._publish_qualia_experience(
        run_ref="test-run-4",
        task_type="experimental_neuron_activity",
        neuron_type="worker_neuron_activity",
        observation="Test de paquete central QualiaBus.",
    )
    store = QualiaStore(db_path=db)
    packets = store.list_central_packets(run_id="test-run-4")
    assert len(packets) >= 1


def test_worker_qualia_experience_handles_error_gracefully(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    loop = WorkerLoop(db_path=db, runs_dir=tmp_path / "runs")

    with patch("triade.workers.worker_loop.QualiaBus.publish_experience", side_effect=RuntimeError("DB locked")):
        qualia = loop._publish_qualia_experience(
            run_ref="test-run-err",
            task_type="test",
            neuron_type="test",
            observation="Test de manejo de errores.",
        )
        assert qualia is not None
        assert qualia["published"] is False
        assert "error" in qualia


def test_worker_run_once_publishes_qualia(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    from triade.workers.background_service import WorkerBackgroundService
    service = WorkerBackgroundService(db_path=db, runs_dir=str(tmp_path / "runs"))
    result = service.run_once(dry_run=False, task_timeout=10.0)
    assert result["status"] in {"completed", "completed_with_errors", "locked", "stopped"}
    store = QualiaStore(db_path=db)
    total = store.counts()
    qualia_total = sum(total.get(f"qualia_{t}", 0) for t in ["experiences", "signals", "central_packets", "storage_packets"])
    assert qualia_total > 0
