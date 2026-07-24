"""Adquisición gobernada de modelos Ollama para N roles/neuronas."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import threading
from pathlib import Path
from typing import Any

from triade.models.ollama_client import OllamaClient


MODEL_CATALOG: dict[str, dict[str, Any]] = {
    "qwen3:4b": {
        "roles": ["deep_reasoning", "refutation", "theory"], "size_gb": 2.5,
        "license": "Apache-2.0", "source": "https://ollama.com/library/qwen3",
    },
    "qwen2.5-coder:3b": {
        "roles": ["coding", "tests", "build", "repair"], "size_gb": 1.9,
        "license": "Apache-2.0", "source": "https://ollama.com/library/qwen2.5-coder",
    },
    "gemma3:4b": {
        "roles": ["vision", "image_understanding", "multilingual"], "size_gb": 3.3,
        "license": "Gemma Terms", "source": "https://ollama.com/library/gemma3",
    },
}

_STATE: dict[str, Any] = {"status": "idle", "downloaded": [], "failed": [], "thread_alive": False}
_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None


def model_acquisition_status() -> dict[str, Any]:
    with _LOCK:
        state = dict(_STATE)
    state["thread_alive"] = bool(_THREAD and _THREAD.is_alive())
    state["catalog"] = MODEL_CATALOG
    state["installed"] = OllamaClient().health().get("models", [])
    state["assignments"] = assign_models_to_neurons()
    state["policy"] = {
        "catalog_only": True, "no_remote_code_execution": True,
        "max_parallel_downloads": 1, "new_models_are_candidates": True,
        "innate_architecture_immutable": True,
    }
    return state


def reconcile_model_catalog(
    *, max_downloads: int = 3, min_free_disk_gb: float = 25.0,
    db_path: str | Path = "triade/memory/triade.db",
) -> dict[str, Any]:
    """Descarga faltantes secuencialmente; nunca acepta nombres externos."""
    installed = set(OllamaClient().health().get("models", []))
    missing = [name for name in MODEL_CATALOG if name not in installed][: max(0, min(max_downloads, 3))]
    downloaded: list[str] = []
    failed: list[dict[str, str]] = []
    for model in missing:
        free_gb = shutil.disk_usage(Path.cwd()).free / (1024 ** 3)
        required = float(MODEL_CATALOG[model]["size_gb"]) + min_free_disk_gb
        if free_gb < required:
            failed.append({"model": model, "error": f"disk_budget: {free_gb:.1f}GB < {required:.1f}GB"})
            continue
        try:
            result = subprocess.run(
                ["ollama", "pull", model], shell=False, capture_output=True, text=True,
                timeout=1800, cwd=str(Path(__file__).resolve().parents[2]),
            )
            if result.returncode == 0:
                downloaded.append(model)
            else:
                failed.append({"model": model, "error": (result.stderr or result.stdout)[-500:]})
        except (OSError, subprocess.TimeoutExpired) as exc:
            failed.append({"model": model, "error": str(exc)})
    ensure_specialized_model_neurons(db_path)
    assignments = assign_models_to_neurons(db_path)
    result = {
        "status": "ok" if not failed else "degraded", "missing_before": missing,
        "downloaded": downloaded, "failed": failed, "assignments": assignments,
        "identity_core_modified": False, "stable_memory_written": False,
    }
    with _LOCK:
        _STATE.update(result)
    return result


def start_model_acquisition_background() -> dict[str, Any]:
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return {"status": "already_running"}

    def work() -> None:
        with _LOCK:
            _STATE.update({"status": "running", "thread_alive": True})
        try:
            reconcile_model_catalog()
        finally:
            with _LOCK:
                _STATE["thread_alive"] = False

    _THREAD = threading.Thread(target=work, name="triade-model-acquisition", daemon=True)
    _THREAD.start()
    return {"status": "started", "catalog_size": len(MODEL_CATALOG)}


def assign_models_to_neurons(db_path: str | Path = "triade/memory/triade.db") -> list[dict[str, str]]:
    """Asigna N neuronas a modelos por rol; los modelos pueden compartirse."""
    path = Path(db_path)
    if not path.exists():
        return []
    installed = set(OllamaClient().health().get("models", []))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT name, domain FROM neurons ORDER BY id").fetchall()
    assignments = []
    for row in rows:
        domain = str(row["domain"] or "general")
        identity = f"{row['name']} {domain}".lower()
        if any(term in identity for term in ("code", "codigo", "código", "repo", "build", "repar")) and "qwen2.5-coder:3b" in installed:
            model, role = "qwen2.5-coder:3b", "coding"
        elif any(term in identity for term in ("vision", "image", "imagen")) and "gemma3:4b" in installed:
            model, role = "gemma3:4b", "vision"
        elif domain in {"cognitive_coordination", "system_governance"} and "qwen3:4b" in installed:
            model, role = "qwen3:4b", "deep_reasoning"
        else:
            model, role = "qwen2.5:3b-instruct", "innate_default"
        assignments.append({"neuron": str(row["name"]), "domain": domain, "model": model, "role": role})
    return assignments


def ensure_specialized_model_neurons(db_path: str | Path = "triade/memory/triade.db") -> list[str]:
    """Crea especialidades experimentales; no las promueve a stable."""
    from .neuron_creator import NeuronSpec
    from .neuron_registry import NeuronRegistry
    registry = NeuronRegistry(db_path)
    specs = [
        NeuronSpec(
            name="Neurona Visual",
            mission="Interpretar imágenes con evidencia y describir límites; no generar imágenes sin un motor generativo.",
            domain="vision_image_understanding", status="experimental", created_by="model_acquisition_governed",
            forbidden_actions=["modify_identity_core", "write_stable_memory", "execute_external_action_without_approval"],
            success_metrics=["visual_grounding_accuracy", "hallucination_rate"], evidence_required=["vision_eval_suite"],
        ),
        NeuronSpec(
            name="Neurona de Código y Reparación",
            mission="Analizar, probar y proponer reparaciones de código mediante sandbox y comandos permitidos.",
            domain="code_repair_build_tests", status="experimental", created_by="model_acquisition_governed",
            forbidden_actions=["modify_identity_core", "run_shell_free", "modify_git", "deploy_without_approval"],
            success_metrics=["tests_pass_rate", "regression_rate", "repair_acceptance"], evidence_required=["test_report", "regression_report"],
        ),
    ]
    return [spec.name for spec in specs if registry.register(spec)]
