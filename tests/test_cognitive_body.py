from triade.body import cognitive_body as module


def test_cognitive_body_snapshot_is_auditable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        module,
        "get_internal_runtime_state",
        lambda **_: {"enabled": True, "mode": "observe_only", "services": {"central": "ok"}},
    )
    monkeypatch.setattr(
        module,
        "build_runtime_heartbeat",
        lambda **_: {
            "recent_events": [{"event_type": "runtime_cycle_complete"}],
            "cycles_last_24h": 1,
            "runtime_activity_state": "active_background",
            "degraded_components": [],
            "blocked_learning_actions": [],
            "ollama_blood": {"status": "degraded_no_ollama"},
        },
    )
    monkeypatch.setattr(
        module,
        "build_learning_journal",
        lambda **_: {"status": "ok", "candidates_created": 2, "consolidations": 1},
    )

    class FakeWorkers:
        def __init__(self, **_):
            pass

        def status(self):
            return {"running": False, "queued": 3, "status": "idle"}

    monkeypatch.setattr(module, "WorkerBackgroundService", FakeWorkers)

    result = module.CognitiveBody(
        db_path=tmp_path / "triade.db",
        runs_dir=tmp_path / "runs",
    ).snapshot()

    assert result["status"] == "operational"
    assert result["entity"] == "Tríade Ω"
    assert result["nervous_system"]["sensory_periphery"]["signals"] == 1
    assert result["nervous_system"]["hippocampus"]["learning_candidates"] == 2
    assert result["nervous_system"]["cerebellum"]["queued_tasks"] == 3
    assert result["claims"] == {
        "subjective_consciousness": False,
        "persistent_runtime": True,
        "learning_requires_evidence": True,
        "identity_core_mutable": False,
    }


def test_build_cognitive_body_delegates_to_snapshot(monkeypatch):
    expected = {"status": "dormant"}

    def fake_snapshot(self, *, since_hours, limit):
        assert since_hours == 12
        assert limit == 7
        return expected

    monkeypatch.setattr(module.CognitiveBody, "snapshot", fake_snapshot)

    assert module.build_cognitive_body(since_hours=12, limit=7) is expected
