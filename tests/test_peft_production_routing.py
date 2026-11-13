from __future__ import annotations

from pathlib import Path

from triade.db import sqlite3
from triade.models.ollama_client import OllamaClient
from triade.training.peft_canary import PeftCanaryServer
from triade.training.serving_governance import GovernedPeftServing


def _active_slot(tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / "triade.db"
    adapters = tmp_path / "adapters"
    adapter = adapters / "compatible"
    adapter.mkdir(parents=True)
    GovernedPeftServing(db, adapters, served_models=["qwen2.5:3b-instruct"])
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO governed_peft_versions
            (version_id,adapter_path,integrity_sha256,dataset_id,status,
             traffic_percent,baseline_quality,rollback_ref,approved_by,
             previous_version_id,created_at,updated_at,base_model)
            VALUES ('peft-live',?,'sha','ds','active',5,-2,'rollback','Santiago',
                    NULL,'now','now','Qwen/Qwen2.5-3B-Instruct')""",
            (str(adapter),),
        )
        conn.execute(
            "INSERT INTO governed_peft_active_slot"
            "(slot,version_id,previous_version_id,updated_at) "
            "VALUES ('production','peft-live',NULL,'now')"
        )
    return db, adapter


def test_central_opt_in_uses_the_canonical_active_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    db, adapter = _active_slot(tmp_path)
    calls: list[dict] = []

    def fake_generate(self, adapter_path, prompt, **kwargs):
        calls.append({"adapter_path": adapter_path, "prompt": prompt, **kwargs})
        return {
            "status": "completed",
            "response": "respuesta PEFT real",
            "latency_ms": 12.5,
        }

    monkeypatch.setattr(PeftCanaryServer, "generate", fake_generate)
    result = OllamaClient(db_path=db).generate(
        "qwen2.5:3b-instruct",
        "hola",
        system="sistema",
        options={"num_predict": 32},
        use_active_peft=True,
    )

    assert result.ok is True
    assert result.provider == "peft-local"
    assert result.model == "peft:peft-live"
    assert result.text == "respuesta PEFT real"
    assert calls[0]["adapter_path"] == str(adapter)
    assert calls[0]["event"] == "production_generation"


def test_other_models_do_not_receive_the_adapter(tmp_path: Path) -> None:
    db, _ = _active_slot(tmp_path)
    assert (
        OllamaClient(db_path=db)._generate_with_active_peft(
            "qwen3:4b", "hola", system=None, options=None
        )
        is None
    )


def test_status_distinguishes_routable_from_observed_production(
    tmp_path: Path,
) -> None:
    db, adapter = _active_slot(tmp_path)
    server = PeftCanaryServer(db, adapter.parent)

    before = server.status()["serving_truth"]
    assert before["routing_connected"] is True
    assert before["effective_state"] == "active_routable"

    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO peft_canary_events(adapter_path,event,success) "
            "VALUES (?, 'production_generation', 1)",
            (str(adapter),),
        )

    after = server.status()["serving_truth"]
    assert after["used_by_production_inference"] is True
    assert after["production_successes"] == 1
    assert after["effective_state"] == "active_observed"
