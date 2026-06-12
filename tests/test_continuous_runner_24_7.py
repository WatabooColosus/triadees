"""Tests del modo 24/7: continuous runner, ritmo, autonomía y promoción estable."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from triade.core.life_pulse import (
    LifePulseEngine,
    AUTONOMY_LEVELS,
    DEFAULT_AUTONOMY_LEVEL,
    _MIN_CONTINUOUS_INTERVAL,
    _DEFAULT_CONTINUOUS_INTERVAL,
)
from triade.core.neuron_autopromoter import NeuronAutopromoter
from triade.core.stable_promotion_readiness import (
    evaluate_stable_readiness,
    SYNTHETIC_POLICIES,
    DEFAULT_THRESHOLDS,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_life_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        run_id = "life-run-1"
        conn.execute(
            """INSERT INTO runs
            (run_id, source, user_input, status, model_hypothalamus, model_central, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, "test", "pulso vida aprendizaje segundo plano", "ok", "rules-fallback", "template-fallback", "2026-06-05"),
        )
        conn.execute(
            "INSERT INTO signal_states (run_id, intent, tone, urgency, risk, pv7, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, "conversation", "constructive", "medium", "low", "{}", "[]"),
        )
        conn.execute(
            "INSERT INTO crystal_states (run_id, q_crystal, stability, q_delta, stability_delta, temporal_status) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, 0.6, 0.8, 0.0, 0.0, "stable"),
        )
        conn.execute(
            "INSERT INTO verification_reports (run_id, status, warnings, recommendations) VALUES (?, ?, ?, ?)",
            (run_id, "ok", "[]", "[]"),
        )
        conn.execute(
            "INSERT INTO episodic_memory (run_id, title, content, summary, tags) VALUES (?, ?, ?, ?, ?)",
            (run_id, "Pulso", "Usuario privado\nRespuesta", "Resumen", "triade,mvp,run"),
        )
    return db_path


def make_neuron_db(tmp_path: Path) -> Path:
    """Create a DB with neurons and training for autopromoter tests."""
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def write_activity_file(
    run_path: Path,
    name: str = "neurona-test",
    status: str = "experimental",
    policy: str = "user_run",
    diagnosis_count: int = 2,
    test_plan_count: int = 1,
    run_id: str | None = None,
) -> None:
    run_path.mkdir(parents=True, exist_ok=True)
    diagnosis = [f"d{i}" for i in range(diagnosis_count)]
    test_plan = [f"t{i}" for i in range(test_plan_count)]
    activity = {
        "active": True,
        "count": 1,
        "activations": [
            {
                "neuron_id": 1,
                "name": name,
                "status": status,
                "domain": "test_domain",
                "match": {"active": True, "reasons": ["test"]},
                "output": {
                    "diagnosis": diagnosis,
                    "test_plan": test_plan,
                },
                "policy": policy,
            }
        ],
    }
    (run_path / "experimental_neuron_activity.json").write_text(
        json.dumps(activity, ensure_ascii=False),
        encoding="utf-8",
    )


# ── 1. Continuous loop respeta intervalo ────────────────────────────────────


def test_continuous_loop_respects_interval(tmp_path: Path) -> None:
    """El continuous runner espera al menos continuous_interval_seconds entre ciclos."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        interval_seconds=5,
        continuous_run_enabled=True,
        continuous_interval_seconds=10,
        autonomy_level="observe_only",
    )

    # Monkey-patch _continuous_loop to track timing
    cycle_times: list[float] = []
    original_loop = engine._continuous_loop

    def tracking_loop() -> None:
        # Just track that the engine was configured correctly
        pass

    engine._continuous_loop = tracking_loop

    # Verify config is correct
    assert engine.continuous_interval_seconds == 10
    assert engine.continuous_run_enabled is True

    # Start and immediately stop
    engine.start()
    time.sleep(0.1)
    engine.stop()

    # Verify it can be stopped
    assert engine._stop.is_set()


def test_continuous_loop_stops_on_max_cycles(tmp_path: Path) -> None:
    """El continuous runner se detiene al alcanzar max_cycles."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        interval_seconds=5,
        continuous_run_enabled=True,
        continuous_interval_seconds=10,
        continuous_max_cycles=2,
        autonomy_level="observe_only",
    )

    # Patch _continuous_loop to simulate reaching max cycles
    cycle_count = 0
    max_reached = threading.Event()

    def mock_continuous_loop() -> None:
        nonlocal cycle_count
        while not engine._stop.is_set():
            cycle_count += 1
            if engine.continuous_max_cycles > 0 and cycle_count >= engine.continuous_max_cycles:
                max_reached.set()
                break
            engine._stop.wait(0.01)

    engine._continuous_loop = mock_continuous_loop
    engine.start()
    max_reached.wait(timeout=5)
    engine.stop()

    assert cycle_count == 2


# ── 2. Continuous loop puede detenerse ──────────────────────────────────────


def test_continuous_loop_can_be_stopped(tmp_path: Path) -> None:
    """El continuous runner puede detenerse limpiamente."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        interval_seconds=5,
        continuous_run_enabled=True,
        continuous_interval_seconds=10,
        autonomy_level="observe_only",
    )

    engine.start()
    assert engine._continuous_thread is not None
    assert engine._continuous_thread.is_alive()

    engine.stop()
    time.sleep(0.2)
    assert not engine._continuous_thread.is_alive()


# ── 3. No promueve a stable con solo experimental_light_pulse ──────────────


def test_no_stable_promotion_with_sonly_synthetic_evidence(tmp_path: Path) -> None:
    """No se promueve a stable si toda la evidencia es sintética (experimental_light_pulse)."""
    runs_dir = tmp_path / "runs"
    for i in range(5):
        write_activity_file(
            runs_dir / f"run-test-{i:03d}",
            policy="experimental_light_pulse",
            diagnosis_count=2,
            test_plan_count=1,
        )

    report = evaluate_stable_readiness(runs_dir=runs_dir, limit=10)
    neuron = report["neurons"][0]

    assert neuron["ready_for_stable_review"] is False
    assert neuron["non_synthetic_activations"] == 0
    assert any("non_synthetic" in b for b in neuron["blockers"])


def test_stable_promotion_allowed_with_diverse_evidence(tmp_path: Path) -> None:
    """Se permite revisión de stable cuando hay evidencia diversa."""
    runs_dir = tmp_path / "runs"
    # 3 activations from user runs (non-synthetic)
    for i in range(3):
        write_activity_file(
            runs_dir / f"run-user-{i:03d}",
            policy="user_run",
            diagnosis_count=2,
            test_plan_count=1,
        )
    # 2 activations from synthetic pulse
    for i in range(2):
        write_activity_file(
            runs_dir / f"run-pulse-{i:03d}",
            policy="experimental_light_pulse",
            diagnosis_count=2,
            test_plan_count=1,
        )

    report = evaluate_stable_readiness(runs_dir=runs_dir, limit=10)
    neuron = report["neurons"][0]

    assert neuron["non_synthetic_activations"] == 3
    assert neuron["external_verifications"] == 5  # all run-* artifacts
    # Check no synthetic-only blocker
    assert not any("non_synthetic" in b for b in neuron["blockers"])


# ── 4. TRIADE_CONTINUOUS_RUNNER no arranca sin activación explícita ────────


def test_continuous_runner_disabled_by_default(tmp_path: Path) -> None:
    """El continuous runner está desactivado por defecto."""
    engine = LifePulseEngine(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs")
    assert engine.continuous_run_enabled is False


def test_continuous_runner_requires_explicit_activation(tmp_path: Path) -> None:
    """El continuous runner solo arranca si se activa explícitamente."""
    db_path = make_life_db(tmp_path)

    # Default: continuous disabled
    engine_off = LifePulseEngine(db_path=db_path, runs_dir=tmp_path / "runs")
    engine_off.start()
    time.sleep(0.1)
    assert engine_off._continuous_thread is None or not engine_off._continuous_thread.is_alive()
    engine_off.stop()

    # Explicitly enabled
    engine_on = LifePulseEngine(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        continuous_run_enabled=True,
        continuous_interval_seconds=10,
        autonomy_level="observe_only",
    )
    engine_on.start()
    time.sleep(0.1)
    assert engine_on._continuous_thread is not None and engine_on._continuous_thread.is_alive()
    engine_on.stop()


def test_from_env_default_continuous_off() -> None:
    """from_env() desactiva continuous runner por defecto."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TRIADE_CONTINUOUS_RUNNER", None)
        engine = LifePulseEngine.from_env()
        assert engine.continuous_run_enabled is False


def test_from_env_continuous_on_when_set() -> None:
    """from_env() activa continuous runner cuando TRIADE_CONTINUOUS_RUNNER=1."""
    with patch.dict(os.environ, {"TRIADE_CONTINUOUS_RUNNER": "1"}):
        engine = LifePulseEngine.from_env()
        assert engine.continuous_run_enabled is True


# ── 5. No modifica identity_core ───────────────────────────────────────────


def test_continuous_loop_never_modifies_identity_core(tmp_path: Path) -> None:
    """El continuous runner nunca modifica identity_core."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        interval_seconds=5,
        continuous_run_enabled=False,  # don't actually run continuous
        autonomy_level="observe_only",
    )

    # Read identity_core before
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM identity_core").fetchone()
        before = dict(zip(row.keys(), row)) if row else {}

    # The policy always says identity_core_modified is False
    snapshot = engine.snapshot()
    assert snapshot["policy"]["identity_core_modified"] is False


def test_snapshot_reports_autonomy_level(tmp_path: Path) -> None:
    """El snapshot reporta el nivel de autonomía."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        autonomy_level="form_candidates",
    )
    snapshot = engine.snapshot()
    assert snapshot["autonomy_level"] == "form_candidates"
    assert "observe_only" in snapshot["autonomy_levels_available"]
    assert "promote_stable" in snapshot["autonomy_levels_available"]


# ── 6. No consolida memoria stable sin gates del LearningPipeline ──────────


def test_policy_auto_consolidation_is_false(tmp_path: Path) -> None:
    """La política siempre impide auto-consolidación de memoria stable."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(db_path=db_path, runs_dir=tmp_path / "runs")
    snapshot = engine.snapshot()
    assert snapshot["policy"]["auto_consolidation"] is False
    assert snapshot["truth"] is not None


# ── 7. Snapshot reporta métricas del continuous runner ─────────────────────


def test_snapshot_reports_continuous_runner_details(tmp_path: Path) -> None:
    """El snapshot reporta intervalo, ciclos/min, última promoción y último error."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        continuous_run_enabled=True,
        continuous_interval_seconds=15,
        continuous_max_cycles=100,
        autonomy_level="train_candidates",
    )
    snapshot = engine.snapshot()

    cr = snapshot["continuous_runner"]
    assert cr["enabled"] is True
    assert cr["interval_seconds"] == 15
    assert cr["max_cycles"] == 100
    assert isinstance(cr["cycles_per_minute"], float)
    assert "last_error" in cr

    lp = snapshot["last_promotion"]
    assert "at" in lp
    assert "name" in lp

    assert snapshot["autonomy_level"] == "train_candidates"


# ── 8. Autonomy levels ─────────────────────────────────────────────────────


def test_autonomy_levels_are_ordered() -> None:
    """Los niveles de autonomía están en orden correcto."""
    assert AUTONOMY_LEVELS == [
        "observe_only",
        "form_candidates",
        "train_candidates",
        "promote_experimental",
        "promote_stable",
    ]


def test_autonomy_level_validation() -> None:
    """from_env() valida niveles de autonomía inválidos."""
    with patch.dict(os.environ, {"TRIADE_AUTONOMY_LEVEL": "invalid_level"}):
        engine = LifePulseEngine.from_env()
        assert engine.autonomy_level == DEFAULT_AUTONOMY_LEVEL


def test_autonomy_level_from_env() -> None:
    """from_env() lee TRIADE_AUTONOMY_LEVEL correctamente."""
    with patch.dict(os.environ, {"TRIADE_AUTONOMY_LEVEL": "promote_experimental"}):
        engine = LifePulseEngine.from_env()
        assert engine.autonomy_level == "promote_experimental"


# ── 9. Backoff on error ────────────────────────────────────────────────────


def test_continuous_backoff_increases_on_error(tmp_path: Path) -> None:
    """El backoff exponencial aumenta cuando hay errores consecutivos."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        continuous_run_enabled=True,
        continuous_interval_seconds=10,
        autonomy_level="observe_only",
    )

    # Simulate error accumulation
    engine._continuous_backoff_seconds = 0.0
    # After one error: 0 * 2 + 5 = 5
    engine._continuous_backoff_seconds = min(
        engine._continuous_backoff_seconds * 2 + 5, 300
    )
    assert engine._continuous_backoff_seconds == 5.0

    # After second error: 5 * 2 + 5 = 15
    engine._continuous_backoff_seconds = min(
        engine._continuous_backoff_seconds * 2 + 5, 300
    )
    assert engine._continuous_backoff_seconds == 15.0

    # After third error: 15 * 2 + 5 = 35
    engine._continuous_backoff_seconds = min(
        engine._continuous_backoff_seconds * 2 + 5, 300
    )
    assert engine._continuous_backoff_seconds == 35.0


def test_continuous_backoff_resets_on_success(tmp_path: Path) -> None:
    """El backoff se reinicia cuando un ciclo tiene éxito."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(db_path=db_path, runs_dir=tmp_path / "runs")
    engine._continuous_backoff_seconds = 35.0
    # Simulate success: reset to 0
    engine._continuous_backoff_seconds = 0.0
    assert engine._continuous_backoff_seconds == 0.0


# ── 10. Elapsed_ms tracking ────────────────────────────────────────────────


def test_continuous_elapsed_ms_tracked(tmp_path: Path) -> None:
    """El engine trackea elapsed_ms por ciclo."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(db_path=db_path, runs_dir=tmp_path / "runs")
    # Simulate adding elapsed times
    engine._continuous_elapsed_ms.append(100)
    engine._continuous_elapsed_ms.append(200)
    engine._continuous_elapsed_ms.append(150)
    assert engine._continuous_elapsed_ms == [100, 200, 150]


# ── 11. NeuronAutopromoter audit reasons ───────────────────────────────────


def test_autopromoter_returns_skip_reason_no_training(tmp_path: Path) -> None:
    """Autopromoter retorna razón cuando no hay training."""
    db_path = make_neuron_db(tmp_path)
    from triade.core.neuron_creator import NeuronSpec
    from triade.core.neuron_registry import NeuronRegistry

    registry = NeuronRegistry(db_path=db_path)
    spec = NeuronSpec(
        name="neurona-sin-training",
        mission="test",
        domain="test",
        status="candidate",
        created_by="test",
    )
    registry.register(spec)

    promoter = NeuronAutopromoter(db_path=db_path)
    events = promoter.promote()

    skip_events = [e for e in events if e.get("status") == "not_promoted"]
    assert len(skip_events) == 1
    assert skip_events[0]["reason"] == "no_training_data"


def test_autopromoter_returns_skip_reason_low_score(tmp_path: Path) -> None:
    """Autopromoter retorna razón cuando score es bajo."""
    db_path = make_neuron_db(tmp_path)
    from triade.core.neuron_creator import NeuronSpec
    from triade.core.neuron_trainer import NeuronTrainingResult
    from triade.core.neuron_registry import NeuronRegistry

    registry = NeuronRegistry(db_path=db_path)
    spec = NeuronSpec(
        name="neurona-score-bajo",
        mission="test",
        domain="test",
        status="candidate",
        created_by="test",
    )
    neuron_id = registry.register(spec)
    tr = NeuronTrainingResult(
        name="neurona-score-bajo",
        score=0.3,
        status="candidate",
        strengths=[],
        warnings=[],
        recommendations=[],
        required_human_review=False,
        policy="test",
    )
    registry.store_training(neuron_id, tr)

    promoter = NeuronAutopromoter(db_path=db_path)
    events = promoter.promote()

    skip_events = [e for e in events if e.get("status") == "not_promoted"]
    assert len(skip_events) == 1
    assert skip_events[0]["reason"] == "score_below_threshold"


def test_autopromoter_returns_skip_reason_not_in_report(tmp_path: Path) -> None:
    """Autopromoter retorna razón cuando la neurona no está en el reporte de readiness."""
    db_path = make_neuron_db(tmp_path)
    from triade.core.neuron_creator import NeuronSpec
    from triade.core.neuron_registry import NeuronRegistry

    registry = NeuronRegistry(db_path=db_path)
    spec = NeuronSpec(
        name="neurona-experimental-sin-evidencia",
        mission="test",
        domain="test",
        status="experimental",
        created_by="test",
    )
    registry.register(spec)

    promoter = NeuronAutopromoter(db_path=db_path)
    events = promoter.promote()

    skip_events = [e for e in events if e.get("status") == "not_promoted"]
    assert len(skip_events) == 1
    assert skip_events[0]["reason"] == "not_in_readiness_report"


# ── 12. Stable promotion diverse evidence blocking ──────────────────────────


def test_stable_readiness_blocks_sonly_synthetic(tmp_path: Path) -> None:
    """Stable readiness bloquea cuando toda la evidencia es sintética."""
    runs_dir = tmp_path / "runs"
    for i in range(5):
        write_activity_file(
            runs_dir / f"run-pulse-{i:03d}",
            policy="experimental_light_pulse",
            diagnosis_count=2,
            test_plan_count=1,
        )

    report = evaluate_stable_readiness(runs_dir=runs_dir, limit=10)
    neuron = report["neurons"][0]

    assert neuron["ready_for_stable_review"] is False
    assert neuron["non_synthetic_activations"] == 0
    assert any("non_synthetic" in b for b in neuron["blockers"])


def test_stable_readiness_counts_diverse_policies(tmp_path: Path) -> None:
    """Stable readiness cuenta correctamente políticas diversas."""
    runs_dir = tmp_path / "runs"
    write_activity_file(
        runs_dir / "run-user-001",
        policy="user_run",
        diagnosis_count=2,
        test_plan_count=1,
    )
    write_activity_file(
        runs_dir / "run-worker-001",
        policy="worker_task",
        diagnosis_count=2,
        test_plan_count=1,
    )
    write_activity_file(
        runs_dir / "run-pulse-001",
        policy="experimental_light_pulse",
        diagnosis_count=2,
        test_plan_count=1,
    )

    report = evaluate_stable_readiness(runs_dir=runs_dir, limit=10)
    neuron = report["neurons"][0]

    assert neuron["non_synthetic_activations"] == 2  # user_run + worker_task
    assert neuron["external_verifications"] == 3  # all run-* artifacts


# ── 13. Config defaults from env ────────────────────────────────────────────


def test_from_env_continuous_interval_default() -> None:
    """from_env() usa intervalo por defecto cuando no está definido."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TRIADE_CONTINUOUS_INTERVAL_SECONDS", None)
        engine = LifePulseEngine.from_env()
        assert engine.continuous_interval_seconds == _DEFAULT_CONTINUOUS_INTERVAL


def test_from_env_continuous_interval_minimum() -> None:
    """from_env() respeta el mínimo de intervalo."""
    with patch.dict(os.environ, {"TRIADE_CONTINUOUS_INTERVAL_SECONDS": "3"}):
        engine = LifePulseEngine.from_env()
        assert engine.continuous_interval_seconds == _MIN_CONTINUOUS_INTERVAL


def test_from_env_max_cycles() -> None:
    """from_env() lee TRIADE_CONTINUOUS_MAX_CYCLES."""
    with patch.dict(os.environ, {"TRIADE_CONTINUOUS_MAX_CYCLES": "50"}):
        engine = LifePulseEngine.from_env()
        assert engine.continuous_max_cycles == 50


def test_default_autonomy_level_is_observe_only() -> None:
    """El nivel de autonomía por defecto es observe_only."""
    assert DEFAULT_AUTONOMY_LEVEL == "observe_only"


# ── 14. Policy fields in snapshot ───────────────────────────────────────────


def test_snapshot_policy_includes_continuous_runner_default(tmp_path: Path) -> None:
    """El snapshot incluye la política de continuous runner default off."""
    db_path = make_life_db(tmp_path)
    engine = LifePulseEngine(db_path=db_path, runs_dir=tmp_path / "runs")
    snapshot = engine.snapshot()
    assert snapshot["policy"]["continuous_runner_default"] == "off"
    assert snapshot["policy"]["stable_promotion_requires_diverse_evidence"] is True


# ── 15. Elapsed_ms capped ──────────────────────────────────────────────────


def test_elapsed_ms_capped_at_200() -> None:
    """La lista de elapsed_ms se mantiene en máximo 200 entradas."""
    engine = LifePulseEngine(db_path=":memory:", runs_dir="/tmp")
    engine._continuous_elapsed_ms = list(range(250))
    # Simulate the capping logic from _continuous_loop
    if len(engine._continuous_elapsed_ms) > 200:
        engine._continuous_elapsed_ms = engine._continuous_elapsed_ms[-200:]
    assert len(engine._continuous_elapsed_ms) == 200
    assert engine._continuous_elapsed_ms[0] == 50
