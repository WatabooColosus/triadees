"""Fase D · federación entre nodos autorizados."""

from __future__ import annotations

from pathlib import Path

import pytest

from triade.federation.federation import Federation
from triade.learning.pipeline import LearningPipeline


def fed(tmp_path: Path) -> Federation:
    return Federation(db_path=tmp_path / "triade.db")


def test_register_node_rejects_forbidden_permissions(tmp_path: Path) -> None:
    federation = fed(tmp_path)
    with pytest.raises(ValueError, match="prohibidos"):
        federation.register_node("n1", "Nodo", permissions=["receive_knowledge", "modify_identity_core"])

    node = federation.register_node("n1", "Nodo aliado", trust_level="medium",
                                    permissions=["receive_knowledge", "send_knowledge"])
    assert node["status"] == "active"
    assert set(node["permissions"]) == {"receive_knowledge", "send_knowledge"}


def test_receive_requires_active_node_and_permission(tmp_path: Path) -> None:
    federation = fed(tmp_path)
    # nodo desconocido
    assert federation.receive_exchange("ghost", "knowledge", "hola")["decision"] == "blocked"

    federation.register_node("n1", "Nodo", permissions=["receive_patterns"])
    # tiene receive_patterns pero NO receive_knowledge
    blocked = federation.receive_exchange("n1", "knowledge", "dato")
    assert blocked["decision"] == "blocked"
    assert "Permiso requerido ausente" in blocked["reason"]


def test_received_knowledge_enters_as_candidate_never_consolidated(tmp_path: Path) -> None:
    federation = fed(tmp_path)
    federation.register_node("n1", "Aliado", trust_level="high", permissions=["receive_knowledge"])

    result = federation.receive_exchange(
        "n1", "knowledge",
        "Patrón verificado de extracción de cold brew compartido por nodo aliado.",
        risk_level="low", domain="cafe",
    )
    assert result["decision"] == "accepted_as_learning_candidate"
    assert result["consolidated"] is False
    cid = result["learning_candidate_id"]
    assert cid is not None

    candidate = LearningPipeline(db_path=tmp_path / "triade.db").get_candidate(cid)
    assert candidate["status"] == "candidate"  # entra como candidato, no consolidado
    assert candidate["source_type"] == "node"


def test_critical_risk_exchange_is_blocked(tmp_path: Path) -> None:
    federation = fed(tmp_path)
    federation.register_node("n1", "Aliado", trust_level="high", permissions=["receive_knowledge"])
    result = federation.receive_exchange("n1", "knowledge", "acción peligrosa", risk_level="critical")

    assert result["decision"] == "blocked"
    assert result["learning_candidate_id"] is None


def test_send_blocks_sensitive_data_leak(tmp_path: Path) -> None:
    federation = fed(tmp_path)
    federation.register_node("n1", "Aliado", permissions=["send_knowledge"])

    leaked = federation.send_exchange("n1", "knowledge", "aquí está el api_key secreto: 1234")
    assert leaked["decision"] == "blocked"

    ok = federation.send_exchange("n1", "knowledge", "resumen público de un patrón de marketing")
    assert ok["decision"] == "sent"


def test_revoked_node_cannot_exchange(tmp_path: Path) -> None:
    federation = fed(tmp_path)
    federation.register_node("n1", "Aliado", trust_level="high", permissions=["receive_knowledge"])
    federation.revoke_node("n1", reason="violó permisos")

    assert federation.get_node("n1")["status"] == "revoked"
    result = federation.receive_exchange("n1", "knowledge", "dato")
    assert result["decision"] == "blocked"


def test_doctor_reports_policy_and_counts(tmp_path: Path) -> None:
    federation = fed(tmp_path)
    federation.register_node("n1", "Aliado", trust_level="medium", permissions=["receive_knowledge"])
    federation.receive_exchange("n1", "knowledge", "dato útil con fuente", domain="general")

    doctor = federation.doctor()
    assert doctor["policy"]["auto_consolidation"] is False
    assert doctor["policy"]["identity_core_protected"] is True
    assert "modify_identity_core" in doctor["policy"]["forbidden_permissions"]
    assert doctor["nodes_by_status"]["active"] == 1


def test_federation_tracks_capable_compute_nodes(tmp_path: Path) -> None:
    federation = fed(tmp_path)
    low = {
        "tier": "low",
        "cpu_count": 2,
        "ram_available_gb": 2.0,
        "gpus": [],
    }
    high = {
        "tier": "high",
        "cpu_count": 16,
        "ram_available_gb": 24.0,
        "gpus": [{"name": "RTX Test", "vram_total_gb": 12.0, "cuda_available": True}],
    }

    federation.register_node("small", "Nodo CPU pequeno", permissions=["publish_capabilities"], capabilities=low)
    federation.register_node(
        "gpu",
        "Nodo GPU",
        trust_level="high",
        permissions=["publish_capabilities", "request_compute"],
        capabilities=high,
    )

    capable = federation.list_capable_nodes(min_tier="medium")
    assert [node["node_id"] for node in capable] == ["gpu"]
    assert federation.list_capable_nodes(min_tier="medium", require_gpu=True)[0]["node_id"] == "gpu"

    doctor = federation.doctor()
    assert doctor["nodes_by_capability"]["high"] == 1
    assert doctor["compute_ready_nodes"] == 1
