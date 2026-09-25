"""Optional authenticated search; credentials never go to result pages."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from .guarded_web import MAX_RESPONSE_BYTES, USER_AGENT, _assert_public_url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("search_provider_redirect_blocked")


def brave_urls(query: str, *, timeout: int) -> list[str]:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        raise ValueError("brave_api_key_missing")
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": 8, "search_lang": "es"}
    )
    _assert_public_url(url)
    request = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": USER_AGENT,
        "X-Subscription-Token": key,
    })
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        if "application/json" not in str(response.headers.get("Content-Type", "")).lower():
            raise ValueError("search_provider_content_type")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("search_provider_response_too_large")
    payload = json.loads(raw)
    urls = []
    for item in (payload.get("web") or {}).get("results", [])[:8]:
        candidate = str(item.get("url") or "")
        if candidate.startswith(("https://", "http://")) and candidate not in urls:
            urls.append(candidate)
    return urls


def rapidapi_urls(query: str, *, timeout: int) -> list[str]:
    key = os.environ.get("RAPIDAPI_KEY", "").strip()
    if not key:
        raise ValueError("rapidapi_key_missing")
    host = "real-time-web-search.p.rapidapi.com"
    url = f"https://{host}/search-light?" + urllib.parse.urlencode(
        {"q": query, "num": 8, "hl": "es"}
    )
    _assert_public_url(url)
    request = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": USER_AGENT,
        "X-RapidAPI-Key": key, "X-RapidAPI-Host": host,
    })
    # No retries or redirects: a quota/authentication failure must remain visible.
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        if "application/json" not in str(response.headers.get("Content-Type", "")).lower():
            raise ValueError("search_provider_content_type")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("search_provider_response_too_large")
    payload = json.loads(raw)
    if payload.get("status") != "OK":
        raise ValueError("rapidapi_search_failed")
    data = payload.get("data") or {}
    items = data if isinstance(data, list) else data.get("organic_results", [])
    urls = []
    for item in items[:8]:
        candidate = str(item.get("url") or "")
        if candidate.startswith(("https://", "http://")) and candidate not in urls:
            urls.append(candidate)
    return urls
