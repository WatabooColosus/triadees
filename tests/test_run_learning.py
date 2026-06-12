"""Pruebas de servicios de aprendizaje derivados de runs."""

from __future__ import annotations

from pathlib import Path

from triade.core.contracts import CrystalPacket, InputPacket, OutputPacket, VerificationReport
from triade.core.run_learning import RunLearningService
from triade.memory.semantic_continuity import LOCAL_HASH_MODEL


def test_run_learning_service_creates_post_run_candidate(tmp_path: Path) -> None:
    packet = InputPacket(user_input="Aprender como candidato", source="test", context={"domain": "tests"})
    output = OutputPacket(run_id=packet.run_id, response="Respuesta verificada para aprendizaje")
    report = VerificationReport(run_id=packet.run_id, status="ok")

    result = RunLearningService(db_path=tmp_path / "triade.db").post_run_learning_candidate(
        input_packet=packet,
        output=output,
        report=report,
        intent="conversation",
    )

    assert result["enabled"] is True
    assert result["mode"] == "candidate_only"
    assert result["status"] == "candidate"
    assert result["source_ref"] == f"run:{packet.run_id}"
    assert result["candidate_id"]


def test_run_learning_service_creates_semantic_continuity_candidate(tmp_path: Path) -> None:
    packet = InputPacket(user_input="Memoria semántica del run", source="test")
    output = OutputPacket(
        run_id=packet.run_id,
        response="Respuesta para continuidad semántica",
        model_provider="template",
        model_name="template-fallback",
        model_ok=False,
    )
    crystal = CrystalPacket(run_id=packet.run_id, q_crystal=0.7, stability=0.8)

    result = RunLearningService(db_path=tmp_path / "triade.db").semantic_continuity(
        input_packet=packet,
        output=output,
        intent="memory",
        crystal=crystal,
        model_selection={"enabled": False},
    )

    assert result["status"] == "ok"
    assert result["document"]["source_ref"] == f"run:{packet.run_id}"
    assert result["document"]["status"] == "candidate"
    assert result["embedding_event"]["ok"] is True
    assert result["embedding_event"]["model"] == LOCAL_HASH_MODEL
    assert result["policy"]["auto_consolidation"] is False
