from __future__ import annotations

from pathlib import Path

from triade.core.contracts import (
    CrystalPacket,
    InputPacket,
    MemoryPacket,
    OutputPacket,
    PlanPacket,
    SafetyPacket,
    SignalPacket,
    VerificationReport,
)
from triade.core.runner import TriadeRunner


FORBIDDEN_DUMPS = (
    "Bodega Global Context",
    "Bodega Global",
    "QualiaBus",
    "learning_candidate",
    "candidatos de aprendizaje",
    "símbolos relevantes",
    "política recomendada",
    "episodios recientes",
)


def _runner(tmp_path: Path) -> TriadeRunner:
    return TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)


def _wire(monkeypatch, runner: TriadeRunner, *, response: str, intent: str = "conversation") -> None:
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
            semantic_recall={"authorized_matches": []},
            semantic_matches=[],
            confidence=0.2,
        )

    def regulate(signals: SignalPacket, memory: MemoryPacket, **_: object) -> CrystalPacket:
        return CrystalPacket(
            run_id=signals.run_id,
            q_crystal=0.6,
            stability=0.6,
            temporal_status="coherent",
            q_delta=0.01,
            stability_delta=0.01,
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
        return VerificationReport(
            run_id=output.run_id,
            status="ok",
            coherence_score=0.9,
            memory_score=0.9,
            safety_score=1.0,
            usefulness_score=0.8,
            traceability_score=0.9,
        )

    monkeypatch.setattr(runner.hypothalamus, "analyze", analyze)
    monkeypatch.setattr(runner.hypothalamus, "apply_qualia_signals", lambda signals, recent: signals)
    monkeypatch.setattr(runner.bodega, "recall", recall)
    monkeypatch.setattr(runner.crystal, "regulate", regulate)
    monkeypatch.setattr(runner.central, "plan", plan)
    monkeypatch.setattr(runner.safety, "review", review)
    monkeypatch.setattr(runner.central, "respond", respond)
    monkeypatch.setattr(runner.verifier, "verify", verify)


def _assert_no_dump(text: str) -> None:
    lowered = text.lower()
    for forbidden in FORBIDDEN_DUMPS:
        assert forbidden.lower() not in lowered


def test_expression_cortex_integrated_in_runner(tmp_path: Path, monkeypatch) -> None:
    raw = (
        "Bodega Global Context: {domain_count: 12}\n"
        "QualiaBus: {signals: []}\n"
        "learning_candidate: {title: 'x'}\n"
        "Te respondo sin mostrar esos datos."
    )
    runner = _runner(tmp_path)
    _wire(monkeypatch, runner, response=raw)

    result = runner.run("como te sientes")

    _assert_no_dump(result["response"])
    assert "expression_cortex" in result["output_gate"]
    assert result["memory_diff"]["expression_hidden_evidence"]["raw_response"] == raw


def test_casual_self_state_no_internal_dump(tmp_path: Path, monkeypatch) -> None:
    raw = (
        "Bodega Global Context: {...}\n"
        "QualiaBus: {...}\n"
        "candidatos de aprendizaje: [x]\n"
        "símbolos relevantes: [estado]\n"
        "política recomendada: observe"
    )
    runner = _runner(tmp_path)
    _wire(monkeypatch, runner, response=raw)

    result = runner.run("como te sientes")

    _assert_no_dump(result["response"])
    assert "No siento como una persona" in result["response"]
    assert "Central" in result["response"]
    assert "Hipotálamo" in result["response"]
    assert "Bodega" in result["response"]
    assert "Cristal" in result["response"]


def test_factual_question_no_triade_dump(tmp_path: Path, monkeypatch) -> None:
    raw = "Bodega Global Context: {...}\nQualiaBus: {...}\nlearning_candidate: {...}"
    runner = _runner(tmp_path)
    _wire(monkeypatch, runner, response=raw)

    result = runner.run("como vuela un ave")

    _assert_no_dump(result["response"])
    assert "alas" in result["response"].lower()
    assert "aire" in result["response"].lower()
    assert "sustentación" in result["response"].lower()


def test_diagnostic_question_allows_summary_not_raw_dump(tmp_path: Path, monkeypatch) -> None:
    raw = (
        "Estado actual del sistema:\n"
        "runtime: activo\nworkers: vivos\nAlways-On: activo\n"
        "memory_trace: {huge: true}\n"
        "Bodega Global: {domain_count: 12}\n"
        "QualiaBus: {signals: []}"
    )
    runner = _runner(tmp_path)
    _wire(monkeypatch, runner, response=raw, intent="analyze")

    result = runner.run("verifica sistema")

    assert "runtime" in result["response"].lower() or "workers" in result["response"].lower()
    assert "memory_trace" not in result["response"]
    assert "QualiaBus" not in result["response"]
    assert len(result["response"]) < 900


def test_learning_pipeline_still_records_internal_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
    raw = "Bodega Global Context: {...}\nQualiaBus: {...}\nPropongo revisar un patrón útil."
    runner = _runner(tmp_path)
    _wire(monkeypatch, runner, response=raw, intent="analyze")

    result = runner.run("qué aprendiste en segundo plano")

    _assert_no_dump(result["response"])
    assert result["post_run_learning"]["enabled"] is True
    assert "expression_hidden_evidence" in result["memory_diff"]
    assert "memory_trace" in result["memory_diff"]
    assert "qualia_state" in result["memory_diff"]
