"""Tests de la política de permisos por estado de neurona."""

from triade.core.contracts import NEURON_STATUS_EFFECTS, IDENTITY_CORE_FORBIDDEN_EFFECTS


def test_all_statuses_defined():
    expected = {"candidate", "experimental", "active_assistant", "trusted_worker", "stable"}
    assert set(NEURON_STATUS_EFFECTS.keys()) == expected


def test_candidate_cannot_influence():
    effects = NEURON_STATUS_EFFECTS["candidate"]
    for forbidden in ("influence_plan", "influence_response", "write_experimental_memory", "request_stable_promotion"):
        assert forbidden not in effects, f"candidate no debe tener {forbidden}"


def test_experimental_cannot_influence():
    effects = NEURON_STATUS_EFFECTS["experimental"]
    for forbidden in ("influence_plan", "influence_response", "write_experimental_memory", "request_stable_promotion"):
        assert forbidden not in effects, f"experimental no debe tener {forbidden}"


def test_active_assistant_can_influence_plan_only():
    effects = NEURON_STATUS_EFFECTS["active_assistant"]
    assert "influence_plan" in effects
    assert "influence_response" not in effects
    assert "write_experimental_memory" not in effects


def test_trusted_worker_can_influence_plan_and_response():
    effects = NEURON_STATUS_EFFECTS["trusted_worker"]
    assert "influence_plan" in effects
    assert "influence_response" in effects
    assert "write_experimental_memory" in effects
    assert "request_stable_promotion" not in effects


def test_stable_has_all_effects():
    effects = NEURON_STATUS_EFFECTS["stable"]
    for required in ("observe", "diagnose", "propose_learning", "influence_plan", "influence_response", "write_experimental_memory", "request_stable_promotion"):
        assert required in effects, f"stable debe tener {required}"


def test_monotonic_effect_granting():
    prev_count = 0
    for status in ("candidate", "experimental", "active_assistant", "trusted_worker", "stable"):
        current_count = len(NEURON_STATUS_EFFECTS[status])
        assert current_count >= prev_count, f"{status} debe tener >= efectos que el anterior"
        prev_count = current_count


def test_identity_core_forbidden_effects_always_blocked():
    for status, effects in NEURON_STATUS_EFFECTS.items():
        for forbidden in IDENTITY_CORE_FORBIDDEN_EFFECTS:
            if status in ("candidate", "experimental", "active_assistant"):
                assert forbidden not in effects, f"{status} no debe tener {forbidden} (forbidden)"


def test_observe_and_diagnose_always_allowed():
    for status, effects in NEURON_STATUS_EFFECTS.items():
        assert "observe" in effects, f"{status} debe tener observe"
        assert "diagnose" in effects, f"{status} debe tener diagnose"


def test_effects_are_strings():
    for status, effects in NEURON_STATUS_EFFECTS.items():
        for effect in effects:
            assert isinstance(effect, str), f"Effect in {status} must be string"
            assert len(effect) > 0, f"Effect in {status} must not be empty"
