import sqlite3
from pathlib import Path

import pytest

from triade.neuron_factory.certification import NeuronCertifier


def seed(path: Path) -> None:
    certifier = NeuronCertifier(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO neurons(name, mission, domain, status) VALUES ('uncertified', 'm', 'd', 'stable')"
        )
    assert certifier.audit_stable()["stable_count"] == 1


def test_uncertified_stable_is_quarantined_with_backup(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    seed(db)
    result = NeuronCertifier(db).apply_quarantine(tmp_path / "backups")
    assert result["applied_count"] == 1
    assert Path(result["backup"]).exists()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT status FROM neurons").fetchone()[0] == "quarantined"


def test_backup_restores_original_stable_state(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    seed(db)
    certifier = NeuronCertifier(db)
    result = certifier.apply_quarantine(tmp_path / "backups")
    certifier.restore_backup(result["backup"], result["backup_sha256"])
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT status FROM neurons").fetchone()[0] == "stable"


def test_tampered_backup_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    seed(db)
    certifier = NeuronCertifier(db)
    result = certifier.apply_quarantine(tmp_path / "backups")
    backup = Path(result["backup"])
    backup.write_bytes(backup.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="hash_mismatch"):
        certifier.restore_backup(backup, result["backup_sha256"])
