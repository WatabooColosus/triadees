from triade.core.foundational_neurons import ensure_foundational_neurons
from triade.core.neuron_missions import NeuronMissionStore
from triade.core.neuron_registry import NeuronRegistry


def test_foundational_neurons_are_idempotent_and_missioned(tmp_path):
    db_path = tmp_path / "triade.db"
    first = ensure_foundational_neurons(db_path)
    second = ensure_foundational_neurons(db_path)

    assert first["count"] == 10
    assert second["count"] == 10
    assert first["creator"] == "Wataboo · Agencia Digital"
    neurons = NeuronRegistry(db_path).list_neurons(limit=20)
    assert len(neurons) == 10
    assert all(n["status"] == "stable" for n in neurons)
    assert all(n["activation_policy"]["every_session"] for n in neurons)

    missions = NeuronMissionStore(db_path).list_missions(limit=20)
    assert len(missions) == 10
    assert all(m.status == "stable" and m.schedule_hint == "every_session" for m in missions)


def test_emotional_drives_are_governed(tmp_path):
    db_path = tmp_path / "triade.db"
    ensure_foundational_neurons(db_path)
    neurons = NeuronRegistry(db_path).list_neurons(limit=20)
    drives = [n for n in neurons if n["domain"] == "emotional_drive"]

    assert len(drives) == 7
    assert all("bypass_safety" in n["forbidden_actions"] for n in drives)
    assert all("external_action_without_permission" in n["forbidden_actions"] for n in drives)
