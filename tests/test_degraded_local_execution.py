from pathlib import Path

from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.core.neuron_nutrition import run_neuron_nutrition_cycle


def _seed_safe_mission(db_path: Path) -> int:
    store = NeuronMissionStore(db_path=db_path)
    mission_id = store.create_mission(
        NeuronMission(
            title="Diagnóstico local degradado",
            domain="runtime",
            mission="Registrar evidencia local sin depender de Ollama.",
            allowed_actions=["observe", "diagnose", "propose_learning"],
            status="experimental",
        )
    )
    return int(mission_id)


def test_safe_mission_runs_without_ollama_and_preserves_guards(monkeypatch, tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    mission_id = _seed_safe_mission(db_path)

    monkeypatch.setattr(
        "triade.core.neuron_nutrition.check_ollama_blood",
        lambda: {
            "status": "degraded_no_ollama",
            "cognitive_blood_active": False,
            "can_nourish_neurons": False,
            "blood_pressure_score": 0.0,
        },
    )
    monkeypatch.setattr(
        "triade.core.neuron_nutrition.ollama_blood_policy",
        lambda *_: {
            "allowed": False,
            "degraded": True,
            "reason": "Ollama no disponible",
            "model_used": None,
            "blocked_actions": ["stable_memory_write"],
        },
    )
    monkeypatch.setattr(
        "triade.core.neuron_nutrition.check_ollama_cognitive_health",
        lambda: {"ok": False},
    )

    result = run_neuron_nutrition_cycle(
        db_path=db_path,
        runs_dir=runs_dir,
        mode="execute_missions",
        limit=5,
    )

    store = NeuronMissionStore(db_path=db_path)
    assert result["status"] == "ok"
    assert result["degraded_mode"] is True
    assert result["missions_executed"] >= 1
    assert store.list_cycles(mission_id, limit=10)
    assert store.list_evidence(mission_id, limit=10)
    assert result["stable_memory_written"] is False
    assert result["identity_core_modified"] is False
    assert result["model_used"]["model_provider"] == "fallback"
    assert result["model_used"]["model_required"] is False


def test_observe_only_never_executes_safe_mission(monkeypatch, tmp_path):
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    _seed_safe_mission(db_path)

    monkeypatch.setattr(
        "triade.core.neuron_nutrition.check_ollama_blood",
        lambda: {"status": "degraded_no_ollama", "cognitive_blood_active": False},
    )
    monkeypatch.setattr(
        "triade.core.neuron_nutrition.ollama_blood_policy",
        lambda *_: {"allowed": False, "degraded": True, "reason": "Ollama no disponible", "model_used": None},
    )
    monkeypatch.setattr(
        "triade.core.neuron_nutrition.check_ollama_cognitive_health",
        lambda: {"ok": False},
    )

    result = run_neuron_nutrition_cycle(
        db_path=db_path,
        runs_dir=runs_dir,
        mode="observe_only",
        limit=5,
    )

    assert result["missions_executed"] == 0
    assert result["stable_memory_written"] is False
    assert result["identity_core_modified"] is False
