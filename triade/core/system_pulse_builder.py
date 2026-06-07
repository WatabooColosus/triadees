"""Constructor del Pulso Vivo de Tríade Ω.

Este módulo separa la composición del pulso del servidor FastAPI.
No ejecuta acciones externas: solo consulta funciones inyectadas por la app.
"""

from __future__ import annotations

from typing import Any, Callable

from .experimental_neuron_evidence import build_experimental_evidence_ledger
from .stable_promotion_readiness import evaluate_stable_readiness


def pulse_item(
    name: str,
    ok: bool,
    summary: str,
    detail: dict[str, Any] | None = None,
    level: str | None = None,
) -> dict[str, Any]:
    clean_level = level or ("ok" if ok else "warn")
    return {"name": name, "ok": ok, "level": clean_level, "summary": summary, "detail": detail or {}}


def safe_pulse(name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        return pulse_item(name, False, str(exc), level="error")


def experimental_neuron_pulse() -> dict[str, Any]:
    """Resumen seguro de neuronas experimentales para Pulso Vivo."""
    try:
        ledger = build_experimental_evidence_ledger(runs_dir="runs", limit=200)
        neurons = ledger.get("neurons") or []
        stable_ready = [n for n in neurons if n.get("stable_promotion_ready")]
        return {
            "ok": True,
            "summary": ledger.get("summary", {}),
            "last_active_neuron": neurons[0].get("name") if neurons else None,
            "stable_ready_count": len(stable_ready),
            "neurons": [
                {
                    "name": n.get("name"),
                    "status": n.get("status"),
                    "domain": n.get("domain"),
                    "activation_count": n.get("activation_count"),
                    "diagnosis_count": n.get("diagnosis_count"),
                    "test_plan_count": n.get("test_plan_count"),
                    "last_run_id": n.get("last_run_id"),
                    "stable_promotion_ready": n.get("stable_promotion_ready"),
                    "source": n.get("source"),
                }
                for n in neurons[:5]
            ],
            "policy": "evidence_only_no_auto_promotion",
        }
    except Exception as exc:
        return {
            "ok": False,
            "summary": {"experimental_neurons_with_evidence": 0, "total_activations": 0},
            "last_active_neuron": None,
            "stable_ready_count": 0,
            "neurons": [],
            "error": str(exc),
            "policy": "evidence_only_no_auto_promotion",
        }


def stable_readiness_pulse() -> dict[str, Any]:
    """Resumen seguro de readiness stable para Pulso Vivo.

    No promueve neuronas. Solo informa si alguna experimental tiene evidencia
    suficiente para revisión humana futura.
    """
    try:
        report = evaluate_stable_readiness(runs_dir="runs", limit=300)
        neurons = report.get("neurons") or []
        return {
            "ok": True,
            "summary": report.get("summary", {}),
            "ready_neurons": [
                {
                    "name": n.get("name"),
                    "status": n.get("status"),
                    "domain": n.get("domain"),
                    "activation_count": n.get("activation_count"),
                    "diagnosis_count": n.get("diagnosis_count"),
                    "test_plan_count": n.get("test_plan_count"),
                    "last_run_id": n.get("last_run_id"),
                    "required_human_decision": n.get("required_human_decision"),
                }
                for n in neurons
                if n.get("ready_for_stable_review")
            ][:5],
            "blocked_neurons": [
                {
                    "name": n.get("name"),
                    "status": n.get("status"),
                    "domain": n.get("domain"),
                    "blockers": n.get("blockers", []),
                    "last_run_id": n.get("last_run_id"),
                }
                for n in neurons
                if not n.get("ready_for_stable_review")
            ][:5],
            "policy": "readiness_only_no_auto_stable",
        }
    except Exception as exc:
        return {
            "ok": False,
            "summary": {
                "neurons_evaluated": 0,
                "ready_for_stable_review": 0,
                "not_ready": 0,
                "policy": "readiness_only_no_auto_stable",
            },
            "ready_neurons": [],
            "blocked_neurons": [],
            "error": str(exc),
            "policy": "readiness_only_no_auto_stable",
        }


def build_system_pulse(
    *,
    sync_relay: bool = True,
    intent: str = "conversation",
    urgency: str = "medium",
    build_model_capacity_fn: Callable[..., dict[str, Any]],
    router_payload_fn: Callable[..., dict[str, Any]],
    model_install_queue_fn: Callable[..., dict[str, Any]],
    semantic_governance_doctor_fn: Callable[[], dict[str, Any]],
    federated_transport_doctor_fn: Callable[[], dict[str, Any]],
    life_snapshot_fn: Callable[[], dict[str, Any]],
    qualia_snapshot_fn: Callable[..., dict[str, Any]],
    edge_llm_host_count_fn: Callable[[dict[str, Any], dict[str, Any]], int],
    edge_llm_host_snapshot_fn: Callable[[], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Construye el pulso completo usando dependencias inyectadas por la app."""
    capacity = build_model_capacity_fn(sync_relay=sync_relay)
    local = capacity["local"]
    federation = capacity["federation"]
    hardware = local["hardware"]
    ollama = local["ollama"]
    docker = local["docker"]
    nodes = federation.get("online_feeders", [])
    authorized = federation.get("authorized", {})

    experimental_neurons = experimental_neuron_pulse()
    stable_readiness = stable_readiness_pulse()

    router = safe_pulse(
        "router",
        lambda: pulse_item(
            "router",
            True,
            "Router disponible",
            {"decisions": router_payload_fn(intent=intent, urgency=urgency).get("router", {}).get("decisions", {})},
        ),
    )
    compatibility = safe_pulse(
        "compatibility",
        lambda: pulse_item(
            "compatibility",
            True,
            f"{local.get('counts', {}).get('recommended', 0)} modelos recomendados",
            {"counts": local.get("counts", {}), "summary": local.get("model_matrix_summary", "")},
            "ok" if local.get("counts", {}).get("recommended", 0) else "warn",
        ),
    )
    queue = safe_pulse(
        "model_queue",
        lambda: pulse_item(
            "model_queue",
            True,
            f"{model_install_queue_fn(False).get('count', 0)} candidatos en cola segura",
            {"auto_install": False},
        ),
    )
    semantic = safe_pulse(
        "semantic_memory",
        lambda: pulse_item(
            "semantic_memory",
            True,
            "Gobierno semantico activo",
            {"doctor": semantic_governance_doctor_fn()},
        ),
    )
    transport = safe_pulse(
        "signed_transport",
        lambda: pulse_item(
            "signed_transport",
            True,
            "HTTP firmado activo para nodos Android",
            federated_transport_doctor_fn(),
        ),
    )

    llm_host_count = edge_llm_host_count_fn(authorized, federation)

    checks = [
        pulse_item("ollama", bool(ollama.get("ok")), "Ollama activo" if ollama.get("ok") else "Ollama apagado o no responde", {"models": ollama.get("models", [])}, "ok" if ollama.get("ok") else "warn"),
        pulse_item("docker", bool(docker.get("ok")), "Docker activo" if docker.get("ok") else ("Docker instalado, motor pendiente" if docker.get("installed") else "Docker no disponible"), docker, "ok" if docker.get("ok") else "warn"),
        pulse_item("local_ram", float(hardware.get("ram_available_gb") or 0) >= 4, f"{hardware.get('ram_available_gb')} GB RAM libre local", {"missing": local.get("missing_for_comfortable_models", [])}, "ok" if float(hardware.get("ram_available_gb") or 0) >= 4 else "warn"),
        pulse_item("federation", len(nodes) > 0, f"{len(nodes)} nodos Android alimentando" if nodes else "Sin nodos Android nativos online", {"nodes": nodes, "authorized": authorized}, "ok" if nodes else "warn"),
        pulse_item(
            "llm_android_host",
            llm_host_count > 0,
            f"{llm_host_count} hosts LLM Android reales",
            {
                "llm_hosts": federation.get("llm_hosts", []),
                "edge_router_hosts": edge_llm_host_snapshot_fn(),
                "source": "authorized_or_edge_router",
            },
            "ok" if llm_host_count > 0 else "warn",
        ),
        router,
        compatibility,
        queue,
        semantic,
        transport,
        pulse_item(
            "experimental_neurons",
            bool(experimental_neurons.get("ok")),
            f"{(experimental_neurons.get('summary') or {}).get('experimental_neurons_with_evidence', 0)} neuronas experimentales con evidencia",
            experimental_neurons,
            "ok" if experimental_neurons.get("ok") else "warn",
        ),
        pulse_item(
            "stable_readiness",
            bool(stable_readiness.get("ok")),
            f"{(stable_readiness.get('summary') or {}).get('ready_for_stable_review', 0)} neuronas listas para revisión stable",
            stable_readiness,
            "ok" if stable_readiness.get("ok") else "warn",
        ),
    ]

    alerts = [item for item in checks if not item["ok"] or item["level"] in {"warn", "error"}]
    errors = [item for item in checks if item["level"] == "error"]
    level = "ok" if not alerts else ("bad" if errors else "warn")

    return {
        "status": "ok" if not errors else "degraded",
        "mode": "system-pulse",
        "level": level,
        "summary": "Todo activo" if level == "ok" else ("Degradado" if level == "bad" else "Activo con pendientes"),
        "alerts": alerts,
        "checks": checks,
        "life": life_snapshot_fn(),
        "qualia": qualia_snapshot_fn(refresh_life=False),
        "capacity": capacity,
        "experimental_neurons": experimental_neurons,
        "stable_readiness": stable_readiness,
        "truth": "Pulso unico: resume router, modelos, memoria, transporte, PC, nodos, vida operativa, neuronas experimentales y readiness stable sin auto-promoción; los botones tecnicos quedan como contadores inspeccionables.",
    }
