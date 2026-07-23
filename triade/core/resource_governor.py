"""Resource Governor · decide modo de trabajo según recursos, energía y Ollama Blood."""

from __future__ import annotations

from typing import Any

WORK_MODES = [
    "blocked",
    "cooldown",
    "observe_only",
    "light_background",
    "balanced_background",
    "full_local",
    "full_local_guarded",
]
WORK_MODE_RANK = {m: i for i, m in enumerate(WORK_MODES)}


def decide_work_mode(
    resource_probe: dict[str, Any],
    ollama_blood: dict[str, Any],
    requested_mode: str | None = None,
) -> dict[str, Any]:
    """Evalúa recursos y decide el modo de trabajo máximo permitido.

    Returns dict con allowed_mode, effective_mode, reason y capacidades.
    """
    limits = resource_probe.get("limits", {})
    ram_gb = limits.get("ram_available_gb", 0.0)
    disk_gb = limits.get("disk_free_gb", 0.0)
    tier = limits.get("tier", "unknown")
    cpu_count = limits.get("cpu_count", 1)

    power = resource_probe.get("power", {})
    battery_pct = power.get("battery_percent")
    ac = power.get("ac_connected")
    load_1min = resource_probe.get("cpu", {}).get("load_1min")
    thermal_status = resource_probe.get("thermal", {}).get("thermal_status")
    warnings_list = resource_probe.get("warnings", [])

    can_reason = bool(ollama_blood.get("can_reason"))
    can_embed = bool(ollama_blood.get("can_embed"))
    blood_ok = ollama_blood.get("status") in ("ok", "degraded_missing_models")

    reasons: list[str] = []
    downgrades: list[str] = []

    # --- Bloqueo por disco ---
    if disk_gb < 2:
        allowed_mode = "blocked"
        reasons.append(f"Disco libre insuficiente ({disk_gb} GB). Operaciones bloqueadas.")
        return _build_decision(allowed_mode, requested_mode, reasons, downgrades, resource_probe, ollama_blood)

    # --- Cooldown por RAM ---
    if ram_gb < 2:
        allowed_mode = "cooldown"
        reasons.append(f"RAM disponible muy baja ({ram_gb} GB). Cooldown forzado.")
        return _build_decision(allowed_mode, requested_mode, reasons, downgrades, resource_probe, ollama_blood)

    # --- Cooldown por batería crítica ---
    if battery_pct is not None and battery_pct < 15 and ac is not True:
        allowed_mode = "cooldown"
        reasons.append(f"Batería crítica ({battery_pct}%) sin AC.")
        return _build_decision(allowed_mode, requested_mode, reasons, downgrades, resource_probe, ollama_blood)

    # --- Observe-only por batería baja ---
    if battery_pct is not None and battery_pct < 25 and ac is not True:
        allowed_mode = "observe_only"
        reasons.append(f"Batería baja ({battery_pct}%) sin AC.")
    # --- Cooldown por load average ---
    elif load_1min is not None and load_1min > cpu_count * 2:
        allowed_mode = "cooldown"
        reasons.append(f"Load average ({load_1min}) muy alto para {cpu_count} CPUs.")
    # --- Cooldown por temperatura ---
    elif thermal_status == "critical":
        allowed_mode = "cooldown"
        reasons.append("Temperatura crítica.")
    elif thermal_status == "high":
        allowed_mode = "observe_only"
        reasons.append("Temperatura elevada.")
    # --- Observación por falta de Ollama razonador ---
    elif not can_reason:
        allowed_mode = "light_background"
        reasons.append("Sin modelo razonador Ollama. Máximo light_background.")
        downgrades.append("semantic_embedding" if not can_embed else None)
        downgrades.append("learning_evaluation")
    # --- Observación por hardware low ---
    elif tier == "low":
        allowed_mode = "light_background"
        reasons.append(f"Hardware tier {tier}. Máximo light_background.")
    # --- Balanced por hardware medium ---
    elif tier == "medium":
        allowed_mode = "balanced_background"
        reasons.append(f"Hardware tier {tier} con AC y Ollama OK. Máximo balanced_background.")
    # --- Full local por high ---
    elif tier == "high" and blood_ok and (ac is not False):
        allowed_mode = "full_local_guarded"
        reasons.append(f"Hardware tier {tier} con AC y Ollama Blood activa. Full local guarded permitido.")
    else:
        allowed_mode = "balanced_background"
        reasons.append(f"Hardware tier {tier}, recursos suficientes. Modo balanced.")

    return _build_decision(allowed_mode, requested_mode, reasons, downgrades, resource_probe, ollama_blood)


def _build_decision(
    allowed_mode: str,
    requested_mode: str | None,
    reasons: list[str],
    downgrades: list[str],
    probe: dict[str, Any],
    blood: dict[str, Any],
) -> dict[str, Any]:
    requested = requested_mode or "observe_only"
    if WORK_MODE_RANK.get(requested, 0) > WORK_MODE_RANK.get(allowed_mode, 0):
        effective_mode = allowed_mode
        reasons.append(f"Modo solicitado '{requested}' excede permitido '{allowed_mode}'. Degradado.")
    else:
        effective_mode = requested

    can_embed = bool(blood.get("can_embed"))
    can_reason = bool(blood.get("can_reason"))
    can_nourish = effective_mode in ("balanced_background", "full_local", "full_local_guarded", "execute_missions") and can_reason
    can_evaluate = effective_mode in ("light_background", "balanced_background", "full_local", "full_local_guarded") and can_reason
    can_consolidate = effective_mode in ("full_local", "full_local_guarded") and can_reason
    can_workers = effective_mode in ("light_background", "balanced_background", "full_local", "full_local_guarded", "execute_missions")
    can_write = effective_mode in ("balanced_background", "full_local", "full_local_guarded")
    can_write_repo = False
    can_shell = effective_mode == "full_local_guarded"  # shell autónomo solo en modo más alto
    can_test = effective_mode == "full_local"
    can_build = effective_mode == "full_local"

    blocked: list[str] = []
    allowed_actions: list[str] = ["read_project", "publish_events", "record_heartbeat"]

    if effective_mode in ("observe_only", "light_background", "balanced_background", "full_local", "full_local_guarded"):
        allowed_actions.append("observe_bodega")
    if effective_mode in ("light_background", "balanced_background", "full_local", "full_local_guarded", "execute_missions"):
        allowed_actions.append("run_workers")
    if effective_mode in ("balanced_background", "full_local", "full_local_guarded", "execute_missions"):
        allowed_actions.append("run_neuron_nutrition")
        allowed_actions.append("write_runs")
        allowed_actions.append("write_artifacts")
    if effective_mode in ("full_local", "full_local_guarded"):
        allowed_actions.append("evaluate_learning")
        allowed_actions.append("consolidate_stable")
        allowed_actions.append("run_tests")
        allowed_actions.append("run_build")
    if effective_mode == "full_local_guarded":
        allowed_actions.append("run_shell")
    if can_embed:
        allowed_actions.append("semantic_embedding")
    else:
        blocked.append("semantic_embedding")

    # Bloqueos explícitos
    if not can_workers:
        blocked.append("run_workers")
    if not can_nourish:
        blocked.append("neuron_nutrition")
    if not can_evaluate:
        blocked.append("learning_evaluation")
    if not can_consolidate:
        blocked.append("stable_consolidation")
    if not can_write:
        blocked.append("write_repo")
    if not can_shell:
        blocked.append("run_shell")
    if not can_test:
        blocked.append("run_tests")
    if not can_build:
        blocked.append("run_build")

    blocked.append("modify_identity_core")

    return {
        "status": "ok",
        "requested_mode": requested,
        "allowed_mode": allowed_mode,
        "effective_mode": effective_mode,
        "reason": "; ".join(filter(None, reasons)),
        "can_run_ollama": can_reason,
        "can_run_workers": can_workers,
        "can_nourish_neurons": can_nourish,
        "can_evaluate_learning": can_evaluate,
        "can_consolidate_stable": can_consolidate,
        "can_write_artifacts": can_write,
        "can_write_repo": can_write_repo,
        "can_run_shell": can_shell,
        "can_run_tests": can_test,
        "can_run_build": can_build,
        "blocked_actions": blocked,
        "allowed_actions": allowed_actions,
        "safety": {
            "identity_core_protected": True,
            "requires_human_approval_for_repo_write": True,
            "shell_whitelist_only": True,
        },
    }
