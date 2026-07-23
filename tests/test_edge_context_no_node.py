from triade.core.edge_context import build_edge_context


def test_no_edge_node_uses_local_signal_without_false_empty_observation(monkeypatch):
    from triade.core.edge_processing import EdgeProcessingResult

    class SkippedService:
        def context_probe(self, text):
            return EdgeProcessingResult(False, False, "intent_probe", text, None, 0, "no_node", "", {"status": "skipped", "reason": "no_node"})

    monkeypatch.setattr("triade.core.edge_context.EdgeProcessingService", SkippedService)
    monkeypatch.setattr("triade.core.edge_observations.record_edge_observation", lambda **_kw: {"status": "ok"})
    result = build_edge_context("analiza el sistema")
    assert result["used_edge"] is False
    assert result["accepted"] is True
    assert result["edge_signal_quality"] == "local_heuristic"
    assert result["edge_observations"] == []
    assert result["fallback_used"] is False


def test_latest_local_signal_marks_historical_failures_recovered(tmp_path):
    from triade.core.edge_observations import build_edge_context_health, record_edge_observation
    db = tmp_path / "triade.db"
    for _ in range(3):
        record_edge_observation("intent_probe", "empty_response", "empty", True, "", "hola", db_path=db)
    record_edge_observation("local_edge_signal", "local_heuristic", "medium", False, "", "hola", db_path=db)
    result = build_edge_context_health(db_path=db)
    assert result["status"] == "recovered_local"
    assert result["empty_count_24h"] == 3
