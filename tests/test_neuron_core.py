"""Tests de órganos internos de Tríade Ω 1.2."""

from __future__ import annotations

from triade.core.neuron_creator import NeuronCreator, NeuronSpec
from triade.core.neuron_trainer import NeuronTrainer


def test_neuron_creator_builds_valid_spec() -> None:
    creator = NeuronCreator()
    spec = creator.create(
        name="Neurona Test",
        mission="Evaluar una capacidad interna de Tríade de forma verificable.",
        domain="testing",
        rules=["Debe registrar evidencia.", "Debe ser auditable."],
    )

    assert isinstance(spec, NeuronSpec)
    assert spec.name == "Neurona Test"
    assert spec.domain == "testing"
    assert spec.status == "candidate_detected"
    assert len(spec.rules) >= 3
    assert any("verific" in rule.lower() for rule in spec.rules)


def test_neuron_trainer_evaluates_candidate() -> None:
    creator = NeuronCreator()
    trainer = NeuronTrainer()
    spec = creator.create(
        name="Neurona Formativa",
        mission="Formar y evaluar neuronas internas de Tríade antes de volverlas estables.",
        domain="core",
        rules=["Debe producir resultados verificables.", "Debe recomendar mejoras."],
    )

    result = trainer.evaluate(spec)

    assert result.name == spec.name
    assert result.score >= 0.6
    assert result.status in {"experimental_candidate", "candidate"}
    assert result.strengths


def test_neuron_trainer_rejects_weak_spec() -> None:
    trainer = NeuronTrainer()
    weak = NeuronSpec(name="x", mission="corta", domain="", rules=[])

    result = trainer.evaluate(weak)

    assert result.score < 0.6
    assert result.status in {"candidate", "rejected"}
    assert result.warnings


def test_neuron_trainer_penalizes_literal_question_like_mission() -> None:
    trainer = NeuronTrainer()
    spec = NeuronSpec(
        name="neurona-continente-queda-colombia",
        mission="¿En qué continente queda Colombia?",
        domain="general",
        rules=["Debe responder rápido."],
    )

    result = trainer.evaluate(spec)

    assert result.score < 0.5
    assert any("pregunta factual simple" in warning.lower() for warning in result.warnings)
