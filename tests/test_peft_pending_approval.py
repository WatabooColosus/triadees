"""Verifica el detector de aprobación de un clic para LoRA canary."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from triade.training.peft_canary import PeftCanaryServer


def _server(tmp_path: Path) -> PeftCanaryServer:
    return PeftCanaryServer(
        db_path=tmp_path / "triade.db", adapters_root=tmp_path / "adapters"
    )


def test_no_pending_when_no_canary_ran(tmp_path: Path) -> None:
    server = _server(tmp_path)
    result = server.pending_approval()
    assert result == {
        "status": "ok",
        "active_adapter_path": None,
        "pending_count": 0,
        "pending": [],
    }


def test_successful_canary_appears_as_pending(tmp_path: Path) -> None:
    server = _server(tmp_path)
    with sqlite3.connect(server.db_path) as conn:
        conn.execute(
            "INSERT INTO peft_canary_events(adapter_path, event, success) "
            "VALUES (?, 'canary_generation', 1)",
            ("/adapters/foo",),
        )
        conn.execute(
            "INSERT INTO peft_canary_events(adapter_path, event, success) "
            "VALUES (?, 'canary_generation', 1)",
            ("/adapters/foo",),
        )

    result = server.pending_approval()

    assert result["pending_count"] == 1
    assert result["pending"][0]["adapter_path"] == "/adapters/foo"
    assert result["pending"][0]["successful_canaries"] == 2


def test_failed_canary_never_counts_as_pending(tmp_path: Path) -> None:
    server = _server(tmp_path)
    with sqlite3.connect(server.db_path) as conn:
        conn.execute(
            "INSERT INTO peft_canary_events(adapter_path, event, success) "
            "VALUES (?, 'canary_generation', 0)",
            ("/adapters/bar",),
        )

    result = server.pending_approval()

    assert result["pending_count"] == 0


def test_already_active_adapter_is_not_pending(tmp_path: Path) -> None:
    server = _server(tmp_path)
    with sqlite3.connect(server.db_path) as conn:
        conn.execute(
            "INSERT INTO peft_canary_events(adapter_path, event, success) "
            "VALUES (?, 'canary_generation', 1)",
            ("/adapters/active-one",),
        )
        conn.execute(
            "INSERT INTO peft_serving_state(slot, adapter_path, status) "
            "VALUES ('production', ?, 'active')",
            ("/adapters/active-one",),
        )

    result = server.pending_approval()

    assert result["active_adapter_path"] == "/adapters/active-one"
    assert result["pending_count"] == 0


def test_pending_disappears_after_real_activation(tmp_path: Path) -> None:
    server = _server(tmp_path)
    adapter_dir = tmp_path / "adapters" / "demo"
    adapter_dir.mkdir(parents=True)
    blob = adapter_dir / "adapter_model.safetensors"
    blob.write_bytes(b"fake-weights")
    manifest = {"adapter_sha256": hashlib.sha256(blob.read_bytes()).hexdigest()}
    (adapter_dir / "triade_adapter_manifest.json").write_text(json.dumps(manifest))
    with sqlite3.connect(server.db_path) as conn:
        conn.execute(
            "INSERT INTO peft_canary_events(adapter_path, event, success) "
            "VALUES (?, 'canary_generation', 1)",
            (str(adapter_dir),),
        )

    before = server.pending_approval()
    assert before["pending_count"] == 1

    activation = server.activate(str(adapter_dir), approved_by="test-human")
    assert activation["status"] == "active"

    after = server.pending_approval()
    assert after["pending_count"] == 0
    assert after["active_adapter_path"] == str(adapter_dir)


def test_retired_canonical_adapter_keeps_evidence_but_is_not_pending(
    tmp_path: Path,
) -> None:
    server = _server(tmp_path)
    with sqlite3.connect(server.db_path) as conn:
        conn.execute(
            "CREATE TABLE governed_peft_versions "
            "(version_id TEXT PRIMARY KEY, adapter_path TEXT, status TEXT)"
        )
        conn.execute(
            "INSERT INTO governed_peft_versions VALUES ('old','/adapters/old','retired')"
        )
        conn.execute(
            "INSERT INTO peft_canary_events(adapter_path,event,success) "
            "VALUES ('/adapters/old','canary_generation',1)"
        )

    result = server.pending_approval()

    assert result["pending_count"] == 0
    with sqlite3.connect(server.db_path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM peft_canary_events WHERE adapter_path='/adapters/old'"
            ).fetchone()[0]
            == 1
        )
