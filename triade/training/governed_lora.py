"""Puerta de scheduler para LoRA: dataset gobernado, presupuesto y no activación."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .lora_trainer import LoraTrainingConfig, RealLoraTrainer


class GovernedLoraJobRunner:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS lora_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id TEXT, dataset_path TEXT, base_model TEXT,
                max_steps INTEGER, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT, result_json TEXT, error TEXT)""")

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload.get("human_approved") or not payload.get("approved_by"):
            return {"status": "blocked", "reason": "explicit_human_approval_required"}
        dataset = Path(str(payload.get("dataset_path") or "")).resolve()
        allowed = [Path("data/lora").resolve(), Path("artifacts/datasets").resolve()]
        if not dataset.is_file() or not any(
            root == dataset.parent or root in dataset.parents for root in allowed
        ):
            return {"status": "blocked", "reason": "dataset_not_in_governed_storage"}
        max_steps = max(1, min(int(payload.get("max_steps") or 20), 100))
        goal_id = str(payload.get("goal_id") or "manual")
        output = Path("artifacts/adapters") / f"{goal_id}-{max_steps}steps"
        config = LoraTrainingConfig(
            base_model=str(payload.get("base_model") or "Qwen/Qwen2.5-0.5B-Instruct"),
            output_dir=str(output),
            max_steps=max_steps,
            maximum_gpu_minutes=min(
                float(payload.get("maximum_gpu_minutes") or 30), 120
            ),
        )
        with sqlite3.connect(self.db_path) as conn:
            job_id = conn.execute(
                "INSERT INTO lora_jobs(goal_id,dataset_path,base_model,max_steps,status) VALUES(?,?,?,?,?)",
                (goal_id, str(dataset), config.base_model, max_steps, "running"),
            ).lastrowid
        try:
            result = RealLoraTrainer(config).train(
                dataset,
                ood_path=payload.get("ood_path"),
                forgetting_path=payload.get("forgetting_path"),
                db_path=self.db_path,
            )
            result.update(
                {
                    "job_id": job_id,
                    "canary_required": True,
                    "automatic_activation": False,
                }
            )
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE lora_jobs SET status='trained_pending_canary',finished_at=CURRENT_TIMESTAMP,result_json=? WHERE id=?",
                    (json.dumps(result, default=str), job_id),
                )
            return result
        except Exception as exc:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE lora_jobs SET status='failed',finished_at=CURRENT_TIMESTAMP,error=? WHERE id=?",
                    (str(exc), job_id),
                )
            return {
                "status": "error",
                "job_id": job_id,
                "error": str(exc),
                "automatic_activation": False,
            }
