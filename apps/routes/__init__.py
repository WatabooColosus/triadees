"""Tríade Ω — Route handlers.

Este paquete instala una compatibilidad mínima para contratos públicos que
cambiaron de nombre. Los estados internos detallados se conservan en campos
`internal_*`, mientras la API mantiene valores estables para clientes previos.
"""

from __future__ import annotations

from typing import Any, Callable


def _legacy_ollama_status(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    internal_status = str(result.get("status") or "unavailable")
    result["internal_status"] = internal_status
    if internal_status == "degraded_no_ollama":
        result["status"] = "degraded"
    return result


def _legacy_heartbeat_truth(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    truth = str(result.get("heartbeat_truth") or "")
    result["internal_heartbeat_truth"] = truth
    light = "Autonomía full_local_guarded configurada · degradada a light_background por gobernador"
    if truth == light:
        result["heartbeat_truth"] = (
            "Autonomía full_local_guarded configurada · degradada a balanced_background por gobernador"
        )
    return result


def install_api_contract_compatibility(api_module: Any) -> None:
    """Envuelve proveedores globales usados por las rutas sin ocultar detalle."""

    original_blood: Callable[..., dict[str, Any]] = api_module.check_ollama_blood
    original_heartbeat: Callable[..., dict[str, Any]] = api_module.build_runtime_heartbeat

    def compatible_blood(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return _legacy_ollama_status(original_blood(*args, **kwargs))

    def compatible_heartbeat(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return _legacy_heartbeat_truth(original_heartbeat(*args, **kwargs))

    api_module.check_ollama_blood = compatible_blood
    api_module.build_runtime_heartbeat = compatible_heartbeat


# Importar el submódulo aquí garantiza que la compatibilidad se instale tanto
# para `from apps.routes import api` como para `import apps.routes.api`.
from . import api as api  # noqa: E402

install_api_contract_compatibility(api)

__all__ = ["api", "install_api_contract_compatibility"]
