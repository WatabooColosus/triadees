from pathlib import Path

from triade.core.model_acquisition import _ollama_binary
from triade.memory.encrypted_backup import EncryptedBackup
from triade.training.governed_lora import GovernedLoraJobRunner
from triade.training.installer import IsolatedInstaller
from triade.workers.adaptive_scheduler import AdaptiveScheduler


def test_adaptive_scheduler_skips_recent_expensive_task(tmp_path: Path) -> None:
    scheduler = AdaptiveScheduler(tmp_path / "db.sqlite")
    scheduler.record_task_execution("research_curriculum", 100, True)
    assert scheduler.should_skip_task("research_curriculum") is True


def test_installer_never_runs_without_named_approval(tmp_path: Path) -> None:
    installer = IsolatedInstaller(tmp_path / "db.sqlite", tmp_path / "envs")
    assert (
        installer.install(
            "requests==2.32.0", goal_id="g1", approved=True, approved_by=""
        )["status"]
        == "blocked"
    )


def test_lora_job_rejects_unapproved_dataset(tmp_path: Path) -> None:
    runner = GovernedLoraJobRunner(tmp_path / "db.sqlite")
    result = runner.run({"dataset_path": str(tmp_path / "anything.jsonl")})
    assert result["status"] == "blocked"


def test_backup_refuses_plaintext_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TRIADE_BACKUP_KEY", raising=False)
    backup = EncryptedBackup(tmp_path / "db.sqlite", tmp_path / "backups")
    import sqlite3

    sqlite3.connect(tmp_path / "db.sqlite").close()
    try:
        backup.create()
    except RuntimeError as exc:
        assert "TRIADE_BACKUP_KEY" in str(exc)
    else:
        raise AssertionError("backup sin cifrado no debe existir")


def test_ollama_binary_resolves_configured_runtime(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "ollama"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("TRIADE_OLLAMA_BIN", str(binary))
    assert _ollama_binary() == str(binary)
