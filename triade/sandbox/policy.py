"""Política de sandbox — whitelist de tareas permitidas y reglas de aislamiento.

Tríade Ω — Sandbox Policy
"""

from __future__ import annotations

ALLOWED_TASKS: frozenset[str] = frozenset({
    "sandbox_exec",
    "validate_learning_candidate",
    "analyze_memory_candidate",
    "dry_run_file_patch",
    "sha256",
    "echo",
    "preprocess_text",
    "federated_inference_probe",
    "browser_benchmark",
})

BLOCKED_TASKS: frozenset[str] = frozenset({
    "shell",
    "exec",
    "eval",
    "deploy",
    "install",
    "publish",
    "git_push",
    "filesystem_write",
    "network_request",
})


def is_task_allowed(task: str) -> bool:
    return task in ALLOWED_TASKS and task not in BLOCKED_TASKS


def get_blocked_reason(task: str) -> str:
    if task in BLOCKED_TASKS:
        return f"task '{task}' is explicitly blocked by sandbox policy"
    return f"task '{task}' is not in the allowed whitelist"


SANDBOX_POLICY = {
    "no_shell": True,
    "no_network": True,
    "no_writes_outside_sandbox": True,
    "identity_core_protected": True,
    "max_timeout_seconds": 60.0,
    "max_memory_mb": 512,
    "allowed_tasks": sorted(ALLOWED_TASKS),
}
