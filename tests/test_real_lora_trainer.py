import json

import pytest

from triade.training import LoraTrainingConfig, RealLoraTrainer


def test_dataset_is_deduplicated_split_and_secret_filtered(tmp_path):
    clean = [
        {"instruction": f"Pregunta {i}", "response": f"Respuesta gobernada {i}"}
        for i in range(6)
    ]
    rows = clean + [
        clean[0],
        {"instruction": "secreto", "response": "password=demasiado-secreto"},
    ]
    path = tmp_path / "dataset.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
    prepared = RealLoraTrainer(LoraTrainingConfig(minimum_examples=5)).prepare_dataset(
        path
    )
    assert prepared["manifest"]["deduplicated"] == 6
    assert prepared["manifest"]["rejected_pii"] == 1
    assert (
        prepared["manifest"]["train_count"] + prepared["manifest"]["validation_count"]
        == 6
    )
    assert prepared["manifest"]["train_hash"] != prepared["manifest"]["validation_hash"]


def test_dataset_requires_enough_examples(tmp_path):
    path = tmp_path / "small.jsonl"
    path.write_text('{"instruction":"a","response":"b"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="al menos"):
        RealLoraTrainer().prepare_dataset(path)
