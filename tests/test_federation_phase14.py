"""La fase federada manual recorre también despacho y evaluación gobernados."""

from __future__ import annotations

from pathlib import Path

from scripts.run_phase_14_federation import verify_governed_dispatch


def test_governed_federated_dispatch_is_complete(tmp_path: Path) -> None:
    result = verify_governed_dispatch(tmp_path / "federation.db")

    assert result["passed"] is True
    assert result["dispatch_status"] == "completed"
    assert result["decision"] == "pass"
    assert result["trust_after"] > result["trust_before"]
