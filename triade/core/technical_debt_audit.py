"""Auditoría automática de deuda técnica — Tríade Ω.

Revisa el estado del repositorio, superficies UI/API,
dependencias y buenas prácticas para generar un puntaje
de deuda técnica y acciones recomendadas.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from triade.core.life_pulse import LIFE_PULSE


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _exists(path: str) -> bool:
    return (REPO_ROOT / path).exists()


def _file_size(path: str) -> int:
    p = REPO_ROOT / path
    return p.stat().st_size if p.exists() and p.is_file() else 0


def build_technical_debt_audit() -> dict[str, Any]:
    """Audita el estado técnico del repositorio.

    Returns:
        Dict con status, score (0-100), debts, warnings, recommended_actions.
    """
    debts: list[dict[str, Any]] = []
    warnings: list[str] = []
    score = 100

    # ── UI React build disponible
    spa_index = _exists("frontend/dist/index.html")
    spa_js = list((REPO_ROOT / "frontend/dist/assets").glob("index-*.js")) if (REPO_ROOT / "frontend/dist/assets").exists() else []
    if not spa_index:
        debts.append({
            "area": "frontend",
            "item": "React SPA build",
            "detail": "frontend/dist/index.html no encontrado. Ejecutar npm --prefix frontend run build",
            "severity": "high",
        })
        score -= 15
    elif not spa_js:
        warnings.append("frontend/dist/index.html existe pero no hay assets JS (build incompleto)")

    # ── HTML embebido legacy
    ui_html_path = REPO_ROOT / "apps/ui_html.py"
    if ui_html_path.exists():
        size_kb = ui_html_path.stat().st_size / 1024
        if size_kb > 5:
            debts.append({
                "area": "ui_legacy",
                "item": "HTML embebido legacy",
                "detail": f"apps/ui_html.py ({size_kb:.0f} KB). Constantes HTML embebidas deben migrarse a React.",
                "severity": "medium",
            })
            score -= 10

    # ── Apps legacy duplicadas
    legacy_apps = []
    for app_name in ["api_app.py", "chat_ui_app.py", "chat_ui_router_app.py"]:
        if _exists(f"apps/{app_name}"):
            legacy_apps.append(app_name)
    if legacy_apps:
        debts.append({
            "area": "api_legacy",
            "item": "Apps FastAPI legacy",
            "detail": f"{', '.join(legacy_apps)}. Son wrappers deprecated que duplican rutas de single_port_app.",
            "severity": "medium",
        })
        score -= 10

    # ── Duplicaciones de rutas en api.py (alias)
    debts.append({
        "area": "api_duplication",
        "item": "Alias de rutas",
        "detail": "Varias rutas tienen alias (/api/health = /health, /api/observability = /api/system/observability, etc.). Mantener compatibilidad.",
        "severity": "low",
    })
    score -= 3

    # ── APIs core disponibles
    available_endpoints = 0
    if _exists("triade/core/ollama_blood.py"):
        available_endpoints += 1
    else:
        warnings.append("triade/core/ollama_blood.py no encontrado")
        score -= 5

    if _exists("triade/core/observability_view.py"):
        available_endpoints += 1
    else:
        warnings.append("triade/core/observability_view.py no encontrado")
        score -= 5

    if _exists("triade/core/living_report.py"):
        available_endpoints += 1
    else:
        warnings.append("triade/core/living_report.py no encontrado")
        score -= 5

    if _exists("triade/core/bodega_global_context.py"):
        available_endpoints += 1
    else:
        warnings.append("triade/core/bodega_global_context.py no encontrado")
        score -= 5

    # ── Tests presentes
    test_files = list((REPO_ROOT / "tests").glob("test_*.py"))
    if len(test_files) < 20:
        debts.append({
            "area": "tests",
            "item": "Cobertura de tests baja",
            "detail": f"Solo {len(test_files)} archivos de test encontrados. Objetivo: 30+.",
            "severity": "low",
        })
        score -= 5

    # ── Docs vigentes
    doc_files = ["docs/STATUS_CURRENT.md", "docs/UI_REACT_MIGRATION.md", "docs/DEPRECATED_UI_ROUTES.md",
                  "docs/OLLAMA_BLOOD.md"]
    for doc in doc_files:
        if not _exists(doc):
            warnings.append(f"Documento faltante: {doc}")

    # ── STATUS_CURRENT.md desactualizado
    status_file = REPO_ROOT / "docs/STATUS_CURRENT.md"
    if status_file.exists():
        content = status_file.read_text(encoding="utf-8")
        if "UI oficial React SPA" not in content:
            debts.append({
                "area": "docs",
                "item": "STATUS_CURRENT.md no declara React como UI oficial",
                "detail": "docs/STATUS_CURRENT.md debe tener sección UI oficial React SPA.",
                "severity": "medium",
            })
            score -= 8

    # ── identity_core no se modifica
    if _exists("triade/core/identity_core.py"):
        debts.append({
            "area": "safety",
            "item": "identity_core existe",
            "detail": "identity_core presente. Verificar que ninguna ruta ni worker lo modifique.",
            "severity": "low",
        })

    # ── entrypoint oficial
    if _exists("apps/single_port_app.py"):
        available_endpoints += 1
    else:
        debts.append({
            "area": "api",
            "item": "single_port_app.py no encontrado",
            "detail": "El entrypoint oficial no existe.",
            "severity": "high",
        })
        score -= 20

    score = max(0, min(100, score))

    recommended_actions = []
    if score < 50:
        recommended_actions.append("Prioridad: construir React SPA y migrar rutas legacy.")
    if not spa_index:
        recommended_actions.append("Ejecutar npm --prefix frontend run build")
    if legacy_apps:
        recommended_actions.append("Eliminar o reducir apps legacy a wrappers mínimos.")
    if score >= 70:
        recommended_actions.append("Mantener: React SPA como UI oficial, endpoints JSON limpios.")

    LIFE_PULSE.record_action("technical_debt_audit")

    return {
        "status": "ok",
        "score": score,
        "debts_count": len(debts),
        "warnings_count": len(warnings),
        "available_endpoints": available_endpoints,
        "debts": debts,
        "warnings": warnings,
        "recommended_actions": recommended_actions,
        "policy": {
            "read_only": True,
            "no_identity_core_modification": True,
        },
    }
