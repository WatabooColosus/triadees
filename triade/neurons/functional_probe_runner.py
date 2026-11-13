"""Run and persist one real functional probe for neuron education."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .functional_evidence import CASES_BY_ID, register_actual_probe


def run_functional_probe(
    db_path: str | Path,
    *,
    runner: Any,
    neuron_id: int,
    case_id: str,
    phase: str,
    session_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a probe through a real runner and register its verified output.

    The runner must produce a closed, verified ``neuron_functional_probe`` run;
    ``register_actual_probe`` remains the authority and fails closed otherwise.
    """
    if case_id not in CASES_BY_ID:
        raise ValueError("functional_probe_case_unknown")
    if phase not in {"pre", "post"}:
        raise ValueError("functional_probe_phase_invalid")
    case = CASES_BY_ID[case_id]
    payload = dict(context or {})
    payload.update(
        {
            "functional_probe_case": case_id,
            "functional_probe_neuron_id": neuron_id,
            "functional_probe_phase": phase,
        }
    )
    result = runner.run(
        user_input=case.question,
        source="neuron_functional_probe",
        context=payload,
        propose_neurons=False,
    )
    run_id = str(result.get("run_id") or "")
    answer = result.get("response")
    if not run_id or not isinstance(answer, str):
        raise ValueError("functional_probe_run_incomplete")
    recorded = register_actual_probe(
        db_path,
        run_id=run_id,
        neuron_id=neuron_id,
        case_id=case_id,
        phase=phase,
        answer=answer,
        session_id=session_id,
    )
    from .education_coordinator import EducationCoordinator
    EducationCoordinator(db_path).record_run(
        neuron_id=neuron_id, case_id=case_id, phase=phase,
        run_id=run_id, session_id=session_id,
    )
    return {"run_id": run_id, "case_id": case_id, "phase": phase, **recorded}
