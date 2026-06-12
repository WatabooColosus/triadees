"""Executor de sandbox — ejecuta tareas permitidas en aislamiento controlado.

Tríade Ω — Sandbox Executor

Reglas:
- No ejecutar shell arbitrario.
- No usar red.
- No escribir fuera de runs/sandbox.
- Solo permitir tareas de lista blanca.
- identity_core nunca se modifica.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .policy import is_task_allowed, get_blocked_reason, SANDBOX_POLICY


def run_in_sandbox(
    task: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 10.0,
    dry_run: bool = False,
    runs_dir: str | Path = "runs/sandbox",
) -> dict[str, Any]:
    """Ejecuta una tarea en entorno sandbox aislado.

    Args:
        task: Nombre de la tarea (debe estar en whitelist).
        payload: Datos de entrada serializables.
        timeout: Tiempo máximo de ejecución en segundos.
        dry_run: Si True, no ejecuta nada, solo reporta qué haría.
        runs_dir: Directorio base para artifacts.

    Returns:
        Dict serializable con: status, task, stdout, stderr, artifacts, policy.
    """
    payload = payload or {}

    if not is_task_allowed(task):
        return {
            "status": "blocked",
            "task": task,
            "reason": get_blocked_reason(task),
            "stdout": "",
            "stderr": "",
            "artifacts": {},
            "policy": SANDBOX_POLICY,
            "allowed_task": False,
            "writes_outside_sandbox": False,
            "network_used": False,
            "shell_used": False,
        }

    if dry_run:
        return {
            "status": "dry_run",
            "task": task,
            "would_execute": True,
            "payload_keys": sorted(payload.keys()),
            "stdout": "",
            "stderr": "",
            "artifacts": {},
            "policy": SANDBOX_POLICY,
            "allowed_task": True,
            "writes_outside_sandbox": False,
            "network_used": False,
            "shell_used": False,
        }

    sandbox_id = f"{task}_{int(time.time() * 1000)}_{os.getpid()}"
    workdir = Path(runs_dir) / sandbox_id

    try:
        workdir.mkdir(parents=True, exist_ok=True)

        input_path = workdir / "input.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")

        result = _execute_task(task, payload)

        result_path = workdir / "result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")

        result["sandbox"] = sandbox_id
        result["artifacts"] = {
            "input": str(input_path),
            "result": str(result_path),
        }
        result["policy"] = SANDBOX_POLICY
        result["allowed_task"] = True
        result["writes_outside_sandbox"] = False
        result["network_used"] = False
        result["shell_used"] = False
        return result

    except Exception as exc:
        return {
            "status": "error",
            "task": task,
            "error": f"Sandbox error: {exc}",
            "sandbox": sandbox_id,
            "stdout": "",
            "stderr": str(exc)[:2000],
            "artifacts": {},
            "policy": SANDBOX_POLICY,
            "allowed_task": True,
            "writes_outside_sandbox": False,
            "network_used": False,
            "shell_used": False,
        }


def _execute_task(task: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Ejecuta una tarea específica de la whitelist.

    Cada tarea es una función pura que no usa shell, red ni escritura externa.
    """
    start = time.monotonic()

    if task == "sandbox_exec":
        result = _task_sandbox_exec(payload)
    elif task == "validate_learning_candidate":
        result = _task_validate_learning_candidate(payload)
    elif task == "analyze_memory_candidate":
        result = _task_analyze_memory_candidate(payload)
    elif task == "dry_run_file_patch":
        result = _task_dry_run_file_patch(payload)
    elif task == "sha256":
        result = _task_sha256(payload)
    elif task == "echo":
        result = _task_echo(payload)
    elif task == "preprocess_text":
        result = _task_preprocess_text(payload)
    elif task == "federated_inference_probe":
        result = _task_federated_inference_probe(payload)
    elif task == "browser_benchmark":
        result = _task_browser_benchmark(payload)
    else:
        result = {"status": "blocked", "reason": f"Unknown task: {task}"}

    result["task"] = task
    result["elapsed"] = round(time.monotonic() - start, 4)
    return result


def _task_sandbox_exec(payload: dict[str, Any]) -> dict[str, Any]:
    """Ejecución aislada genérica — no realiza acciones reales."""
    return {
        "status": "completed",
        "executed": True,
        "sandbox_mode": "isolated",
        "payload_keys": sorted(payload.keys()),
        "note": "Ejecución aislada en sandbox. Ninguna acción real fue ejecutada.",
        "stdout": "sandbox_exec completed",
        "stderr": "",
    }


def _task_validate_learning_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """Valida un candidato de aprendizaje sin modificar estado."""
    content = str(payload.get("content", ""))
    domain = str(payload.get("domain", "general"))
    has_content = bool(content.strip())
    word_count = len(content.split()) if content else 0
    return {
        "status": "completed",
        "valid": has_content and word_count >= 3,
        "domain": domain,
        "word_count": word_count,
        "stdout": f"Validated candidate: {word_count} words, domain={domain}",
        "stderr": "",
    }


def _task_analyze_memory_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """Analiza un candidato de memoria sin persistir."""
    content = str(payload.get("content", ""))
    source_ref = str(payload.get("source_ref", ""))
    word_count = len(content.split()) if content else 0
    return {
        "status": "completed",
        "analyzed": True,
        "word_count": word_count,
        "source_ref": source_ref,
        "stdout": f"Analyzed memory candidate: {word_count} words",
        "stderr": "",
    }


def _task_dry_run_file_patch(payload: dict[str, Any]) -> dict[str, Any]:
    """Simula un parche de archivo sin escribir nada."""
    file_path = str(payload.get("file_path", ""))
    patch_type = str(payload.get("patch_type", "unknown"))
    return {
        "status": "completed",
        "dry_run": True,
        "file_path": file_path,
        "patch_type": patch_type,
        "would_write": False,
        "stdout": f"Dry run patch for {file_path} (type={patch_type})",
        "stderr": "",
    }


def _task_sha256(payload: dict[str, Any]) -> dict[str, Any]:
    """Calcula SHA-256 de un texto."""
    import hashlib
    text = str(payload.get("text", "triade"))
    sha = hashlib.sha256(text.encode()).hexdigest()
    return {
        "status": "completed",
        "sha256": sha,
        "stdout": sha,
        "stderr": "",
    }


def _task_echo(payload: dict[str, Any]) -> dict[str, Any]:
    """Devuelve el payload tal cual."""
    return {
        "status": "completed",
        "payload": payload,
        "stdout": json.dumps(payload, ensure_ascii=False, default=str)[:2000],
        "stderr": "",
    }


def _task_preprocess_text(payload: dict[str, Any]) -> dict[str, Any]:
    """Preprocesa texto: cuenta palabras, caracteres, tokens approx."""
    text = str(payload.get("text", ""))
    chars = len(text)
    words = len(text.split())
    tokens = chars // 3
    return {
        "status": "completed",
        "word_count": words,
        "char_count": chars,
        "approx_tokens": tokens,
        "stdout": f"words={words} chars={chars} tokens≈{tokens}",
        "stderr": "",
    }


def _task_federated_inference_probe(payload: dict[str, Any]) -> dict[str, Any]:
    """Simula una sonda de inferencia federada."""
    import random
    iterations = int(payload.get("iterations", 5000))
    ops = iterations // 1000 + random.randint(0, 10)
    return {
        "status": "completed",
        "ops": ops,
        "stdout": f"probe ops={ops}",
        "stderr": "",
    }


def _task_browser_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    """Simula un benchmark de navegador."""
    import random
    score = random.randint(5000, 15000)
    return {
        "status": "completed",
        "score": score,
        "ops": score * 2,
        "stdout": f"benchmark score={score}",
        "stderr": "",
    }
