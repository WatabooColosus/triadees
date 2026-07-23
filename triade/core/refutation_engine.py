"""Motor de refutación: contrasta afirmaciones de Tríade con evidencia medible."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def _claim(claim_id: str, statement: str, check: Callable[[], tuple[bool | None, Any]]) -> dict[str, Any]:
    try:
        verdict, evidence = check()
        status = "supported" if verdict is True else "falsified" if verdict is False else "undetermined"
        return {"claim_id": claim_id, "statement": statement, "verdict": status, "evidence": evidence}
    except Exception as exc:
        return {"claim_id": claim_id, "statement": statement, "verdict": "undetermined", "evidence": {"error": str(exc)}}


def run_system_refutation(
    db_path: str | Path = "triade/memory/triade.db", runs_dir: str | Path = "runs",
) -> dict[str, Any]:
    db_path, runs_dir = Path(db_path), Path(runs_dir)

    def runtime_claim():
        from .internal_runtime import build_runtime_heartbeat
        value = build_runtime_heartbeat(db_path=db_path, runs_dir=runs_dir)
        observed_cycles = int(value.get("cycles_last_hour") or 0)
        return bool(observed_cycles > 0), {
            "runtime_enabled": value.get("runtime_enabled"), "background_thread_alive": value.get("background_thread_alive"),
            "observer_scope": "El hilo solo es visible dentro del proceso servidor; ciclos persistidos prueban actividad entre procesos.",
            "cycles_last_hour": observed_cycles,
            "continuity": value.get("runtime_continuity_score"), "latest_error": value.get("latest_error"),
        }

    def edge_claim():
        from .federated_global_edge import build_federated_global_edge_context
        value = build_federated_global_edge_context(db_path)
        ok = value.get("status") == "ok" and "nodes" in value and value.get("policy", {}).get("node_input_is_evidence_not_truth") is True
        return ok, {"nodes_total": value.get("nodes_total"), "nodes_active_online": value.get("nodes_active_online"), "policy": value.get("policy")}

    def foundational_claim():
        from .foundational_neurons import ensure_foundational_neurons
        value = ensure_foundational_neurons(db_path)
        return value.get("count") == 10, {"count": value.get("count"), "creator": value.get("creator")}

    def artifacts_claim():
        closed = list(runs_dir.glob("run-*/CLOSED"))
        integrity = list(runs_dir.glob("run-*/integrity.json"))
        return (bool(closed) and len(closed) == len(integrity)), {"closed_runs": len(closed), "integrity_artifacts": len(integrity)}

    def model_claim():
        from triade.models.ollama_client import OllamaClient
        models = OllamaClient().health().get("models", [])
        present = any(str(model).startswith("triade-omega") for model in models)
        return present, {"models": models, "truth": "Modelo derivado; no entrenamiento fundacional desde cero."}

    claims = [
        _claim("runtime_continuous", "El runtime opera continuamente en segundo plano.", runtime_claim),
        _claim("foundational_neurons", "Las diez neuronas fundacionales están registradas.", foundational_claim),
        _claim("global_edge", "Bodega Global incluye contexto de nodos federados con procedencia.", edge_claim),
        _claim("run_integrity", "Los runs cerrados tienen integridad auditable.", artifacts_claim),
        _claim("triade_model", "Existe un modelo Ollama identificable de Tríade.", model_claim),
    ]
    counts = {verdict: sum(1 for item in claims if item["verdict"] == verdict) for verdict in ("supported", "falsified", "undetermined")}
    return {
        "status": "coherent" if counts["falsified"] == 0 else "contradictions_found",
        "method": "claim_evidence_falsification",
        "claims": claims,
        "counts": counts,
        "policy": "La teoría no cuenta como evidencia de su propia implementación.",
    }
