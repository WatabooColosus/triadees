from __future__ import annotations

from pathlib import Path

from triade.core.contracts import CrystalPacket, InputPacket, MemoryPacket, OutputPacket, PlanPacket, SafetyPacket, SignalPacket, VerificationReport
from triade.core.runner import TriadeRunner


def make_runner(tmp_path: Path) -> TriadeRunner:
    return TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)


def _wire_runner(monkeypatch, runner: TriadeRunner, *, response: str, intent: str = "conversation") -> None:
    def analyze(input_packet: InputPacket) -> SignalPacket:
        runner.hypothalamus.last_model_result = {"ok": True, "name": "hypothalamus-test", "provider": "template"}
        return SignalPacket(
            run_id=input_packet.run_id,
            intent=intent,
            tone="neutral",
            urgency="low",
            risk="low",
            notes=["test"],
        )

    def recall(*_: object, **__: object) -> MemoryPacket:
        return MemoryPacket(
            run_id="stub",
            identity_matches=[{"key": "entity_name", "value": "Tríade Ω"}],
            semantic_recall={},
            confidence=0.0,
        )

    def regulate(signals: SignalPacket, memory: MemoryPacket, **_: object) -> CrystalPacket:
        return CrystalPacket(
            run_id=signals.run_id,
            q_crystal=0.6,
            stability=0.6,
            temporal_status="baseline",
            comparison_basis={"context_key": "test"},
        )

    def plan(input_packet: InputPacket, signals: SignalPacket, memory: MemoryPacket, crystal: CrystalPacket) -> PlanPacket:
        return PlanPacket(run_id=input_packet.run_id, goal="test", steps=["one"], tools=[], safety_required=True)

    def review(signals: SignalPacket, plan: PlanPacket, crystal: CrystalPacket, memory: MemoryPacket) -> SafetyPacket:
        return SafetyPacket(run_id=signals.run_id, status="approved", risk_level="low", reason="ok")

    def respond(input_packet: InputPacket, signals: SignalPacket, memory: MemoryPacket, crystal: CrystalPacket, plan: PlanPacket) -> OutputPacket:
        return OutputPacket(
            run_id=input_packet.run_id,
            response=response,
            actions_taken=["test"],
            memory_diff={"pending_persistence": True},
            status="ok",
            model_provider="template",
            model_name="template-fallback",
            model_ok=False,
        )

    def verify(output: OutputPacket, safety: SafetyPacket, crystal: CrystalPacket, memory: MemoryPacket) -> VerificationReport:
        return VerificationReport(run_id=output.run_id, status="ok", coherence_score=0.9, memory_score=0.9, safety_score=1.0, usefulness_score=0.8, traceability_score=0.9)

    monkeypatch.setattr(runner.hypothalamus, "analyze", analyze)
    monkeypatch.setattr(runner.hypothalamus, "apply_qualia_signals", lambda signals, recent: signals)
    monkeypatch.setattr(runner.bodega, "recall", recall)
    monkeypatch.setattr(runner.crystal, "regulate", regulate)
    monkeypatch.setattr(runner.central, "plan", plan)
    monkeypatch.setattr(runner.safety, "review", review)
    monkeypatch.setattr(runner.central, "respond", respond)
    monkeypatch.setattr(runner.verifier, "verify", verify)


def test_runner_factual_simple_does_not_create_neuron(tmp_path: Path, monkeypatch) -> None:
    runner = make_runner(tmp_path)
    _wire_runner(monkeypatch, runner, response="Colombia se encuentra en el continente de América del Sur.")

    result = runner.run("en que continente queda colombia?")

    assert result["response"] == "Colombia se encuentra en el continente de América del Sur."
    assert result["neuron_proposal"] is None
    assert result["neuron_candidate_gate"]["route"] == "learning_candidate"
    assert result["response_coherence_gate"]["detected_input_type"] == "factual_question"


def test_runner_feedback_rewrites_without_repeating_previous_answer(tmp_path: Path, monkeypatch) -> None:
    runner = make_runner(tmp_path)
    _wire_runner(monkeypatch, runner, response="Entendido. Colombia se encuentra en el continente de América del Sur.")

    result = runner.run(
        "muy bine, felicitaciones",
        context={
            "conversation_history": [
                {"role": "user", "content": "en que continente queda colombia?"},
                {"role": "bot", "content": "Colombia se encuentra en el continente de América del Sur."},
            ]
        },
    )

    assert "Colombia se encuentra" not in result["response"]
    assert result["neuron_proposal"] is None
    assert result["neuron_candidate_gate"]["route"] == "qualia_feedback"
    assert result["response_coherence_gate"]["detected_input_type"] == "positive_feedback"
    assert result["memory_diff"]["traceability"]["response_coherence_gate_status"] in {"rewritten", "blocked"}


def test_runner_explicit_neuron_request_creates_candidate(tmp_path: Path, monkeypatch) -> None:
    runner = make_runner(tmp_path)
    _wire_runner(monkeypatch, runner, response="Entendido. Crearé una neurona para eso.", intent="build_or_update")

    result = runner.run("crea una neurona para auditar memoria y evitar contradicciones")

    assert result["neuron_proposal"] is not None
    assert result["neuron_candidate_gate"]["route"] == "neuron"
    assert result["response_coherence_gate"]["detected_input_type"] == "command"
    assert result["memory_diff"]["traceability"]["neuron_candidate_gate_route"] == "neuron"
