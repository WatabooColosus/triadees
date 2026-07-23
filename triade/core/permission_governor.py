"""Permission Governor · perfiles de permisos según modo de trabajo."""

from __future__ import annotations

from typing import Any


def build_permission_profile(
    mode: str,
    api_key_present: bool = False,
    human_approved: bool = False,
) -> dict[str, Any]:
    """Construye perfil de permisos para el modo de trabajo dado.

    observe_only:
      solo lectura + eventos.
    light_background:
      lectura + artifacts/runs.
    balanced_background:
      lectura + artifacts + candidates + neuron evidence.
    full_local/full_local_guarded:
      todo lo anterior + tests/build whitelist.
      repo write solo con human approval.
      shell solo whitelist.
      identity_core nunca.
    """
    p = {
        "status": "ok",
        "mode": mode,
        "api_key_present": api_key_present,
        "human_approved": human_approved,
        "permissions": {},
        "explanations": {},
        "blocked": [],
    }

    grants = _grants_for(mode)

    for perm, (granted, explanation) in grants.items():
        p["permissions"][perm] = granted
        p["explanations"][perm] = explanation
        if not granted:
            p["blocked"].append(perm)

    # identity_core nunca se modifica
    p["permissions"]["can_modify_identity_core"] = False
    p["explanations"]["can_modify_identity_core"] = "identity_core nunca se modifica."

    # repo_write requiere human_approved
    if mode in ("full_local", "full_local_guarded") and not human_approved:
        p["permissions"]["can_write_repo"] = False
        p["explanations"]["can_write_repo"] = "Repo write requiere aprobación humana."

    # shell solo whitelist
    if mode in ("balanced_background", "full_local", "full_local_guarded") and human_approved:
        p["permissions"]["can_run_shell"] = True
        p["explanations"]["can_run_shell"] = "Shell permitido solo whitelist con aprobación."
    else:
        p["permissions"]["can_run_shell"] = False
        p["explanations"]["can_run_shell"] = "Shell solo whitelist con aprobación humana."

    return p


def _grants_for(mode: str) -> dict[str, tuple[bool, str]]:
    base: dict[str, tuple[bool, str]] = {
        "can_read_project": (True, "Lectura de proyecto permitida."),
        "can_write_runs": (False, ""),
        "can_write_artifacts": (False, ""),
        "can_write_reports": (False, ""),
        "can_write_repo": (False, ""),
        "can_create_files": (False, ""),
        "can_run_shell": (False, ""),
        "can_run_git_status": (False, ""),
        "can_run_tests": (False, ""),
        "can_run_build": (False, ""),
        "can_research_web": (False, ""),
        "can_call_ollama": (False, ""),
        "can_consolidate_stable": (False, ""),
        "can_promote_neuron_stable": (False, ""),
    }

    if mode in ("observe_only", "light_background", "balanced_background", "full_local", "full_local_guarded"):
        base["can_read_project"] = (True, "Lectura de proyecto permitida.")
        base["can_write_runs"] = (True, "Escritura de runs permitida.")
        base["can_call_ollama"] = (True, "Llamadas a Ollama permitidas.")

    if mode in ("light_background", "balanced_background", "full_local", "full_local_guarded"):
        base["can_write_artifacts"] = (True, "Escritura de artifacts permitida.")
        base["can_create_files"] = (True, "Creación de archivos en runs/artifacts.")

    if mode in ("balanced_background", "full_local", "full_local_guarded"):
        base["can_write_reports"] = (True, "Escritura de informes permitida.")
        base["can_run_git_status"] = (True, "Git status permitido.")

    if mode in ("full_local", "full_local_guarded"):
        base["can_run_tests"] = (True, "Tests permitidos (whitelist).")
        base["can_run_build"] = (True, "Build permitido (whitelist).")
        base["can_consolidate_stable"] = (True, "Consolidación estable permitida con gates.")
        base["can_promote_neuron_stable"] = (True, "Promoción de neuronas estables permitida con gates.")
    if mode == "full_local_guarded":
        base["can_research_web"] = (True, "Investigación web explícita permitida con fuentes, límites y bloqueo SSRF.")

    for k in list(base.keys()):
        if not base[k][0]:
            base[k] = (False, f"'{k}' no permitido en modo {mode}.")

    return base
