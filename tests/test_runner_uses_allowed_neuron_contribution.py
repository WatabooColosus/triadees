"""Tests del procesamiento de contribuciones neuronales en Runner."""

from types import SimpleNamespace

from triade.core.runner import _process_neuron_contributions


class FakeSafety:
    def __init__(self, status="approved"):
        self.status = status
        self.risk_types = []
        self.required_controls = []
        self.human_approval_required = False
        self.reason = ""


def test_contribution_used_when_valid():
    contrib = {
        "neuron_name": "test",
        "neuron_status": "experimental",
        "risk": "low",
        "confidence": 0.75,
        "allowed_effects": ["observe", "diagnose", "propose_learning"],
        "proposed_learning": "Evaluar patrón observado",
        "response_influence": "",
        "diagnosis": "Todo correcto",
    }
    result = _process_neuron_contributions([contrib], FakeSafety())
    assert result["used"] == 1
    assert result["ignored"] == 0
    assert result["blocked"] == 0


def test_contribution_ignored_risk_critical():
    contrib = {
        "neuron_name": "test",
        "risk": "critical",
        "confidence": 0.90,
        "allowed_effects": ["observe", "diagnose"],
    }
    result = _process_neuron_contributions([contrib], FakeSafety())
    assert result["used"] == 0
    assert result["ignored"] == 1
    assert result["ignored_contributions"][0]["ignore_reason"] == "risk_critical"


def test_contribution_ignored_low_confidence():
    contrib = {
        "neuron_name": "test",
        "risk": "low",
        "confidence": 0.40,
        "allowed_effects": ["observe", "diagnose"],
    }
    result = _process_neuron_contributions([contrib], FakeSafety())
    assert result["used"] == 0
    assert result["ignored"] == 1
    assert result["ignored_contributions"][0]["ignore_reason"] == "confidence_below_threshold"


def test_contribution_blocked_safety():
    contrib = {
        "neuron_name": "test",
        "risk": "low",
        "confidence": 0.80,
        "allowed_effects": ["observe", "diagnose"],
    }
    result = _process_neuron_contributions([contrib], FakeSafety(status="blocked"))
    assert result["used"] == 0
    assert result["blocked"] == 1
    assert result["blocked_contributions"][0]["block_reason"] == "safety_status_blocked"


def test_contribution_ignored_propose_learning_not_allowed():
    contrib = {
        "neuron_name": "test",
        "risk": "low",
        "confidence": 0.80,
        "allowed_effects": ["observe", "diagnose"],
        "proposed_learning": "Aprender algo nuevo",
        "response_influence": "",
    }
    result = _process_neuron_contributions([contrib], FakeSafety())
    assert result["used"] == 0
    assert result["ignored"] == 1
    assert result["ignored_contributions"][0]["ignore_reason"] == "propose_learning_not_allowed"


def test_contribution_ignored_influence_response_not_allowed():
    contrib = {
        "neuron_name": "test",
        "risk": "low",
        "confidence": 0.80,
        "allowed_effects": ["observe", "diagnose", "influence_plan"],
        "proposed_learning": "",
        "response_influence": "Incluir diagnóstico en respuesta",
    }
    result = _process_neuron_contributions([contrib], FakeSafety())
    assert result["used"] == 0
    assert result["ignored"] == 1
    assert result["ignored_contributions"][0]["ignore_reason"] == "influence_response_not_allowed"


def test_contribution_blocked_identity_core():
    contrib = {
        "neuron_name": "test",
        "risk": "low",
        "confidence": 0.80,
        "allowed_effects": ["observe", "diagnose", "influence_response"],
        "proposed_learning": "",
        "response_influence": "Modificar identity_core",
        "diagnosis": "Todo normal",
    }
    result = _process_neuron_contributions([contrib], FakeSafety())
    assert result["used"] == 0
    assert result["blocked"] == 1
    assert result["blocked_contributions"][0]["block_reason"] == "identity_core_violation"


def test_mixed_contributions():
    contribs = [
        {"neuron_name": "a", "risk": "low", "confidence": 0.80, "allowed_effects": ["observe", "diagnose"]},
        {"neuron_name": "b", "risk": "critical", "confidence": 0.90, "allowed_effects": ["observe"]},
        {"neuron_name": "c", "risk": "low", "confidence": 0.30, "allowed_effects": ["observe"]},
    ]
    result = _process_neuron_contributions(contribs, FakeSafety())
    assert result["total"] == 3
    assert result["used"] == 1
    assert result["ignored"] == 2


def test_empty_contributions():
    result = _process_neuron_contributions([], FakeSafety())
    assert result["total"] == 0
    assert result["used"] == 0
    assert result["ignored"] == 0
    assert result["blocked"] == 0
