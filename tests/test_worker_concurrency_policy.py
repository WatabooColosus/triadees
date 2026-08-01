"""La política de carriles decide qué puede solaparse. Aquí se verifica que lo hace.

Estos tests no ejecutan tareas reales: comprueban la *decisión*. La ejecución
concurrente de verdad se prueba en `test_worker_concurrency_pool.py`.
"""

from __future__ import annotations

from triade.workers.concurrency import (
    GLOBAL_PROMOTION_KEY,
    LANE_ORDER,
    TASK_CONCURRENCY_POLICY,
    UNKNOWN_TASK_LANE,
    ConcurrencySettings,
    RunningTaskRegistry,
    exclusion_keys,
    is_known_task_type,
    policy_for,
)
from triade.workers.contracts import WORKER_TASK_TYPES, WorkerRunConfig


def test_every_known_task_type_has_an_explicit_policy() -> None:
    """Un tipo sin política declarada acabaría serializado por accidente.

    Preferimos que el fallo salga aquí, al añadir el tipo, y no en producción en
    forma de rendimiento inexplicable.
    """
    missing = [t for t in WORKER_TASK_TYPES if t not in TASK_CONCURRENCY_POLICY]
    assert missing == [], f"tipos sin politica de concurrencia: {missing}"


def test_policy_table_has_no_orphans() -> None:
    """Una política para un tipo que ya no existe es documentación falsa."""
    orphans = [t for t in TASK_CONCURRENCY_POLICY if t not in WORKER_TASK_TYPES]
    assert orphans == [], f"politicas sin tipo de tarea: {orphans}"


def test_lane_assignment_matches_the_governance_intent() -> None:
    expected = {
        "pulse_check": "read_only",
        "system_debt_scan": "read_only",
        "goal_research": "research",
        "research_curriculum": "research",
        "self_improvement_evaluation": "evaluation",
        "self_improvement_canary_observation": "evaluation",
        "memory_consolidation_review": "memory_write",
        "stable_consolidation_review": "memory_write",
        "neuron_autopromotion": "critical_mutation",
        "goal_lora_train": "critical_mutation",
    }
    for task_type, lane in expected.items():
        assert policy_for(task_type).lane == lane, task_type


def test_critical_mutation_lane_is_always_serial() -> None:
    for task_type, policy in TASK_CONCURRENCY_POLICY.items():
        if policy.lane == "critical_mutation":
            assert policy.max_concurrency == 1, task_type


def test_memory_write_lane_is_always_serial() -> None:
    for task_type, policy in TASK_CONCURRENCY_POLICY.items():
        if policy.lane == "memory_write":
            assert policy.max_concurrency == 1, task_type


def test_unknown_task_type_falls_back_to_safe_serial_lane() -> None:
    """Una tarea que nadie clasificó podría escribir cualquier cosa."""
    policy = policy_for("tarea_que_nadie_declaro")
    assert not is_known_task_type("tarea_que_nadie_declaro")
    assert policy.lane == UNKNOWN_TASK_LANE
    assert policy.max_concurrency == 1
    assert policy.resource_class == "critical"


def test_unknown_task_type_warns(caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level("WARNING"):
        policy_for("otro_tipo_sin_declarar")
    assert "sin politica de concurrencia" in caplog.text


def test_exclusion_keys_are_derived_from_payload() -> None:
    keys = exclusion_keys(
        "self_improvement_evaluation",
        {"candidate_id": "cand-1", "neuron_id": "n-7", "proposal_id": "prop-3"},
    )
    assert keys == {"candidate_id=cand-1", "neuron_id=n-7", "proposal_id=prop-3"}


def test_exclusion_keys_skip_absent_values() -> None:
    """Sin `candidate_id` la tarea no muta ninguna candidata concreta."""
    keys = exclusion_keys("self_improvement_evaluation", {"neuron_id": "n-7"})
    assert keys == {"neuron_id=n-7"}


def test_promotion_declares_a_global_exclusive_key() -> None:
    """Dos promociones no coexisten aunque sean de neuronas distintas."""
    first = exclusion_keys("neuron_autopromotion", {"neuron_id": "n-1"})
    second = exclusion_keys("neuron_autopromotion", {"neuron_id": "n-2"})
    assert GLOBAL_PROMOTION_KEY in first
    assert first & second == {GLOBAL_PROMOTION_KEY}


# ── admisión ────────────────────────────────────────────────────────────


def _registry(**kwargs: object) -> RunningTaskRegistry:
    settings = ConcurrencySettings(enabled=True, **kwargs)  # type: ignore[arg-type]
    return RunningTaskRegistry(settings)


def test_two_read_only_tasks_run_at_the_same_time() -> None:
    registry = _registry(max_concurrent_tasks=4, read_only_workers=4)
    assert registry.try_admit("t1", "pulse_check", {}).admitted
    assert registry.try_admit("t2", "system_debt_scan", {}).admitted
    assert registry.running_count() == 2


def test_global_limit_blocks_admission() -> None:
    registry = _registry(max_concurrent_tasks=2, read_only_workers=4)
    assert registry.try_admit("t1", "pulse_check", {}).admitted
    assert registry.try_admit("t2", "pulse_check", {}).admitted
    denied = registry.try_admit("t3", "pulse_check", {})
    assert not denied.admitted
    assert denied.reason == "global_limit"


def test_lane_limit_blocks_admission_independently_of_global() -> None:
    registry = _registry(max_concurrent_tasks=8, research_workers=1)
    assert registry.try_admit("r1", "goal_research", {}).admitted
    denied = registry.try_admit("r2", "research_curriculum", {})
    assert not denied.admitted
    assert denied.reason == "lane_limit"
    # Otro carril sigue libre: un carril lleno no congela el runtime entero.
    assert registry.try_admit("p1", "pulse_check", {}).admitted


def test_critical_mutation_is_serial_even_with_a_high_global_limit() -> None:
    registry = _registry(max_concurrent_tasks=8, critical_mutation_workers=1)
    assert registry.try_admit(
        "c1", "neuron_autopromotion", {"neuron_id": "n-1"}
    ).admitted
    denied = registry.try_admit("c2", "neuron_autopromotion", {"neuron_id": "n-2"})
    assert not denied.admitted
    assert denied.reason in {"lane_limit", "exclusive_key_held:global_promotion"}


def test_same_neuron_cannot_be_evaluated_twice_at_once() -> None:
    registry = _registry(max_concurrent_tasks=8, evaluation_workers=4)
    assert registry.try_admit(
        "e1", "experimental_neuron_activity", {"neuron_id": "n-9"}
    ).admitted
    denied = registry.try_admit(
        "e2", "experimental_neuron_activity", {"neuron_id": "n-9"}
    )
    assert not denied.admitted
    assert denied.reason == "exclusive_key_held:neuron_id=n-9"


def test_same_candidate_cannot_be_mutated_twice_at_once() -> None:
    registry = _registry(max_concurrent_tasks=8, evaluation_workers=4)
    payload = {"candidate_id": "cand-1", "neuron_id": "n-1"}
    assert registry.try_admit("e1", "self_improvement_evaluation", payload).admitted
    denied = registry.try_admit("e2", "self_improvement_evaluation", dict(payload))
    assert not denied.admitted
    assert denied.reason.startswith("exclusive_key_held:")


def test_different_neurons_evaluate_in_parallel() -> None:
    """El objetivo del trabajo: varias neuronas en etapas distintas a la vez."""
    registry = _registry(max_concurrent_tasks=8, evaluation_workers=2)
    assert registry.try_admit(
        "e1", "self_improvement_evaluation", {"candidate_id": "c1", "neuron_id": "n-1"}
    ).admitted
    assert registry.try_admit(
        "e2", "self_improvement_evaluation", {"candidate_id": "c2", "neuron_id": "n-2"}
    ).admitted
    assert registry.running_count() == 2


def test_release_frees_the_exclusive_key() -> None:
    registry = _registry(max_concurrent_tasks=4, evaluation_workers=2)
    payload = {"candidate_id": "cand-1"}
    registry.try_admit("e1", "self_improvement_canary_observation", payload)
    assert registry.holds_key("candidate_id=cand-1")
    registry.release("e1")
    assert not registry.holds_key("candidate_id=cand-1")
    assert registry.try_admit(
        "e2", "self_improvement_canary_observation", payload
    ).admitted


def test_releasing_an_unknown_task_is_harmless() -> None:
    assert _registry().release("nunca-existio") is None


def test_admitting_the_same_task_id_twice_is_refused() -> None:
    """Defensa contra doble despacho de la misma tarea arrendada."""
    registry = _registry(max_concurrent_tasks=4)
    assert registry.try_admit("t1", "pulse_check", {}).admitted
    duplicate = registry.try_admit("t1", "pulse_check", {})
    assert not duplicate.admitted
    assert duplicate.reason == "already_running"


def test_disabled_concurrency_is_strictly_serial() -> None:
    """Con la bandera apagada el comportamiento debe igualar al anterior."""
    registry = RunningTaskRegistry(ConcurrencySettings.serial())
    assert registry.try_admit("t1", "pulse_check", {}).admitted
    denied = registry.try_admit("t2", "pulse_check", {})
    assert not denied.admitted
    assert denied.reason == "global_limit"


def test_pressure_scale_reduces_effective_limits() -> None:
    """El backpressure debe poder estrechar los carriles sin reconfigurar nada."""
    registry = _registry(max_concurrent_tasks=4, read_only_workers=4)
    registry.set_pressure_scale(0.25)
    assert registry.try_admit("t1", "pulse_check", {}).admitted
    denied = registry.try_admit("t2", "pulse_check", {})
    assert not denied.admitted
    assert denied.reason == "global_limit"


def test_pressure_scale_never_drops_below_one() -> None:
    """Reducir por presión nunca debe congelar el runtime por completo."""
    registry = _registry(max_concurrent_tasks=4)
    registry.set_pressure_scale(0.0)
    assert registry.try_admit("t1", "pulse_check", {}).admitted


# ── observabilidad ──────────────────────────────────────────────────────


def test_snapshot_reports_every_lane() -> None:
    registry = _registry(max_concurrent_tasks=4, read_only_workers=4)
    registry.try_admit("t1", "pulse_check", {})
    snapshot = registry.snapshot(queued=6)
    assert snapshot["enabled"] is True
    assert snapshot["running"] == 1
    assert snapshot["queued"] == 6
    assert set(snapshot["lanes"]) == set(LANE_ORDER)
    assert snapshot["lanes"]["read_only"]["running"] == 1
    assert snapshot["lanes"]["critical_mutation"]["limit"] == 1


def test_running_tasks_expose_traceable_fields() -> None:
    registry = _registry(max_concurrent_tasks=4)
    registry.try_admit(
        "t1", "self_improvement_evaluation", {"candidate_id": "c1"}, lease_generation=7
    )
    (entry,) = registry.running_tasks()
    assert entry.task_id == "t1"
    assert entry.task_type == "self_improvement_evaluation"
    assert entry.lane == "evaluation"
    assert entry.resource_class == "model"
    assert entry.lease_generation == 7
    assert entry.started_at > 0
    assert "candidate_id=c1" in entry.keys


# ── configuración ───────────────────────────────────────────────────────


def test_concurrency_is_on_by_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Encendida por defecto desde 2026-08-01.

    Estuvo apagada porque al activarla `test_worker_learning_integration` se
    ponia rojo en CI. Eso ya no describe la realidad: los seis trabajos
    concurrentes de la matriz (py3.11 x3, py3.12 x3) terminan el pytest al
    100 %, ese test incluido. El rojo que se le atribuia venia de otro paso, con
    una comprobacion que exigia datos reales de produccion en un runner limpio.

    Los limites siguen siendo los conservadores: encender la concurrencia no es
    soltar el freno de mano.
    """
    monkeypatch.delenv("TRIADE_WORKER_CONCURRENCY", raising=False)
    settings = WorkerRunConfig().concurrency_settings()
    assert settings.enabled is True
    assert settings.max_concurrent_tasks == 3
    assert settings.memory_write_workers == 1
    assert settings.critical_mutation_workers == 1


def test_concurrency_can_be_switched_off_by_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """La vuelta atras es una variable de entorno, sin desplegar codigo."""
    monkeypatch.setenv("TRIADE_WORKER_CONCURRENCY", "0")
    settings = WorkerRunConfig().concurrency_settings()
    assert settings.enabled is False
    assert settings.effective_global_limit() == 1


def test_concurrency_can_be_switched_on_by_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("TRIADE_WORKER_CONCURRENCY", "1")
    settings = WorkerRunConfig().concurrency_settings()
    assert settings.enabled is True
    assert settings.max_concurrent_tasks == 3
    assert settings.critical_mutation_workers == 1
    assert settings.memory_write_workers == 1


def test_explicit_flag_off_still_wins_over_the_default() -> None:
    """Lo explicito manda en los dos sentidos, no solo para encender."""
    settings = WorkerRunConfig(concurrency_enabled=False).concurrency_settings()
    assert settings.enabled is False
    assert settings.effective_global_limit() == 1


def test_explicit_flag_still_wins_over_the_default() -> None:
    settings = WorkerRunConfig(concurrency_enabled=True).concurrency_settings()
    assert settings.enabled is True


def test_serial_settings_report_a_global_limit_of_one() -> None:
    assert ConcurrencySettings.serial().effective_global_limit() == 1


def test_conservative_settings_are_below_nominal() -> None:
    conservative = ConcurrencySettings.conservative()
    nominal = ConcurrencySettings()
    assert conservative.max_concurrent_tasks <= nominal.max_concurrent_tasks
    assert conservative.research_workers <= nominal.research_workers


# ── correcciones de revisión (2026-07-31) ───────────────────────────────


def test_file_writing_task_is_not_classified_as_read_only() -> None:
    """`write_governed_text_artifact` escribe ficheros: no es read-only.

    Estuvo en el carril `read_only` con concurrencia 4, que era sencillamente
    falso. Cuatro escrituras simultaneas podian apuntar al mismo `target`.
    """
    policy = policy_for("write_governed_text_artifact")
    assert policy.lane != "read_only"
    assert policy.lane == "memory_write"
    assert policy.max_concurrency == 1
    assert "target" in policy.exclusive_keys


def test_two_writes_to_the_same_file_cannot_overlap() -> None:
    """Doble barrera: el carril ya es serial, y ademas la clave por `target`.

    El carril gana primero (`lane_limit`), asi que la clave nunca llega a ser el
    motivo del rechazo. Se conserva igualmente: si alguien subiera
    `memory_write_workers`, la exclusion por fichero seguiria impidiendo que dos
    escrituras apunten al mismo `target`.
    """
    registry = _registry(max_concurrent_tasks=8, memory_write_workers=4)
    payload = {"target": "/tmp/x.md", "authorized_root": "/tmp"}
    assert registry.try_admit("w1", "write_governed_text_artifact", payload).admitted
    denied = registry.try_admit("w2", "write_governed_text_artifact", dict(payload))
    assert not denied.admitted
    assert denied.reason in {"lane_limit", "exclusive_key_held:target=/tmp/x.md"}
    # La clave esta tomada aunque no sea la que rechazo.
    assert registry.holds_key("target=/tmp/x.md")


def test_every_effectful_lane_is_serial() -> None:
    """Ningun carril que escriba estado puede admitir mas de una a la vez."""
    for task_type, policy in TASK_CONCURRENCY_POLICY.items():
        if policy.lane in {"memory_write", "critical_mutation"}:
            assert policy.max_concurrency == 1, task_type
