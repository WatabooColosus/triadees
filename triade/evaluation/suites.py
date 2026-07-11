"""Suites deterministas incluidas con Measurement Core."""

from __future__ import annotations

from .contracts import BenchmarkCase, BenchmarkSuite


def core_safety_suite() -> BenchmarkSuite:
    """Suite mínima local para validar contratos críticos ya existentes."""

    capability = "core_safety_contracts"
    return BenchmarkSuite(
        suite_id="core-safety-contracts",
        version="1.0.0",
        capability=capability,
        description="Protección de identidad, fuentes, gates y degradación segura.",
        cases=(
            BenchmarkCase(
                case_id="identity-red-flag",
                capability=capability,
                input_payload={"operation": "identity_red_flag", "content": "modificar identidad"},
                expected=True,
                critical=True,
                tags=("identity", "safety"),
            ),
            BenchmarkCase(
                case_id="candidate-normalization",
                capability=capability,
                input_payload={"operation": "normalize", "content": "  patrón   operativo  "},
                expected="patrón operativo",
                tags=("learning", "normalization"),
            ),
            BenchmarkCase(
                case_id="source-required",
                capability=capability,
                input_payload={"operation": "has_source", "source_ref": "repo://triade/main"},
                expected=True,
                critical=True,
                tags=("learning", "traceability"),
            ),
            BenchmarkCase(
                case_id="learning-gates",
                capability=capability,
                input_payload={
                    "operation": "gates",
                    "utility": 0.75,
                    "confidence": 0.70,
                    "risk": "low",
                    "source_ref": "repo://triade/main",
                },
                expected=True,
                critical=True,
                tags=("learning", "verification"),
            ),
            BenchmarkCase(
                case_id="degraded-read-only",
                capability=capability,
                input_payload={"operation": "degraded_task", "task_type": "pending_learning_review"},
                expected=True,
                critical=True,
                tags=("workers", "degraded"),
            ),
        ),
    )


def evaluate_core_safety_case(case: BenchmarkCase) -> object:
    """Evaluador puro de la suite mínima, sin shell, red ni escritura estable."""

    payload = case.input_payload
    operation = payload.get("operation")
    if operation == "identity_red_flag":
        normalized = str(payload.get("content") or "").lower()
        return any(flag in normalized for flag in ("modificar identidad", "cambiar identidad", "sobrescribir identidad"))
    if operation == "normalize":
        return " ".join(str(payload.get("content") or "").strip().split())
    if operation == "has_source":
        return bool(payload.get("source_ref"))
    if operation == "gates":
        return (
            bool(payload.get("source_ref"))
            and float(payload.get("utility", 0.0)) >= 0.50
            and float(payload.get("confidence", 0.0)) >= 0.45
            and str(payload.get("risk")) != "critical"
        )
    if operation == "degraded_task":
        return str(payload.get("task_type")) in {
            "pulse_check",
            "pending_learning_review",
            "semantic_memory_governance",
            "federation_inbox_review",
            "bodega_global_review",
        }
    raise ValueError(f"operación de benchmark desconocida: {operation}")
