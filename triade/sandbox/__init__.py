"""Safety Sandbox — ejecuta operaciones en aislamiento controlado.

Tríade Ω — Sandbox Package

Uso:
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("sandbox_exec", {"intent": "test"}, dry_run=True)
"""

from .executor import run_in_sandbox
from .policy import ALLOWED_TASKS, BLOCKED_TASKS, SANDBOX_POLICY, is_task_allowed

__all__ = ["run_in_sandbox", "ALLOWED_TASKS", "BLOCKED_TASKS", "SANDBOX_POLICY", "is_task_allowed"]
