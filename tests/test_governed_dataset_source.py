"""La autorización de LoRA ata revisión, path y bytes del dataset."""

from __future__ import annotations

import hashlib
from pathlib import Path

from triade.core.governed_datasets import GovernedDatasets


def test_authorized_training_source_detects_file_drift(tmp_path: Path) -> None:
    source = tmp_path / "dataset.jsonl"
    source.write_text('{"instruction":"a","response":"b"}\n', encoding="utf-8")
    store = GovernedDatasets(tmp_path / "triade.db")
    dataset = store.create_dataset(
        "governed",
        "fixture",
        source=str(source),
        governance_rules={
            "allowed_uses": ["lora_training"],
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
    )
    store.update_dataset(dataset.dataset_id, {"status": "training_ready"})

    allowed = store.authorize_training_source(source)
    assert allowed["allowed"] is True
    assert allowed["dataset_id"] == dataset.dataset_id

    source.write_text('{"instruction":"c","response":"d"}\n', encoding="utf-8")
    changed = store.authorize_training_source(source)
    assert changed["allowed"] is False
    assert changed["reason"] == "dataset_sha256_mismatch"
