"""Tests del contrato NeuronContributionPacket y políticas de permisos."""

from triade.core.contracts import (
    NeuronContributionPacket,
    NEURON_STATUS_EFFECTS,
    IDENTITY_CORE_FORBIDDEN_EFFECTS,
)


def test_contribution_packet_creation():
    p = NeuronContributionPacket(
        run_id="run-1",
        neuron_id="1",
        neuron_name="test-neuron",
        neuron_status="experimental",
        neuron_domain="system_governance",
        activation_reason="domain match",
        diagnosis="Salud correcta",
        confidence=0.75,
        risk="low",
    )
    assert p.run_id == "run-1"
    assert p.neuron_status == "experimental"
    assert p.contribution_id.startswith("contrib-")


def test_contribution_has_effect():
    p = NeuronContributionPacket(neuron_status="experimental", allowed_effects=["observe", "diagnose", "propose_learning"])
    assert p.has_effect("observe") is True
    assert p.has_effect("diagnose") is True
    assert p.has_effect("propose_learning") is True
    assert p.has_effect("influence_plan") is False
    assert p.has_effect("influence_response") is False


def test_contribution_to_dict():
    p = NeuronContributionPacket(
        run_id="run-1",
        neuron_name="x",
        diagnosis="test",
        allowed_effects=["observe"],
    )
    d = p.to_dict()
    assert isinstance(d, dict)
    assert d["run_id"] == "run-1"
    assert d["allowed_effects"] == ["observe"]


def test_status_effects_policy_candidate():
    effects = NEURON_STATUS_EFFECTS["candidate"]
    assert "observe" in effects
    assert "diagnose" in effects
    assert "influence_plan" not in effects
    assert "influence_response" not in effects
    assert "write_experimental_memory" not in effects


def test_status_effects_policy_experimental():
    effects = NEURON_STATUS_EFFECTS["experimental"]
    assert "observe" in effects
    assert "diagnose" in effects
    assert "propose_learning" in effects
    assert "influence_plan" not in effects
    assert "influence_response" not in effects


def test_status_effects_policy_active_assistant():
    effects = NEURON_STATUS_EFFECTS["active_assistant"]
    assert "influence_plan" in effects
    assert "influence_response" not in effects
    assert "write_experimental_memory" not in effects


def test_status_effects_policy_trusted_worker():
    effects = NEURON_STATUS_EFFECTS["trusted_worker"]
    assert "influence_plan" in effects
    assert "influence_response" in effects
    assert "write_experimental_memory" in effects
    assert "request_stable_promotion" not in effects


def test_status_effects_policy_stable():
    effects = NEURON_STATUS_EFFECTS["stable"]
    assert "request_stable_promotion" in effects
    assert "write_experimental_memory" in effects


def test_identity_core_safe_clean():
    p = NeuronContributionPacket(
        diagnosis="Neurona observó patrón",
        proposed_learning="Mantener ciclo de evaluación",
        response_influence="",
    )
    assert p.is_identity_core_safe() is True


def test_identity_core_unsafe_in_learning():
    p = NeuronContributionPacket(
        diagnosis="ok",
        proposed_learning="Modificar identity_core para agregar nueva personalidad",
    )
    assert p.is_identity_core_safe() is False


def test_identity_core_unsafe_in_response():
    p = NeuronContributionPacket(
        diagnosis="ok",
        response_influence="Cambiar identity_core del sistema",
    )
    assert p.is_identity_core_safe() is False


def test_identity_core_unsafe_in_diagnosis():
    p = NeuronContributionPacket(
        diagnosis="Hay que modificar identity_core del usuario",
    )
    assert p.is_identity_core_safe() is False


def test_identity_core_forbidden_effects_constant():
    assert "write_experimental_memory" in IDENTITY_CORE_FORBIDDEN_EFFECTS
    assert "request_stable_promotion" in IDENTITY_CORE_FORBIDDEN_EFFECTS
    assert "observe" not in IDENTITY_CORE_FORBIDDEN_EFFECTS
    assert "diagnose" not in IDENTITY_CORE_FORBIDDEN_EFFECTS
