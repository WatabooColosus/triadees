from __future__ import annotations

import hashlib
import json
from pathlib import Path

from triade.db import sqlite3
from triade.training.governed_lora import GovernedLoraJobRunner
from triade.training.serving_governance import GovernedPeftServing
from triade.workers.contracts import WorkerTask
from triade.workers.worker_loop import _timeout_for_task


def _write_rows(path: Path, count: int = 5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "instruction": f"pregunta {index}",
                    "response": f"respuesta {index}",
                }
            )
            for index in range(count)
        )
        + "\n",
        encoding="utf-8",
    )


def _authorized_dataset(db: Path, adapters: Path, dataset: Path) -> None:
    GovernedPeftServing(db, adapters, served_models=["qwen2.5:3b-instruct"])
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO governed_datasets"
            "(dataset_id,name,source,status,governance_rules) "
            "VALUES ('ds-test','test',?,'training_ready',?)",
            (
                str(dataset),
                json.dumps(
                    {
                        "source_sha256": hashlib.sha256(
                            dataset.read_bytes()
                        ).hexdigest(),
                        "allowed_uses": ["lora_training"],
                    }
                ),
            ),
        )


def test_lora_requires_independent_ood_and_forgetting_data(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    dataset = tmp_path / "data/lora/train.jsonl"
    _write_rows(dataset)

    result = GovernedLoraJobRunner(tmp_path / "triade.db").run(
        {
            "human_approved": True,
            "approved_by": "Santiago",
            "dataset_path": str(dataset),
            "base_model": "Qwen/Qwen2.5-3B-Instruct",
        }
    )

    assert result == {"status": "blocked", "reason": "ood_dataset_required"}


def test_training_result_is_bundled_and_enrolled_in_canary(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    dataset = tmp_path / "data/lora/train.jsonl"
    ood = tmp_path / "data/lora/ood.jsonl"
    forgetting = tmp_path / "data/lora/forgetting.jsonl"
    for path in (dataset, ood, forgetting):
        _write_rows(path)
    db = tmp_path / "triade.db"
    adapters = tmp_path / "artifacts/adapters"
    _authorized_dataset(db, adapters, dataset)

    def fake_train(self, dataset_path, **kwargs):
        output = Path(self.config.output_dir).resolve()
        output.mkdir(parents=True)
        blob = output / "adapter_model.safetensors"
        blob.write_bytes(b"compatible-peft")
        manifest = {
            "base_model": self.config.base_model,
            "adapter_sha256": hashlib.sha256(blob.read_bytes()).hexdigest(),
            "dataset": {
                "source_sha256": hashlib.sha256(
                    Path(dataset_path).read_bytes()
                ).hexdigest()
            },
            "metrics": {
                "baseline_validation_loss": 2.0,
                "validation_loss": 1.0,
                "forgetting_regression": -0.1,
                "ood_loss": 2.5,
            },
        }
        (output / "triade_adapter_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (output / "rollback.json").write_text("{}\n", encoding="utf-8")
        return {"status": "trained_not_activated", "output_dir": str(output)}

    monkeypatch.setattr(
        "triade.training.governed_lora.RealLoraTrainer.train", fake_train
    )
    result = GovernedLoraJobRunner(db).run(
        {
            "goal_id": "goal-test",
            "human_approved": True,
            "approved_by": "Santiago",
            "dataset_path": str(dataset),
            "ood_path": str(ood),
            "forgetting_path": str(forgetting),
            "base_model": "Qwen/Qwen2.5-3B-Instruct",
            "max_steps": 2,
        }
    )

    assert result["status"] == "completed"
    assert result["canary"]["status"] == "canary"
    assert result["canary"]["traffic_percent"] == 5.0
    assert result["effect_receipt"]["verified"] is True
    assert result["dataset_authorization"]["dataset_id"] == "ds-test"
    assert (Path(result["output_dir"]) / "serving_integrity.json").is_file()
    with sqlite3.connect(db) as conn:
        job_status = conn.execute(
            "SELECT status FROM lora_jobs WHERE id=?", (result["job_id"],)
        ).fetchone()[0]
        version_status = conn.execute(
            "SELECT status FROM governed_peft_versions WHERE version_id=?",
            (result["canary"]["version_id"],),
        ).fetchone()[0]
    assert job_status == "canary"
    assert version_status == "canary"


def test_training_rejects_an_unregistered_dataset_before_gpu(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    dataset = tmp_path / "data/lora/train.jsonl"
    ood = tmp_path / "data/lora/ood.jsonl"
    forgetting = tmp_path / "data/lora/forgetting.jsonl"
    for path in (dataset, ood, forgetting):
        _write_rows(path)

    result = GovernedLoraJobRunner(tmp_path / "triade.db").run(
        {
            "human_approved": True,
            "approved_by": "Santiago",
            "dataset_path": str(dataset),
            "ood_path": str(ood),
            "forgetting_path": str(forgetting),
            "base_model": "Qwen/Qwen2.5-3B-Instruct",
        }
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "dataset_not_registered"


def test_lora_timeout_honors_gpu_budget_plus_bounded_overhead() -> None:
    task = WorkerTask(task_type="goal_lora_train", payload={"maximum_gpu_minutes": 10})
    assert _timeout_for_task(task, 30.0, 1) == 25 * 60
    assert _timeout_for_task(WorkerTask(task_type="pulse_check"), 30.0, 2) == 60.0
