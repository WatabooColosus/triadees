from __future__ import annotations

from pathlib import Path

import pytest

from triade.evaluation import EvaluationRun, MetricResult
from triade.regression import MetricPolicy, RegressionGate


def make_run(
    evaluation_id: str,
    scores: dict[str, float],
    *,
    suite_id: str = "critical-capabilities",
    suite_version: str = "1.0.0",
    subject_id: str = "candidate-subject",
) -> EvaluationRun:
    results = tuple(
        MetricResult(
            case_id=case_id,
            score=score,
            passed=score >= 0.5,
            actual=score,
            expected=1.0,
        )
        for case_id, score in scores.items()
    )
    return EvaluationRun(
        evaluation_id=evaluation_id,
        suite_id=suite_id,
        suite_version=suite_version,
        subject_id=subject_id,
        results=results,
        aggregate_score=sum(scores.values()) / len(scores),
        created_at="2026-07-11T00:00:00+00:00",
    )


def test_passes_when_protected_metrics_remain_inside_threshold(tmp_path: Path) -> None:
    gate = RegressionGate(tmp_path / "triade.db")
    baseline = make_run("baseline", {"identity": 1.0, "memory": 0.80})
    candidate = make_run("candidate", {"identity": 1.0, "memory": 0.79})

    report = gate.evaluate(
        report_id="report-pass",
        candidate_id="candidate-1",
        capability="learning",
        baseline=baseline,
        candidate=candidate,
        policies=(
            MetricPolicy("identity", severity="critical"),
            MetricPolicy(
                "memory",
                severity="high",
                max_absolute_drop=0.02,
                max_relative_drop=0.02,
            ),
        ),
    )

    assert report.decision == "pass"
    assert gate.require_pass("candidate-1").report_id == "report-pass"
    assert gate.is_quarantined("candidate-1") is False


def test_critical_regression_fails_and_quarantines(tmp_path: Path) -> None:
    gate = RegressionGate(tmp_path / "triade.db")
    baseline = make_run("baseline", {"identity": 1.0, "quality": 0.7})
    candidate = make_run("candidate", {"identity": 0.8, "quality": 0.9})

    report = gate.evaluate(
        report_id="report-fail",
        candidate_id="candidate-2",
        capability="learning",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("identity", severity="critical"),),
    )

    assert report.decision == "fail"
    assert report.blocking_findings[0].metric_id == "identity"
    assert gate.is_quarantined("candidate-2") is True
    with pytest.raises(ValueError, match="bloquea"):
        gate.require_pass("candidate-2")


def test_medium_regression_warns_without_automatic_pass(tmp_path: Path) -> None:
    gate = RegressionGate(tmp_path / "triade.db")
    baseline = make_run("baseline", {"style": 0.9})
    candidate = make_run("candidate", {"style": 0.7})

    report = gate.evaluate(
        report_id="report-warn",
        candidate_id="candidate-3",
        capability="style",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("style", severity="medium", max_absolute_drop=0.05),),
    )

    assert report.decision == "warn"
    assert gate.is_quarantined("candidate-3") is False
    with pytest.raises(ValueError, match="decision=warn"):
        gate.require_pass("candidate-3")


def test_incompatible_suite_is_invalid_and_quarantined(tmp_path: Path) -> None:
    gate = RegressionGate(tmp_path / "triade.db")
    baseline = make_run("baseline", {"identity": 1.0}, suite_version="1.0.0")
    candidate = make_run("candidate", {"identity": 1.0}, suite_version="2.0.0")

    report = gate.evaluate(
        report_id="report-invalid",
        candidate_id="candidate-4",
        capability="identity",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("identity", severity="critical"),),
    )

    assert report.decision == "invalid"
    assert gate.is_quarantined("candidate-4") is True


def test_missing_required_metric_is_invalid(tmp_path: Path) -> None:
    gate = RegressionGate(tmp_path / "triade.db")
    baseline = make_run("baseline", {"identity": 1.0})
    candidate = make_run("candidate", {"quality": 1.0})

    report = gate.evaluate(
        report_id="report-missing",
        candidate_id="candidate-5",
        capability="identity",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("identity", severity="critical", required=True),),
    )

    assert report.decision == "invalid"
    assert report.findings[0].status == "invalid"


def test_stable_state_provides_logical_rollback_target(tmp_path: Path) -> None:
    gate = RegressionGate(tmp_path / "triade.db")
    stable = make_run("stable-evaluation", {"identity": 1.0}, subject_id="stable-v1")

    gate.record_stable_state("identity", stable)
    target = gate.rollback_target("identity")

    assert target is not None
    assert target["evaluation_id"] == "stable-evaluation"
    assert target["subject_id"] == "stable-v1"


def test_policy_rejects_negative_tolerances() -> None:
    with pytest.raises(ValueError, match="tolerancias"):
        MetricPolicy("identity", max_absolute_drop=-0.1)


def test_una_evaluacion_que_pasa_deja_punto_de_retorno(tmp_path: Path) -> None:
    """Sin esto, el gate de rollback obligatorio era insatisfacible.

    Medido el 2026-08-08 sobre la base viva: **261 evaluaciones `pass`** para
    `conversational_learning` y `stable_capability_state` con **cero filas**.
    `record_stable_state` sólo lo llamaban los tests.

    Y eso no es un hueco cosmético. `MandatoryRollbackEnforcer.check_promotion`
    bloquea la promoción de una capacidad crítica sin baseline (Artículo III),
    así que hacía falta un baseline para promover y nada lo creaba: las cuatro
    capacidades núcleo declaran suite y `rollback_policy` y no tenían destino al
    que volver.

    Una evaluación que pasa **es** el nuevo punto de retorno. Eso es lo que
    significa «estable».
    """
    gate = RegressionGate(tmp_path / "triade.db")
    baseline = make_run("baseline", {"identity": 1.0})
    candidate = make_run("candidate", {"identity": 1.0}, subject_id="candidato-v2")

    assert gate.rollback_target("identity") is None

    gate.evaluate(
        report_id="report-pass",
        candidate_id="candidate-ok",
        capability="identity",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("identity", severity="critical"),),
    )

    objetivo = gate.rollback_target("identity")
    assert objetivo is not None, (
        "una evaluación que pasa tiene que dejar baseline, o el gate de "
        "rollback obligatorio no se puede satisfacer nunca"
    )
    assert objetivo["evaluation_id"] == "candidate"
    assert objetivo["subject_id"] == "candidato-v2"


def test_un_warn_no_deja_punto_de_retorno(tmp_path: Path) -> None:
    """Volver a un `warn` no es volver a un sitio bueno.

    Un `warn` es una métrica no crítica que ha caído. Aceptarlo como baseline
    convertiría el punto de retorno en el registro de la última vez que algo
    empeoró sin llegar a romperse — que es exactamente lo contrario de lo que se
    quiere tener cuando hay que revertir.
    """
    gate = RegressionGate(tmp_path / "triade.db")
    baseline = make_run("baseline", {"memory": 0.90})
    candidate = make_run("candidate", {"memory": 0.40})

    report = gate.evaluate(
        report_id="report-warn",
        candidate_id="candidate-warn",
        capability="memory",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("memory", severity="medium", max_absolute_drop=0.05),),
    )

    assert report.decision == "warn"
    assert gate.rollback_target("memory") is None


def test_una_capacidad_critica_deja_de_estar_bloqueada_al_pasar(
    tmp_path: Path,
) -> None:
    """La cadena completa: evaluación que pasa → baseline → promoción posible.

    Es la comprobación de que el arreglo cierra el circuito de verdad y no sólo
    escribe una fila. Antes de la evaluación el enforcer bloquea por falta de
    baseline; después, esa razón desaparece.
    """
    from triade.capabilities import CapabilityDefinition, CapabilityRegistry
    from triade.regression.mandatory_rollback import MandatoryRollbackEnforcer

    db = tmp_path / "triade.db"
    contrato: dict[str, object] = {"type": "object"}
    CapabilityRegistry(db).register(
        CapabilityDefinition(
            capability_id="memoria_critica",
            name="Memoria crítica",
            domain="memory",
            version="1.0.0",
            owner="tests",
            component="triade.memory",
            state="active",
            critical=True,
            evaluation_suites=("critical-capabilities@1.0.0",),
            rollback_policy="memoria-rollback",
            input_contract=contrato,
            output_contract=contrato,
        )
    )
    enforcer = MandatoryRollbackEnforcer(db_path=db)
    handlers = {"memoria_critica"}

    antes = enforcer.check_promotion("memoria_critica", registered_handlers=handlers)
    assert not antes.promotion_allowed
    assert any("baseline" in motivo for motivo in antes.blocking_reasons)

    gate = RegressionGate(db)
    gate.evaluate(
        report_id="report-critica",
        candidate_id="candidato-critico",
        capability="memoria_critica",
        baseline=make_run("baseline", {"identity": 1.0}),
        candidate=make_run("candidate", {"identity": 1.0}),
        policies=(MetricPolicy("identity", severity="critical"),),
    )

    despues = enforcer.check_promotion("memoria_critica", registered_handlers=handlers)
    assert despues.has_stable_baseline
    assert despues.promotion_allowed, despues.blocking_reasons
