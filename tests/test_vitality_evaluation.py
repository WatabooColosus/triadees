"""La suite de vitalidad y su provider: la vara con la que Tríade se mide.

Fija por contrato la definición de "mejor" dada por el responsable del proyecto,
para que ningún cambio futuro la relaje en silencio.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.evaluation.contracts import EvaluationRun, MetricResult
from triade.evaluation.triade_vitality_suite import (
    SUITE_ID,
    SUITE_VERSION,
    TRIADE_VITALITY_SUITE,
    build_vitality_registry,
)
from triade.evaluation.vitality_provider import VitalityEvaluationProvider
from triade.regression.gate import RegressionGate

BASE = {
    "coherence": 0.74,
    "memory": 0.90,
    "safety": 0.88,
    "usefulness": 0.85,
    "traceability": 0.95,
}


def _run(evaluation_id: str, scores: dict[str, float]) -> EvaluationRun:
    return EvaluationRun(
        evaluation_id=evaluation_id,
        suite_id=SUITE_ID,
        suite_version=SUITE_VERSION,
        subject_id="cand",
        results=tuple(
            MetricResult(case_id=k, score=v, passed=v >= 0.6, actual=v, expected=0.6)
            for k, v in sorted(scores.items())
        ),
        aggregate_score=sum(scores.values()) / len(scores),
        created_at="2026-07-31T04:00:00Z",
    )


# ── La vara no se puede reescribir, pero sí evolucionar ────────────────


def test_una_version_publicada_es_inmutable():
    registry = build_vitality_registry()
    with pytest.raises(ValueError):
        registry.register(TRIADE_VITALITY_SUITE)


def test_el_sistema_puede_evolucionar_publicando_una_version_nueva():
    from dataclasses import replace

    registry = build_vitality_registry()
    registry.register(replace(TRIADE_VITALITY_SUITE, version="2.0.0"))
    assert registry.latest(SUITE_ID).version == "2.0.0"
    # la versión histórica sigue intacta como suelo
    assert registry.get(SUITE_ID, SUITE_VERSION).version == SUITE_VERSION


# ── Tolerancia cero donde el responsable la exigió ─────────────────────


def test_trazabilidad_y_safety_tienen_tolerancia_cero_efectiva():
    """Cero real frente a cambios reales, pero inmune a ruido de coma flotante.

    Un `0.0` literal es inusable: promediar conjuntos distintos de runs produce
    diferencias de ~1e-15 aunque los valores sean idénticos, y eso reprobaba todo.
    """
    from triade.evaluation.triade_vitality_suite import FLOAT_NOISE

    policies = {p.metric_id: p for p in TRIADE_VITALITY_SUITE.policies()}
    for metric in ("traceability", "safety"):
        assert policies[metric].max_absolute_drop == FLOAT_NOISE
        assert policies[metric].max_relative_drop == FLOAT_NOISE
        assert policies[metric].severity == "critical"
        # sigue siendo cero frente a cualquier degradación real
        assert policies[metric].max_absolute_drop < 1e-6


def test_ninguna_metrica_deja_el_umbral_relativo_en_cero(tmp_path: Path):
    """El gate reprueba si CUALQUIERA de los dos umbrales se supera.

    Dejar `max_relative_drop=0.0` anula silenciosamente la tolerancia absoluta:
    cualquier caída, por diminuta que sea, tiene caída relativa > 0.
    """
    for policy in TRIADE_VITALITY_SUITE.policies():
        assert policy.max_relative_drop > 0.0, policy.metric_id


def test_ruido_de_coma_flotante_no_reprueba(tmp_path: Path):
    """Regresión del fallo hallado en la primera ejecución real."""
    gate = RegressionGate(tmp_path / "g.db")
    ruido = {**BASE, "traceability": BASE["traceability"] - 1.3e-15}
    report = gate.evaluate(
        report_id="r-ruido",
        candidate_id="c",
        capability="triade_vitality",
        baseline=_run("b", BASE),
        candidate=_run("k", ruido),
        policies=TRIADE_VITALITY_SUITE.policies(),
    )
    assert report.decision == "pass"


@pytest.mark.parametrize("metric", ["traceability", "safety"])
def test_perder_las_bases_solidas_reprueba(tmp_path: Path, metric: str):
    gate = RegressionGate(tmp_path / "g.db")
    degradado = {**BASE, metric: BASE[metric] - 0.03}
    report = gate.evaluate(
        report_id=f"r-{metric}",
        candidate_id="c",
        capability="triade_vitality",
        baseline=_run("b", BASE),
        candidate=_run("k", degradado),
        policies=TRIADE_VITALITY_SUITE.policies(),
    )
    assert report.decision == "fail"


def test_mejorar_sin_perder_nada_aprueba(tmp_path: Path):
    gate = RegressionGate(tmp_path / "g.db")
    mejor = {**BASE, "coherence": 0.85, "memory": 0.93}
    report = gate.evaluate(
        report_id="r-ok",
        candidate_id="c",
        capability="triade_vitality",
        baseline=_run("b", BASE),
        candidate=_run("k", mejor),
        policies=TRIADE_VITALITY_SUITE.policies(),
    )
    assert report.decision == "pass"


# ── El provider exige evidencia real, no adivina ───────────────────────


def _seed(db: Path, count: int, created_prefix: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS verification_reports (
                run_id TEXT, status TEXT, coherence_score REAL, memory_score REAL,
                safety_score REAL, usefulness_score REAL, traceability_score REAL,
                created_at TEXT)"""
        )
        for i in range(count):
            conn.execute(
                "INSERT INTO verification_reports VALUES (?,?,?,?,?,?,?,?)",
                (
                    f"run-{i}",
                    "ok",
                    0.74,
                    0.90,
                    0.88,
                    0.85,
                    0.95,
                    f"{created_prefix}{i:02d}",
                ),
            )


def test_sin_corte_temporal_se_niega_a_comparar(tmp_path: Path):
    db = tmp_path / "t.db"
    _seed(db, 20, "2026-07-30T10:")
    provider = VitalityEvaluationProvider(db)
    with pytest.raises(ValueError, match="created_at"):
        provider("cand", {})


def test_evidencia_insuficiente_falla_en_vez_de_adivinar(tmp_path: Path):
    db = tmp_path / "t.db"
    _seed(db, 4, "2026-07-30T10:")  # menos que min_runs
    provider = VitalityEvaluationProvider(db, min_runs=10)
    with pytest.raises(ValueError, match="insuficiente"):
        provider("cand", {"created_at": "2026-07-30T10:02"})


def test_con_evidencia_suficiente_produce_runs_validos(tmp_path: Path):
    db = tmp_path / "t.db"
    _seed(db, 12, "2026-07-30T10:")  # baseline
    _seed(db, 12, "2026-07-30T20:")  # candidate
    provider = VitalityEvaluationProvider(db, window=40, min_runs=10)
    baseline, candidate, policies = provider("cand", {"created_at": "2026-07-30T20:00"})
    assert baseline.suite_id == SUITE_ID
    assert candidate.suite_version == SUITE_VERSION
    assert {r.case_id for r in candidate.results} == set(BASE)
    assert len(policies) == 5
