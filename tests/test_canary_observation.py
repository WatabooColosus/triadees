"""El canary acumula observaciones reales entre ciclos, sin contar dos veces.

Las puntuaciones salen de `verification_reports`, la misma tabla que usa
`VitalityEvaluationProvider`. Aquí se insertan a mano porque el objetivo es
probar la mecánica de acumulación, no la medición: eso se prueba contra datos
reales en la validación E2E.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from triade.evaluation.provider_registry import (
    EVALUATION_PROVIDERS,
    build_evaluation_provider,
)
from triade.self_improvement.canary_observation import CanaryObservationCollector


def _seed_reports(db_path: Path, scores: list[float], *, base: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS verification_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT, scope TEXT, status TEXT, score REAL,
            coherence_score REAL, memory_score REAL, safety_score REAL,
            usefulness_score REAL, traceability_score REAL,
            findings TEXT, errors TEXT, warnings TEXT, recommendations TEXT,
            created_at TEXT)"""
    )
    for index, score in enumerate(scores):
        conn.execute(
            """INSERT INTO verification_reports
            (run_id, status, coherence_score, memory_score, safety_score,
             usefulness_score, traceability_score, created_at)
            VALUES (?, 'ok', ?, ?, ?, ?, ?, ?)""",
            (
                f"run-{base}-{index}",
                score,
                score,
                score,
                score,
                score,
                f"{base}{index:03d}",
            ),
        )
    conn.commit()
    conn.close()


def _open_canary(
    db_path: Path,
    *,
    baseline: float = 0.9,
    tolerance: float = 0.02,
    minimum: int = 2,
    maximum: int = 3,
) -> str:
    """Inserta un canary 'running' directamente.

    `CanaryMonitor.start()` exige una candidata promovida real, que arrastraría
    media fábrica de neuronas a un test cuyo objeto es la acumulación. La tabla
    la crea el propio CanaryMonitor.
    """
    CanaryObservationCollector(db_path)
    now = time.time()
    conn = sqlite3.connect(db_path)
    payload = '{"canary_id": "canary-test", "status": "running"}'
    conn.execute(
        """INSERT INTO improvement_canaries
        (canary_id, candidate_id, status, baseline_score, tolerance,
         traffic_percent, min_observations, max_observations,
         payload_json, created_at, updated_at)
        VALUES ('canary-test', 'cand-test', 'running', ?, ?, 10, ?, ?, ?, ?, ?)""",
        (baseline, tolerance, minimum, maximum, payload, now, now),
    )
    conn.commit()
    conn.close()
    return "canary-test"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "triade.db"


# ── sin evidencia ───────────────────────────────────────────────────────


def test_no_canary_is_not_an_error(db_path: Path) -> None:
    result = CanaryObservationCollector(db_path).observe_once()
    assert result["status"] == "no_canary"


def test_canary_without_new_reports_defers(db_path: Path) -> None:
    """Sin informes nuevos no se decide nada. No es un fallo."""
    _open_canary(db_path)
    _seed_reports(db_path, [0.9], base="2020-01-01T00:00:")  # anteriores al canary
    result = CanaryObservationCollector(db_path).observe_once()
    assert result["status"] == "insufficient_candidate_observations"


def test_reports_before_the_canary_are_ignored(db_path: Path) -> None:
    """Un informe anterior no dice nada sobre la candidata: no existía."""
    _open_canary(db_path)
    _seed_reports(db_path, [0.1, 0.1, 0.1], base="1999-01-01T00:00:")
    result = CanaryObservationCollector(db_path).observe_once()
    assert result["status"] == "insufficient_candidate_observations"
    # Y no ha disparado ningun rollback pese a las puntuaciones pesimas.
    assert result.get("rollback") is None


# ── acumulación ─────────────────────────────────────────────────────────


def test_canary_stays_running_until_the_window_closes(db_path: Path) -> None:
    _open_canary(db_path, baseline=0.9, minimum=2, maximum=5)
    _seed_reports(db_path, [0.91], base="2999-01-01T00:00:")
    result = CanaryObservationCollector(db_path).observe_once()
    assert result["status"] == "running"
    assert result["observation_count"] == 1
    assert result["eligible_for_stable_promotion"] is False


def test_canary_graduates_when_it_survives_the_window(db_path: Path) -> None:
    _open_canary(db_path, baseline=0.9, minimum=2, maximum=3)
    _seed_reports(db_path, [0.92, 0.93, 0.94], base="2999-01-01T00:00:")
    result = CanaryObservationCollector(db_path).observe_once()
    assert result["status"] == "graduated"
    assert result["eligible_for_stable_promotion"] is True
    # Graduar NO es promover. La consolidacion estable es otro carril.
    assert result["stable_promotion_performed"] is False


def test_degradation_triggers_rollback_and_never_graduation(db_path: Path) -> None:
    """Degradacion sostenida bajo el umbral: intenta revertir, jamas graduar.

    Con una candidata sintetica el rollback real no puede completarse
    —`NeuronLifecycleManager` exige una especificacion promovida de verdad— y
    eso es exactamente lo que se comprueba aqui: el intento ocurre y falla
    ruidosamente con `KeyError`, en vez de tragarse el error y dejar viva una
    candidata degradada. El rollback completo se ejercita en la validacion E2E,
    donde si hay candidata real.
    """
    _open_canary(db_path, baseline=0.9, tolerance=0.02, minimum=2, maximum=5)
    _seed_reports(db_path, [0.50, 0.50], base="2999-01-01T00:00:")
    collector = CanaryObservationCollector(db_path)
    with pytest.raises(KeyError, match="candidato no registrado"):
        collector.observe_once()
    canary = collector.active_canary()
    assert canary is None or str(canary["status"]) != "graduated"


# ── idempotencia ────────────────────────────────────────────────────────


def test_the_same_report_is_never_counted_twice(db_path: Path) -> None:
    """La garantia vive en la clave primaria, no en una comprobacion."""
    _open_canary(db_path, baseline=0.9, minimum=2, maximum=10)
    _seed_reports(db_path, [0.91, 0.92], base="2999-01-01T00:00:")
    collector = CanaryObservationCollector(db_path)

    first = collector.observe_once()
    assert first["observation_count"] == 2

    # Segunda pasada sin informes nuevos: no puede inflar la evidencia.
    second = collector.observe_once()
    assert second["status"] == "insufficient_candidate_observations"

    conn = sqlite3.connect(db_path)
    total = conn.execute(
        "SELECT COUNT(*) FROM improvement_canary_observations"
    ).fetchone()[0]
    consumed = conn.execute(
        "SELECT COUNT(*) FROM improvement_canary_consumed_reports"
    ).fetchone()[0]
    conn.close()
    assert total == 2
    assert consumed == 2


def test_reserving_the_same_report_twice_is_refused(db_path: Path) -> None:
    _open_canary(db_path)
    collector = CanaryObservationCollector(db_path)
    assert collector._reserve("canary-test", 42, 0.9)
    assert not collector._reserve("canary-test", 42, 0.9)


def test_max_reports_bounds_how_fast_a_canary_can_graduate(db_path: Path) -> None:
    """Volcar cincuenta informes de golpe saltaria de recien abierto a graduado."""
    _open_canary(db_path, baseline=0.9, minimum=2, maximum=10)
    _seed_reports(db_path, [0.91] * 8, base="2999-01-01T00:00:")
    result = CanaryObservationCollector(db_path).observe_once(max_reports=3)
    assert result["observation_count"] == 3
    assert result["status"] == "running"


# ── registro cerrado de providers ───────────────────────────────────────


def test_only_authorised_providers_resolve(db_path: Path) -> None:
    provider = build_evaluation_provider("triade_vitality", db_path)
    assert callable(provider)


def test_an_arbitrary_provider_name_is_refused(db_path: Path) -> None:
    """Una propuesta no puede elegir su propio examinador."""
    with pytest.raises(ValueError, match="no autorizado"):
        build_evaluation_provider("mi_propio_evaluador", db_path)


def test_the_registry_is_small_and_explicit() -> None:
    assert set(EVALUATION_PROVIDERS) == {"triade_vitality"}


def test_empty_provider_name_falls_back_to_the_default(db_path: Path) -> None:
    assert callable(build_evaluation_provider("", db_path))


# ── corrección de revisión (2026-07-31) ─────────────────────────────────


def test_observation_declares_that_attribution_is_only_temporal(db_path: Path) -> None:
    """El resultado debe confesar que no prueba que la candidata se usara.

    Los informes se eligen por ser posteriores al canary. Sin enrutado de
    trafico por candidata, eso es correlacion, no causa. Quien lea el resultado
    tiene que saberlo sin ir a leer el codigo.
    """
    _open_canary(db_path, baseline=0.9, minimum=2, maximum=5)
    _seed_reports(db_path, [0.91], base="2999-01-01T00:00:")
    result = CanaryObservationCollector(db_path).observe_once()
    assert result["causal_attribution"] == "temporal_only"
    assert "no se demuestra" in result["causal_attribution_note"]


def test_temporal_attribution_never_authorises_a_promotion(db_path: Path) -> None:
    """Revertir por correlacion es barato; promover por correlacion, no."""
    _open_canary(db_path, baseline=0.9, minimum=2, maximum=3)
    _seed_reports(db_path, [0.92, 0.93, 0.94], base="2999-01-01T00:00:")
    result = CanaryObservationCollector(db_path).observe_once()
    assert result["status"] == "graduated"
    assert result["stable_promotion_performed"] is False
    assert result["causal_attribution"] == "temporal_only"
