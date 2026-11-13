import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from triade.training.serving_governance import (
    GovernedPeftServing,
    build_integrity_bundle,
)


def adapter(root: Path, db: Path) -> Path:
    path = root / "adapter"
    path.mkdir(parents=True)
    blob = path / "adapter_model.safetensors"
    blob.write_bytes(b"peft")
    source_hash = "dataset-sha"
    manifest = {
        "base_model": "base",
        "adapter_sha256": hashlib.sha256(blob.read_bytes()).hexdigest(),
        "dataset": {"source_sha256": source_hash},
        "metrics": {
            "baseline_validation_loss": 2.0,
            "validation_loss": 1.0,
            "forgetting_regression": -0.1,
            "ood_loss": 3.0,
        },
    }
    (path / "triade_adapter_manifest.json").write_text(json.dumps(manifest))
    build_integrity_bundle(path)
    serving = GovernedPeftServing(db, root)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO governed_datasets(dataset_id,name,status,governance_rules) VALUES ('ds','d','training_ready',?)",
            (
                json.dumps(
                    {"source_sha256": source_hash, "allowed_uses": ["lora_training"]}
                ),
            ),
        )
    del serving
    return path


def test_hash_mismatch_blocks(tmp_path: Path) -> None:
    db = tmp_path / "db"
    path = adapter(tmp_path / "adapters", db)
    (path / "adapter_model.safetensors").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash_mismatch"):
        GovernedPeftServing(db, tmp_path / "adapters").enroll(path)


def test_unauthorized_dataset_blocks(tmp_path: Path) -> None:
    db = tmp_path / "db"
    path = adapter(tmp_path / "adapters", db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE governed_datasets SET status='draft'")
    with pytest.raises(ValueError, match="not_authorized"):
        GovernedPeftServing(db, tmp_path / "adapters").enroll(path)


def test_failed_canary_blocks_activation(tmp_path: Path) -> None:
    db = tmp_path / "db"
    path = adapter(tmp_path / "adapters", db)
    serving = GovernedPeftServing(db, tmp_path / "adapters")
    version = serving.enroll(path)["version_id"]
    serving.observe(version, quality=-3, latency_ms=1, success=False, evidence_ref="e")
    assert serving.activate(version, approved_by="reviewer")["status"] == "blocked"


def test_activation_persists_and_rollback_restores_base(tmp_path: Path) -> None:
    db = tmp_path / "db"
    path = adapter(tmp_path / "adapters", db)
    # El modelo base del manifiesto tiene que estar entre los servidos: activar
    # un adaptador sobre un modelo que el runtime no sirve deja el slot de
    # producción apuntando a algo inservible.
    serving = GovernedPeftServing(db, tmp_path / "adapters", served_models=["base"])
    version = serving.enroll(path)["version_id"]
    serving.observe(version, quality=1, latency_ms=1, success=True, evidence_ref="e")
    assert serving.activate(version, approved_by="reviewer")["status"] == "active"
    restarted = GovernedPeftServing(db, tmp_path / "adapters", served_models=["base"])
    assert restarted.status()["version_id"] == version
    assert restarted.rollback(approved_by="reviewer")["status"] == "rolled_back"
    assert restarted.status()["status"] == "base_only"
