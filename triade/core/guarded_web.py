"""Investigación web explícita, acotada y auditable para Tríade Ω."""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
from typing import Any

MAX_RESPONSE_BYTES = 350_000
MAX_SOURCES = 3
USER_AGENT = "TriadeOmega/1.0 guarded-research"


def requests_web_research(text: str) -> bool:
    normalized = text.lower()
    return any(marker in normalized for marker in (
        "busca en internet", "buscar en internet", "investiga en internet",
        "consulta internet", "consulta la web", "busca en la web",
        "investiga en la web", "verifica en internet",
    ))


def guarded_web_research(query: str, *, timeout: int = 8, max_sources: int = MAX_SOURCES) -> dict[str, Any]:
    """Busca con DuckDuckGo HTML y extrae texto de resultados públicos.

    No ejecuta JavaScript, no usa cookies, no acepta URLs privadas y limita el
    volumen. La salida es evidencia temporal con URLs, no memoria estable.
    """
    clean_query = _clean_query(query)
    if not clean_query:
        return {"status": "skipped", "query": "", "sources": [], "reason": "empty_query"}
    search_url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": clean_query})
    try:
        search_html = _download(search_url, timeout=timeout).decode("utf-8", errors="replace")
        urls = _result_urls(search_html)
    except Exception as exc:
        urls = []
        search_error = str(exc)
    else:
        search_error = ""

    if not urls:
        sources = _wikipedia_sources(clean_query, timeout=timeout, max_sources=max_sources)
        return {
            "status": "ok" if sources else "degraded",
            "query": clean_query,
            "sources": sources,
            "source_count": len(sources),
            "search_provider": "wikipedia_api_fallback",
            "search_warning": search_error or "primary_search_returned_no_results",
            "policy": "explicit_request_public_http_no_javascript_evidence_only",
            "stable_memory_written": False,
        }

    sources: list[dict[str, str]] = []
    for url in urls:
        if len(sources) >= max(1, min(max_sources, MAX_SOURCES)):
            break
        try:
            raw = _download(url, timeout=timeout).decode("utf-8", errors="replace")
            text = _visible_text(raw)[:1800]
            if len(text) < 80:
                continue
            sources.append({"url": url, "title": _title(raw) or urllib.parse.urlparse(url).netloc, "excerpt": text})
        except Exception:
            continue
    return {
        "status": "ok" if sources else "degraded",
        "query": clean_query,
        "sources": sources,
        "source_count": len(sources),
        "policy": "explicit_request_public_http_no_javascript_evidence_only",
        "stable_memory_written": False,
    }


def _wikipedia_sources(query: str, *, timeout: int, max_sources: int) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": query,
        "gsrlimit": max(1, min(max_sources, MAX_SOURCES)), "prop": "extracts|info",
        "exintro": 1, "explaintext": 1, "inprop": "url", "format": "json", "utf8": 1,
    })
    url = "https://es.wikipedia.org/w/api.php?" + params
    try:
        payload = json.loads(_download_json(url, timeout=timeout).decode("utf-8"))
    except Exception:
        return []
    pages = (payload.get("query") or {}).get("pages") or {}
    result = []
    for page in pages.values():
        excerpt = " ".join(str(page.get("extract") or "").split())[:1800]
        source_url = str(page.get("fullurl") or "")
        if excerpt and source_url:
            result.append({"url": source_url, "title": str(page.get("title") or "Wikipedia"), "excerpt": excerpt})
    return result[:max_sources]


def _clean_query(query: str) -> str:
    query = re.sub(
        r"(?i)\b(busca(?:r)?|investiga(?:r)?|consulta(?:r)?|verifica(?:r)?)\s+(?:en\s+)?(?:la\s+)?(?:internet|web)\b[:\s,-]*",
        "", query,
    )
    return " ".join(query.split())[:300]


def _download(url: str, *, timeout: int) -> bytes:
    _assert_public_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        _assert_public_url(final_url)
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise ValueError("content_type_not_allowed")
        return response.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES]


def _download_json(url: str, *, timeout: int) -> bytes:
    _assert_public_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        _assert_public_url(response.geturl())
        if "json" not in str(response.headers.get("Content-Type") or "").lower():
            raise ValueError("content_type_not_allowed")
        return response.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES]


def _assert_public_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url_not_allowed")
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("private_host_blocked")
    for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global:
            raise ValueError("private_address_blocked")


def _result_urls(page: str) -> list[str]:
    found: list[str] = []
    for href in re.findall(r'class="result__a"[^>]+href="([^"]+)"', page):
        decoded = html.unescape(href)
        parsed = urllib.parse.urlparse(decoded)
        if parsed.netloc.endswith("duckduckgo.com"):
            decoded = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        if decoded.startswith(("http://", "https://")) and decoded not in found:
            found.append(decoded)
    return found[:8]


def _visible_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript|svg).*?>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    return " ".join(html.unescape(page).split())


def _title(page: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    return " ".join(html.unescape(match.group(1)).split())[:200] if match else ""


def web_context_for_prompt(result: dict[str, Any]) -> str:
    safe = {"query": result.get("query"), "sources": result.get("sources", []), "policy": result.get("policy")}
    return json.dumps(safe, ensure_ascii=False, indent=2)
