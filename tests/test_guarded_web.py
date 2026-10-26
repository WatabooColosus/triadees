import pytest

from triade.core.guarded_web import (
    _assert_public_url,
    _clean_query,
    requests_web_research,
)
from triade.core.permission_governor import build_permission_profile
from triade.core.resource_governor import decide_work_mode


def test_web_research_requires_explicit_request():
    assert requests_web_research("busca en internet la historia de Medellín") is True
    assert requests_web_research("cuéntame la historia de Medellín") is False
    assert (
        _clean_query("busca en internet la historia de Medellín")
        == "la historia de Medellín"
    )


def test_guard_blocks_private_hosts():
    with pytest.raises(ValueError):
        _assert_public_url("http://127.0.0.1:8010/private")
    with pytest.raises(ValueError):
        _assert_public_url("file:///etc/passwd")


@pytest.mark.parametrize(
    "query",
    [
        "quiero que busques en internet y me des la fuente de donde lo sacaste, dame los 5 presidentes de latinoamierca actuales",
        "investigues en la web",
        "consulta internet",
        "verifiques en internet",
    ],
)
def test_conjugated_explicit_requests(query):
    assert requests_web_research(query)


@pytest.mark.parametrize(
    "query",
    [
        "no busques en internet",
        "sin consultar internet",
        "evita buscar en la web",
    ],
)
def test_negative_web_requests(query):
    assert not requests_web_research(query)


def test_failed_explicit_search_cannot_fall_back_to_model_facts():
    from triade.core.guarded_web import web_failure_response

    request = "quiero que busques en internet los presidentes actuales"
    for result in (None, {}, {"status": "error", "sources": []}):
        assert "No puedo confirmar los datos actuales" in web_failure_response(
            request, result
        )
    assert (
        web_failure_response(request, {"sources": [{"url": "https://example.org"}]})
        is None
    )
    assert web_failure_response("hola", None) is None


def test_learning_filter_rejects_irrelevant_conversation_sources(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from triade.core.runner_preflight import enrich_research
    from triade.research import AutonomousResearchEngine

    original = {"sources": [{"url": "https://example.org", "excerpt": "Evidence"}]}
    packet = SimpleNamespace(context={"guarded_web_research": original})
    monkeypatch.setattr(
        "triade.memory.continuity_truth.memory_truth_snapshot", lambda path: {}
    )
    monkeypatch.setattr(AutonomousResearchEngine, "__init__", lambda self, path: None)
    monkeypatch.setattr(
        AutonomousResearchEngine,
        "ingest_result",
        lambda *a, **k: {"status": "insufficient_material", "sources": []},
    )
    enrich_research(
        packet, SimpleNamespace(), "busques en internet", "test", tmp_path / "test.db"
    )
    assert packet.context["guarded_web_research"]["sources"] == []
    assert packet.context["autonomous_research"]["status"] == "insufficient_material"


def test_results_accept_attribute_order_quotes_and_multiple_classes():
    from triade.core.guarded_web import _result_urls

    page = """<a href='https://docs.python.org/3/' class='link result__a'>Python</a>
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2F">Other</a>
    <a class='result__a' href='https://docs.python.org/3/'>Duplicate</a>"""
    assert _result_urls(page) == ["https://docs.python.org/3/", "https://example.org/"]


def test_redirect_is_blocked_before_contacting_private_target():
    from urllib.request import Request

    from triade.core.guarded_web import _PublicRedirectHandler

    with pytest.raises(ValueError, match="private"):
        _PublicRedirectHandler().redirect_request(
            Request("https://example.org"),
            None,
            302,
            "Found",
            {},
            "http://127.0.0.1/private",
        )


def test_fallback_is_bounded_and_identified(monkeypatch):
    from triade.core import guarded_web as web

    monkeypatch.setattr(web, "_download", lambda *a, **k: b"<html>no results</html>")
    observed = []

    def curated(query, *, timeout, max_sources):
        observed.append(max_sources)
        return [{"url": "https://example.org"}] * max_sources

    monkeypatch.setattr(web, "_curated_sources", curated)
    result = web.guarded_web_research("Python", max_sources=100)
    assert observed == [web.MAX_SOURCES]
    assert result["search_provider"] == "curated_and_wikipedia_fallback"
    assert result["stable_memory_written"] is False


def test_full_local_guarded_capabilities_are_consistent():
    probe = {
        "limits": {
            "ram_available_gb": 16,
            "disk_free_gb": 100,
            "tier": "high",
            "cpu_count": 8,
        },
        "cpu": {"load_1min": 1.0},
        "power": {"ac_connected": True, "battery_percent": 100},
        "thermal": {"thermal_status": "ok"},
        "warnings": [],
    }
    result = decide_work_mode(
        probe,
        {"status": "ok", "can_reason": True, "can_embed": True},
        "full_local_guarded",
    )
    assert result["can_run_tests"] is True
    assert result["can_run_build"] is True
    assert result["can_research_web"] is True
    permissions = build_permission_profile("full_local_guarded")
    assert permissions["permissions"]["can_research_web"] is True
    assert permissions["permissions"]["can_run_shell"] is False
    assert permissions["permissions"]["can_run_safe_shell"] is True
