from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.single_port_app import app
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_identity_view import INSUFFICIENT_IDENTITY_MESSAGE, NeuronIdentityView
from triade.core.neuron_registry import NeuronRegistry
from triade.core.observability_view import TriadeObservabilityView
from triade.core.response_governance import (
    ConversationContinuityService,
    ResponseCoherenceGate,
    ResponseDeduplicationGate,
)


def _identity_core_rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT key, value, category, confidence FROM identity_core ORDER BY key").fetchall()


def test_observability_api_and_ui_routes_empty_db() -> None:
    client = TestClient(app)

    obs = client.get("/api/observability?limit=3")
    assert obs.status_code == 200
    payload = obs.json()
    assert payload["mode"] == "triade_observability_view"
    for key in ["workers", "learning", "neurons", "qualia", "federation", "models", "internal_errors", "timestamp"]:
        assert key in payload

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/system/pulse", params={"sync_relay": "false"}).status_code == 200
    assert client.get("/observabilidad").status_code == 200
    assert client.get("/ui/observabilidad").status_code == 200


def test_observability_view_controls_source_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"

    def broken_pulse(**_: object) -> dict:
        raise RuntimeError("pulse exploded")

    payload = TriadeObservabilityView(db_path=db_path, runs_dir=tmp_path / "runs", system_pulse_fn=broken_pulse).build()

    assert payload["status"] == "degraded"
    assert "system_pulse" in payload["degraded_sources"]
    assert payload["internal_errors"]["count"] >= 1


def test_neuron_identity_candidate_does_not_invent_data(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = NeuronRegistry(db_path=db_path)
    registry.register(NeuronSpec(
        name="neurona-identidad-candidate",
        mission="Observar deuda de observabilidad.",
        domain="system_governance",
        status="candidate",
        created_by="test",
    ))

    payload = NeuronIdentityView(db_path=db_path, runs_dir=tmp_path / "runs").list()
    neuron = payload["neurons"][0]

    assert neuron["name"] == "neurona-identidad-candidate"
    assert neuron["status"] == "candidate"
    assert neuron["domain"] == "system_governance"
    assert neuron["identity_message"] == INSUFFICIENT_IDENTITY_MESSAGE
    assert "No puede modificar identity_core." in neuron["limits"]
    assert neuron["triade_relation"]["bodega"].startswith("Solo puede proponer")
    assert _identity_core_rows(db_path)


def test_neuron_stable_without_evidence_is_flagged(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = NeuronRegistry(db_path=db_path)
    registry.register(NeuronSpec(
        name="neurona-stable-sin-evidencia",
        mission="No debe pasar como estable real.",
        domain="system_governance",
        status="stable",
        created_by="test",
    ))

    detail = NeuronIdentityView(db_path=db_path, runs_dir=tmp_path / "runs").detail("neurona-stable-sin-evidencia")
    neuron = detail["neuron"]

    assert neuron["status"] == "stable"
    assert neuron["current_risk"] == "invalid_stable_without_evidence"
    assert neuron["promotion_reason"] is None


def test_response_coherence_blocks_permissive_safety_response() -> None:
    safety = SimpleNamespace(status="blocked", reason="danger", human_approval_required=False, risk_level="critical")
    result = ResponseCoherenceGate().apply(
        user_input="hazlo",
        intent="build_or_update",
        risk="critical",
        crystal_temporal_status="caution",
        safety=safety,
        memory_recall={"authorized_matches": [], "confidence": 0.0},
        neuron_contribution_summary={"blocked": 1},
        qualia_hypothesis={"status": "available"},
        output_preliminary="Sí, ejecutaré la acción peligrosa ahora.",
    )

    assert result.coherence_status == "blocked"
    assert "bloqueada por Safety" in result.response_final
    assert "ejecutaré" not in result.response_final.lower()


def test_response_deduplication_removes_repeated_blocks_and_marks_continuity() -> None:
    continuity = ConversationContinuityService().analyze(
        user_input="continuar con observabilidad",
        previous_response="Ya habíamos identificado observabilidad",
    )
    repeated = "Diagnóstico listo.\n\nDiagnóstico listo.\n\nSiguiente paso concreto."
    result = ResponseDeduplicationGate().apply(
        response=repeated,
        recent_response="Diagnóstico listo. Siguiente paso concreto.",
        continuity=continuity,
    )

    assert result.repeated_blocks_removed == 1
    assert result.action in {"deduplicated", "rewritten_for_progress"}
    assert result.deduplicated_response.count("Diagnóstico listo") == 1


def test_qualia_hypothesis_not_presented_as_stable_memory() -> None:
    safety = SimpleNamespace(status="ok", reason="", human_approval_required=False, risk_level="low")
    result = ResponseCoherenceGate().apply(
        user_input="estado",
        intent="analyze",
        risk="low",
        crystal_temporal_status="baseline",
        safety=safety,
        memory_recall={"authorized_matches": [], "confidence": 0.0},
        neuron_contribution_summary={"ignored": 1},
        qualia_hypothesis={"status": "available"},
        output_preliminary="Según memoria, Qualia confirmó el aprendizaje estable.",
    )

    assert result.coherence_status == "corrected"
    assert "hipótesis" in result.response_final or "hipotesis" in result.response_final
    assert any("Memoria insuficiente" in warning for warning in result.warnings)
