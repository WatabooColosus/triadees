from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient


def test_parse_model_json_safely_empty_is_observation_not_error() -> None:
    from triade.core.edge_context import parse_model_json_safely

    result = parse_model_json_safely("", fallback_text="hola", parser_name="intent_probe")

    assert result["ok"] is False
    assert result["empty"] is True
    assert result["observation_type"] == "empty_response"
    assert result["signal_quality"] == "empty"
    assert result["fallback_required"] is True


def test_parse_intent_empty_records_edge_observation(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_record(**kwargs):
        calls.append(kwargs)
        return {"status": "ok", "event_id": 1}

    monkeypatch.setattr("triade.core.edge_observations.record_edge_observation", fake_record)

    result = _parse_intent_empty()

    assert calls
    assert calls[0]["parser_name"] == "intent_probe"
    assert calls[0]["observation_type"] == "empty_response"
    assert calls[0]["fallback_used"] is True
    assert result["_fallback_used"] is True


def test_parse_intent_empty_returns_heuristic_with_quality(monkeypatch) -> None:
    monkeypatch.setattr("triade.core.edge_observations.record_edge_observation", lambda **_kw: {"status": "ok"})

    result = _parse_intent_empty()

    assert result["intent"] in {"casual", "general", "unknown", "question"}
    assert result["_edge_signal_quality"] == "empty"
    assert result["_edge_observation_type"] == "empty_response"
    assert result["_fallback_used"] is True


def test_parse_context_probe_non_json_records_signal_quality(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        "triade.core.edge_observations.record_edge_observation",
        lambda **kw: calls.append(kw) or {"status": "ok"},
    )

    from triade.core.edge_context import parse_context_probe

    result = parse_context_probe("esto no es json", fallback_text="audita repo")

    assert result["ok"] is False
    assert result["edge_signal_quality"] == "low"
    assert result["edge_observation_type"] == "non_json_response"
    assert result["fallback_used"] is True
    assert calls[0]["parser_name"] == "context_probe"


def test_build_edge_context_exposes_edge_confidence_score(monkeypatch) -> None:
    monkeypatch.setattr("triade.core.edge_observations.record_edge_observation", lambda **_kw: {"status": "ok"})

    @dataclass
    class FakeEdgeResult:
        response: str
        used_edge: bool = True
        accepted_for_context: bool = False
        node_id: str = "node-test"

        def to_dict(self) -> dict:
            return self.__dict__.copy()

    class FakeService:
        def context_probe(self, _text):
            return FakeEdgeResult(response="")

        def intent_probe(self, _text):
            return FakeEdgeResult(response="")

        def keywords(self, _text):
            return FakeEdgeResult(response="hola, repo")

    monkeypatch.setattr("triade.core.edge_context.EdgeProcessingService", FakeService)

    from triade.core.edge_context import build_edge_context

    ctx = build_edge_context("hola")

    assert ctx["edge_signal_quality"] == "empty"
    assert ctx["fallback_used"] is True
    assert ctx["edge_confidence_score"] <= 0.2
    assert ctx["edge_observations"]


def test_empty_edge_response_does_not_record_internal_error(monkeypatch) -> None:
    internal_calls: list[dict] = []
    monkeypatch.setattr("triade.core.edge_observations.record_edge_observation", lambda **_kw: {"status": "ok"})
    monkeypatch.setattr(
        "triade.core.error_bus.record_internal_error",
        lambda *args, **kwargs: internal_calls.append({"args": args, "kwargs": kwargs}),
    )

    _parse_intent_empty()

    assert internal_calls == []


def test_repeated_empty_edge_creates_learning_candidate(tmp_path) -> None:
    from triade.core.edge_observations import record_edge_observation
    from triade.learning.pipeline import LearningPipeline

    db_path = tmp_path / "triade.db"
    for i in range(3):
        record_edge_observation(
            parser_name="intent_probe",
            observation_type="empty_response",
            signal_quality="empty",
            fallback_used=True,
            raw_preview="",
            user_text_preview=f"hola {i}",
            db_path=db_path,
        )

    candidates = LearningPipeline(db_path=db_path).list_candidates(status="candidate", limit=10)

    assert any(c["domain"] == "system_edge_context" for c in candidates)


def test_dashboard_edge_context_health_reports_empty_count(monkeypatch) -> None:
    import triade.core.internal_runtime as runtime_mod
    from apps.api_app import app

    monkeypatch.setattr(
        runtime_mod,
        "build_runtime_heartbeat",
        lambda **_kw: {
            "status": "ok",
            "api_server_alive": True,
            "edge_context_health": {
                "status": "empty_response_repeated",
                "empty_count_24h": 4,
                "last_observation_type": "empty_response",
            },
        },
    )

    response = TestClient(app, raise_server_exceptions=False).get("/api/ui/react-dashboard")
    payload = response.json()

    assert response.status_code == 200
    assert payload["edge_context_health"]["status"] == "empty_response_repeated"
    assert payload["edge_context_health"]["empty_count_24h"] == 4


def test_latest_error_not_polluted_by_edge_empty_response() -> None:
    from triade.core.internal_runtime import _latest_noncritical_filtered_error

    errors = [
        {
            "task_type": "edge_context.parse_model_output",
            "message": "[edge_context.parse_model_output] Expecting value: line 1 column 1 (char 0)",
            "payload": {"context": {"operation": "parse_model_json"}},
        },
        {"task_type": "worker", "message": "[worker] crash real"},
    ]

    latest = _latest_noncritical_filtered_error(errors)

    assert latest["message"] == "[worker] crash real"


def _parse_intent_empty() -> dict:
    from triade.core.edge_context import parse_intent

    return parse_intent("", fallback_text="hola")
