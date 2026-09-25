import json
from urllib.request import Request

import pytest

from triade.core import guarded_web, search_provider


@pytest.mark.parametrize("provider,key", [("brave", "BRAVE_SEARCH_API_KEY"), ("rapidapi", "RAPIDAPI_KEY")])
def test_missing_key_never_contacts_network(monkeypatch, provider, key):
    monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(search_provider, "_assert_public_url", lambda url: pytest.fail("network called"))
    with pytest.raises(ValueError, match="key_missing"):
        getattr(search_provider, provider + "_urls")("presidentes", timeout=1)


def test_credentials_cannot_follow_redirects():
    with pytest.raises(ValueError, match="redirect_blocked"):
        search_provider._NoRedirect().redirect_request(
            Request("https://api.search.brave.com", headers={"X-Subscription-Token": "test"}),
            None, 302, "Found", {}, "https://other.example/",
        )


@pytest.mark.parametrize("data", [[{"url": "https://example.org"}], {"organic_results": [{"url": "https://example.org"}]}])
def test_rapidapi_contract_and_light_endpoint(monkeypatch, data):
    monkeypatch.setenv("RAPIDAPI_KEY", "test-only-not-a-secret")
    monkeypatch.setattr(search_provider, "_assert_public_url", lambda url: None)

    class Response:
        def __init__(self):
            self.headers = {"Content-Type": "application/json"}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            return json.dumps({"status": "OK", "data": data}).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.full_url.startswith("https://real-time-web-search.p.rapidapi.com/search-light?")
            assert request.get_header("X-rapidapi-key") == "test-only-not-a-secret"
            return Response()

    monkeypatch.setattr(search_provider.urllib.request, "build_opener", lambda *a: Opener())
    assert search_provider.rapidapi_urls("presidentes", timeout=1) == ["https://example.org"]


def test_irrelevant_wikipedia_fallback_is_rejected(monkeypatch):
    monkeypatch.setattr(guarded_web, "_download_json", lambda *a, **k: json.dumps({
        "query": {"pages": {"1": {"title": "Disney Channel Latinoamerica", "extract": "Canal de television", "fullurl": "https://es.wikipedia.org/wiki/Disney_Channel"}}}
    }).encode())
    assert guarded_web._wikipedia_sources("presidentes latinoamerica actuales", timeout=1, max_sources=3) == []


def test_captcha_is_degraded_not_success(monkeypatch):
    monkeypatch.setenv("TRIADE_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr(guarded_web, "_download", lambda *a, **k: b'<form class="anomaly-modal">')
    monkeypatch.setattr(guarded_web, "_curated_sources", lambda *a, **k: [])
    monkeypatch.setattr(guarded_web, "_wikipedia_sources", lambda *a, **k: [])
    result = guarded_web.guarded_web_research("presidentes")
    assert result["status"] == "degraded"
    assert result["search_warning"] == "search_provider_challenge"


def test_failed_explicit_search_is_not_repeated(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from triade.core.runner_preflight import enrich_research
    from triade.research import AutonomousResearchEngine

    monkeypatch.setattr("triade.memory.continuity_truth.memory_truth_snapshot", lambda p: {})
    monkeypatch.setattr(AutonomousResearchEngine, "__init__", lambda self, p: None)
    monkeypatch.setattr(AutonomousResearchEngine, "should_research", lambda *a, **k: pytest.fail("duplicate search"))
    failed = {"status": "degraded", "sources": [], "search_warning": "quota"}
    packet = SimpleNamespace(context={"guarded_web_research": failed})
    enrich_research(packet, SimpleNamespace(), "busca en internet", "test", tmp_path / "db")
    assert packet.context["guarded_web_research"] == failed
