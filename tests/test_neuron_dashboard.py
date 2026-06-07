from __future__ import annotations

from pathlib import Path

from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_dashboard import build_neuron_dashboard
from triade.core.neuron_registry import NeuronRegistry


def test_neuron_dashboard_is_read_only_and_groups_status(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = NeuronRegistry(db_path=db_path)
    registry.register(NeuronSpec(
        name="neurona-dashboard-candidate",
        mission="Probar dashboard candidate.",
        domain="system_governance",
        rules=["Solo prueba"],
        status="candidate",
        created_by="test",
    ))
    registry.register(NeuronSpec(
        name="neurona-dashboard-stable",
        mission="Probar dashboard stable.",
        domain="system_governance",
        rules=["Solo prueba"],
        status="stable",
        created_by="test",
    ))

    dashboard = build_neuron_dashboard(db_path=db_path, runs_dir=tmp_path / "runs", limit=20)

    assert dashboard["status"] == "ok"
    assert dashboard["mode"] == "neuron_dashboard"
    assert dashboard["summary"]["total_neurons"] == 2
    assert dashboard["summary"]["by_status"]["candidate"] == 1
    assert dashboard["summary"]["by_status"]["stable"] == 1
    assert dashboard["policy"] == "dashboard_read_only_actions_require_explicit_endpoint"

    candidate = next(n for n in dashboard["neurons"] if n["name"] == "neurona-dashboard-candidate")
    stable = next(n for n in dashboard["neurons"] if n["name"] == "neurona-dashboard-stable")

    assert any(a["id"] == "approve_experimental" and a["enabled"] for a in candidate["ui_actions"])
    assert stable["ui_actions"][0]["id"] == "view_only"
    assert stable["ui_actions"][0]["enabled"] is False
