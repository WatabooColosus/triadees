"""Federation Gate — verifica permisos y confianza antes de operaciones federadas."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from triade.federation.federation import Federation

TASK_PERMISSIONS: dict[str, str] = {
    "browser_benchmark": "request_compute",
    "preprocess_text": "request_compute",
    "federated_inference_probe": "request_compute",
    "android_model_doctor": "request_compute",
    "android_local_generate": "request_compute",
}

TRUST_THRESHOLDS: dict[str, str] = {
    "federated_inference_probe": "low",
    "android_model_doctor": "medium",
    "android_local_generate": "medium",
}

TRUST_RANK = {"low": 0, "medium": 1, "high": 2}


def require_federation_enabled() -> None:
    """Pre-flight: verifica que la federación esté habilitada en la configuración."""
    try:
        from triade.core.config import load_config

        config = load_config()
        if not config.get("federation", {}).get("enabled", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "Federación deshabilitada por configuración.",
                    "truth": "Habilita federation.enabled en triade.yml para operaciones federadas.",
                },
            )
    except HTTPException:
        raise
    except Exception:
        pass


def federation_gate(nodes: list[dict[str, Any]], task: str | None = None) -> list[dict[str, Any]]:
    """Post-selección: filtra nodos por permiso y trust level requeridos.

    Args:
        nodes: Lista de nodos candidatos (ya filtrados por estado y capacidades).
        task: Nombre de la tarea a ejecutar (determina permiso y trust requeridos).

    Returns:
        Lista de nodos autorizados. Puede ser vacía.

    Raises:
        HTTPException 403 si ningún nodo pasa el gate.
    """
    if not nodes:
        return nodes

    required_perm = TASK_PERMISSIONS.get(task) if task else None
    min_trust = TRUST_THRESHOLDS.get(task) if task else None

    if required_perm is None and min_trust is None:
        return nodes

    fed = Federation()
    authorized: list[dict[str, Any]] = []

    for node in nodes:
        registered = fed.get_node(node["node_id"])
        if registered is None:
            continue
        perms = registered.get("permissions") or []
        if required_perm and required_perm not in perms:
            continue
        if min_trust:
            trust = registered.get("trust_level") or "low"
            if TRUST_RANK.get(trust, 0) < TRUST_RANK.get(min_trust, 0):
                continue
        authorized.append(node)

    if not authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Ningún nodo federado tiene los permisos o nivel de confianza requeridos.",
                "required_permission": required_perm,
                "minimum_trust_level": min_trust,
                "task": task,
                "truth": "El gate federado bloqueó la operación. Revisa permisos y trust_level de los nodos registrados.",
            },
        )

    return authorized
