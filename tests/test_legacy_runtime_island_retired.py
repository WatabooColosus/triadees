"""La isla T-007..T-024 no puede volver como gemelo del runtime canónico."""

from __future__ import annotations

from pathlib import Path

RETIRED_TO_CANONICAL = {
    "triade/core/system_monitor.py": "triade/runtime/service_health.py",
    "triade/dashboard/routes.py": "apps/routes/api.py",
    "triade/evaluation/advanced_evaluation.py": "triade/evaluation/runner.py",
    "triade/federation/federation_advanced.py": "triade/federation/federation.py",
    "triade/integration/final_validator.py": "triade/verification/certification.py",
    "triade/learning/causal_learning.py": "triade/learning/evidence_producer.py",
    "triade/memory/replacement_tracker.py": "triade/memory/semantic_governance.py",
    "triade/models/smart_router.py": "triade/models/model_router.py",
    "triade/neuron_factory/design.py": "triade/neuron_factory/specification.py",
    "triade/neuron_factory/training.py": "triade/neuron_factory/execution.py",
    "triade/os/autonomous_routines.py": "triade/core/life_pulse.py",
    "triade/os/triadeos_complete.py": "triade/os/__init__.py",
    "triade/sandbox/enhanced_tool_registry.py": "triade/sandbox/policy.py",
    "triade/workers/advanced_scheduler.py": "triade/workers/scheduler.py",
    "triade/workers/worker_supervisor.py": "triade/workers/state_store.py",
}


def test_legacy_runtime_island_stays_retired() -> None:
    root = Path(__file__).resolve().parents[1]
    for retired, canonical in RETIRED_TO_CANONICAL.items():
        assert not (root / retired).exists(), f"gemelo legacy reintroducido: {retired}"
        assert (root / canonical).is_file(), f"falta reemplazo canónico: {canonical}"
