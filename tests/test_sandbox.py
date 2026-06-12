"""Tests para el sandbox de Tríade Ω.

Verifica:
- run_in_sandbox con tareas permitidas retorna completed o dry_run.
- run_in_sandbox con tarea bloqueada retorna blocked.
- Safety sandbox_only no rompe TriadeRunner.
- identity_core no se modifica.
"""

from __future__ import annotations

import json
import os
import pytest
from pathlib import Path


def test_sandbox_exec_completed():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("sandbox_exec", {"intent": "test"}, dry_run=False)
    assert result["status"] == "completed"
    assert result["task"] == "sandbox_exec"
    assert result["executed"] is True
    assert "policy" in result


def test_sandbox_exec_dry_run():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("sandbox_exec", {"intent": "test"}, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["would_execute"] is True
    assert result["task"] == "sandbox_exec"


def test_sandbox_blocked_task():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("shell", {"command": "rm -rf /"})
    assert result["status"] == "blocked"
    assert "not in the allowed whitelist" in result["reason"] or "explicitly blocked" in result["reason"]


def test_sandbox_blocked_exec():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("exec", {"code": "import os; os.system('rm -rf /')"})
    assert result["status"] == "blocked"


def test_sandbox_sha256():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("sha256", {"text": "hello"})
    assert result["status"] == "completed"
    assert "sha256" in result
    assert len(result["sha256"]) == 64


def test_sandbox_echo():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("echo", {"msg": "test"})
    assert result["status"] == "completed"
    assert result["payload"]["msg"] == "test"


def test_sandbox_preprocess_text():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("preprocess_text", {"text": "hello world foo"})
    assert result["status"] == "completed"
    assert result["word_count"] == 3
    assert result["char_count"] == 15


def test_sandbox_validate_learning_candidate():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("validate_learning_candidate", {"content": "this is a valid learning", "domain": "test"})
    assert result["status"] == "completed"
    assert result["valid"] is True


def test_sandbox_validate_learning_candidate_empty():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("validate_learning_candidate", {"content": "", "domain": "test"})
    assert result["status"] == "completed"
    assert result["valid"] is False


def test_sandbox_analyze_memory_candidate():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("analyze_memory_candidate", {"content": "memory content", "source_ref": "run:123"})
    assert result["status"] == "completed"
    assert result["analyzed"] is True
    assert result["source_ref"] == "run:123"


def test_sandbox_dry_run_file_patch():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("dry_run_file_patch", {"file_path": "/tmp/test.py", "patch_type": "add"})
    assert result["status"] == "completed"
    assert result["dry_run"] is True
    assert result["would_write"] is False


def test_sandbox_creates_artifacts(tmp_path):
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("sandbox_exec", {"test": True}, runs_dir=tmp_path)
    assert result["status"] == "completed"
    artifacts = result.get("artifacts", {})
    assert "input" in artifacts
    assert "result" in artifacts
    assert Path(artifacts["input"]).exists()
    assert Path(artifacts["result"]).exists()
    input_data = json.loads(Path(artifacts["input"]).read_text())
    assert input_data["test"] is True


def test_sandbox_returns_policy():
    from triade.sandbox import run_in_sandbox
    result = run_in_sandbox("echo", {"x": 1})
    policy = result.get("policy", {})
    assert policy.get("no_shell") is True
    assert policy.get("no_network") is True
    assert policy.get("identity_core_protected") is True


def test_sandbox_is_task_allowed():
    from triade.sandbox import is_task_allowed
    assert is_task_allowed("sandbox_exec") is True
    assert is_task_allowed("validate_learning_candidate") is True
    assert is_task_allowed("shell") is False
    assert is_task_allowed("exec") is False
    assert is_task_allowed("unknown_task_xyz") is False


def test_sandbox_identity_core_not_modified():
    """Verifica que el sandbox no toca identity_core."""
    identity_path = Path("triade/memory/identity_core.json")
    if identity_path.exists():
        before = identity_path.read_text()
    else:
        before = None

    from triade.sandbox import run_in_sandbox
    run_in_sandbox("sandbox_exec", {"test": True})

    if identity_path.exists():
        after = identity_path.read_text()
        assert before == after, "identity_core was modified by sandbox!"
