"""Verifica que _shell_execute conecte AutonomousSandbox (snapshot+backup+
rollback por contenido) sin cambiar el comportamiento de comandos exitosos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from triade.workers.contracts import WorkerTask
from triade.workers.worker_loop import WorkerLoop


def _make_loop(tmp_path: Path) -> WorkerLoop:
    return WorkerLoop(
        db_path=tmp_path / "triade.db",
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )


def _make_task(working_dir: Path) -> WorkerTask:
    return WorkerTask(
        id=1,
        task_type="goal_safe_command",
        payload={
            "command_key": "git_status",
            "autonomy_level": "observe_only",
            "working_dir": str(working_dir),
        },
        status="claimed",
    )


def test_sandbox_snapshot_and_restore_roundtrip(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    original = watch_dir / "keep.txt"
    original.write_text("original content", encoding="utf-8")

    snapshot, backup_map, backup_dir = loop._sandbox_snapshot_and_backup(
        watch_dir, "run-test-1"
    )
    assert str(original.resolve()) in snapshot
    assert str(original.resolve()) in backup_map
    assert backup_dir.exists()

    # Simular daño real: se corrompe el archivo original y se crea uno nuevo.
    original.write_text("corrupted by failed command", encoding="utf-8")
    new_file = watch_dir / "unexpected.txt"
    new_file.write_text("should not exist after rollback", encoding="utf-8")

    restored = loop._sandbox_restore(watch_dir, snapshot, backup_map)

    assert restored == 1
    assert original.read_text(encoding="utf-8") == "original content"
    assert not new_file.exists()


def test_shell_execute_success_never_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _make_loop(tmp_path)
    watch_dir = tmp_path / "watched_ok"
    watch_dir.mkdir()
    (watch_dir / "existing.txt").write_text("v1", encoding="utf-8")

    def fake_run_autonomous(**kwargs):
        # Un comando exitoso que de paso modifica un archivo del working_dir.
        (Path(kwargs["working_dir"]) / "existing.txt").write_text(
            "v2", encoding="utf-8"
        )
        return {"status": "ok", "command_key": kwargs["command_key"], "returncode": 0}

    monkeypatch.setattr("triade.core.safe_shell.run_autonomous", fake_run_autonomous)

    result = loop._shell_execute(
        _make_task(watch_dir), "run-test-2", tmp_path / "task_dir", None
    )

    assert result["status"] == "ok"
    assert (watch_dir / "existing.txt").read_text(encoding="utf-8") == "v2"
    assert "sandbox_file_changes" in result
    assert any("existing.txt" in fp for fp in result["sandbox_file_changes"])
    assert "sandbox_rollback" not in result


def test_shell_execute_failure_with_changes_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _make_loop(tmp_path)
    watch_dir = tmp_path / "watched_fail"
    watch_dir.mkdir()
    (watch_dir / "existing.txt").write_text("v1", encoding="utf-8")

    def fake_run_autonomous(**kwargs):
        wd = Path(kwargs["working_dir"])
        (wd / "existing.txt").write_text("corrupted", encoding="utf-8")
        (wd / "stray.txt").write_text("leftover from failure", encoding="utf-8")
        return {
            "status": "error",
            "command_key": kwargs["command_key"],
            "returncode": 1,
        }

    monkeypatch.setattr("triade.core.safe_shell.run_autonomous", fake_run_autonomous)

    result = loop._shell_execute(
        _make_task(watch_dir), "run-test-3", tmp_path / "task_dir", None
    )

    assert result["status"] == "error"
    assert result["sandbox_rollback"]["performed"] is True
    assert (watch_dir / "existing.txt").read_text(encoding="utf-8") == "v1"
    assert not (watch_dir / "stray.txt").exists()


def test_shell_execute_without_working_dir_is_unaffected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _make_loop(tmp_path)

    def fake_run_autonomous(**kwargs):
        assert kwargs["working_dir"] is None
        return {"status": "ok", "command_key": kwargs["command_key"], "returncode": 0}

    monkeypatch.setattr("triade.core.safe_shell.run_autonomous", fake_run_autonomous)

    task = WorkerTask(
        id=2,
        task_type="goal_safe_command",
        payload={"command_key": "git_status", "autonomy_level": "observe_only"},
        status="claimed",
    )
    result = loop._shell_execute(task, "run-test-4", tmp_path / "task_dir", None)

    assert result["status"] == "ok"
    assert "sandbox_file_changes" not in result
    assert "sandbox_rollback" not in result
