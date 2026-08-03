from __future__ import annotations

import json
from pathlib import Path

import pytest

from triade.core.active_memory import ActiveMemoryError, load_active_memory


def test_repository_active_memory_loads_and_exposes_covenant() -> None:
    snapshot = load_active_memory()

    assert snapshot.schema_version == "1.0.0"
    assert snapshot.memory_id == "triade_active_covenant_2026_08_02"
    assert snapshot.checksum
    assert snapshot.permits("observe") is True
    assert snapshot.permits("run_low_risk_local_actions") is True
    assert snapshot.permits("modify_identity_core") is False
    assert snapshot.permits("activate_lora_in_production") is False
    assert snapshot.permits("unknown_future_permission") is False

    context = snapshot.runtime_context()
    assert context["ethical_covenant"]["name"] == "Pacto de Manos Unidas"
    assert context["architecture_direction"]["llm_blood"]["model_is_organ_not_soul"]


def test_active_memory_rejects_unsafe_permission_expansion(tmp_path: Path) -> None:
    source = load_active_memory().payload
    payload = json.loads(json.dumps(source))
    payload["operational_permissions"]["self_expand_permissions"] = True
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ActiveMemoryError, match="Unsafe foundational permissions"):
        load_active_memory(path)


def test_active_memory_rejects_unknown_schema(tmp_path: Path) -> None:
    source = load_active_memory().payload
    payload = json.loads(json.dumps(source))
    payload["schema_version"] = "99.0.0"
    path = tmp_path / "future.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ActiveMemoryError, match="Unsupported active memory schema"):
        load_active_memory(path)
