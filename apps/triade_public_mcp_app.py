"""Public, read-only Tríade Ω MCP entrypoint.

This service is intentionally safe to discover anonymously in ChatGPT:
- It cannot query the Bodega, private Colab, or runtime API.
- It has no credential exchange, model hosting or write tools.
- GitHub queries target only WatabooColosus/triadees public metadata.

Authenticated access to private Tríade MUST use the separately protected
MCP gateway with an OAuth 2.1 authorization-code + PKCE integration.
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

_REPO = "WatabooColosus/triadees"
_API = "https://api.github.com/repos/WatabooColosus/triadees"


def _public_git_status() -> dict[str, Any]:
    """Use only fixed, publicly accessible GitHub API and Atom feed URLs."""
    result: dict[str, Any] = {
        "repository": _REPO,
        "source": "public_github",
        "verified": False,
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "TriadeOmegaPublicObservatory/0.2",
    }
    with httpx.Client(timeout=7.0, follow_redirects=False, trust_env=False) as client:
        try:
            response = client.get(_API + "/commits/main", headers=headers)
            response.raise_for_status()
            obj = response.json()
            if not isinstance(obj, dict):
                raise TypeError("unexpected GitHub JSON")
            sha = obj.get("sha")
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
                raise TypeError("invalid Git commit SHA")
            commit = obj.get("commit")
            info = commit if isinstance(commit, dict) else {}
            committer = info.get("committer")
            author = committer if isinstance(committer, dict) else {}
            result.update(
                {
                    "source": "public_github_api",
                    "verified": True,
                    "main_commit": sha,
                    "commit_date_utc": author.get("date"),
                    "evidence_url": "https://github.com/" + _REPO + "/commit/" + sha,
                }
            )
            return result
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            result["api_error_type"] = type(exc).__name__
            if isinstance(exc, httpx.HTTPStatusError):
                result["api_http_status"] = exc.response.status_code

        # GitHub's unauthenticated REST API is often rate-limited on shared
        # cloud IPs. Use its *public* Atom commit feed as a bounded fallback.
        try:
            response = client.get(
                "https://github.com/" + _REPO + "/commits/main.atom",
                headers={
                    "Accept": "application/atom+xml",
                    "User-Agent": "TriadeOmegaPublicObservatory/0.2",
                },
            )
            response.raise_for_status()
            xml = ElementTree.fromstring(response.text)
            entry = xml.find("{http://www.w3.org/2005/Atom}entry")
            if entry is None:
                raise ValueError("public commit feed has no entry")
            link = entry.find("{http://www.w3.org/2005/Atom}link")
            sha = "" if link is None else link.get("href", "").rsplit("/", 1)[-1]
            if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
                raise ValueError("invalid public feed commit SHA")
            result.update(
                {
                    "source": "public_github_atom",
                    "verified": True,
                    "main_commit": sha,
                    "evidence_url": "https://github.com/" + _REPO + "/commit/" + sha,
                }
            )
            return result
        except (httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
            result["feed_error_type"] = type(exc).__name__
            if isinstance(exc, httpx.HTTPStatusError):
                result["feed_http_status"] = exc.response.status_code
    return result


def build_public_app():
    """Construct fresh stateless MCP sessions for Render and integration tests."""
    server = MCPServer(
        "Tríade Ω · Observatorio público",
        instructions=(
            "Interfaz pública de Tríade Ω, creada por Agencia Digital Wataboo. "
            "Consulta solo información pública verificable. No afirmes que el "
            "runtime, sus modelos o la Bodega están conectados por esta interfaz. "
            "Para datos privados exige una conexión OAuth separada y segura."
        ),
    )

    @server.tool(
        description=(
            "Describe el estado y las limitaciones de esta instancia pública "
            "de Tríade. Solo lectura, sin datos personales."
        )
    )
    def triade_estado_publico() -> dict[str, Any]:
        return {
            "organismo": "Tríade Ω",
            "creador": "Agencia Digital Wataboo",
            "instancia": "MCP público de observación",
            "operativo": True,
            "runtime_original_conectado": False,
            "bodega_original_conectada": False,
            "modelos_locales_alojados": False,
            "escrituras_habilitadas": False,
            "limite": (
                "La existencia de este servicio no demuestra aprendizaje "
                "autónomo ni ejecución del sistema original."
            ),
        }

    @server.tool(
        description=(
            "Obtiene el SHA más reciente de la rama main del repositorio "
            "público Tríade Ω mediante la API oficial de GitHub."
        )
    )
    def triade_codigo_publico() -> dict[str, Any]:
        return _public_git_status()

    @server.tool(
        description=(
            "Genera un plan verificable de trabajo para Tríade; no ejecuta "
            "acciones en el runtime ni escribe en la Bodega."
        )
    )
    def triade_plan_publico(objetivo: str) -> dict[str, Any]:
        objetivo = objetivo.strip()
        if not 1 <= len(objetivo) <= 500:
            raise ValueError("objetivo debe tener entre 1 y 500 caracteres")
        return {
            "objetivo": objetivo,
            "creador": "Agencia Digital Wataboo",
            "neurona_central": "Definir pruebas de aceptación y evidencia independiente.",
            "hipotalamo_emocional": "Priorizar impacto humano, claridad y riesgos.",
            "bodega": "Registrar hechos solo en un almacén autorizado y verificado.",
            "gates": [
                "fuentes_publicas_verificables",
                "reproducibilidad",
                "seguridad_y_privacidad",
                "no_promocion_sin_evidencia",
            ],
            "ejecutado": False,
            "nota": "Plan generado; no implica aprendizaje o procesos en background.",
        }

    @server.custom_route("/health", methods=["GET"])
    def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "triade-omega-public-mcp"})

    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
            "triade-omega-mcp.onrender.com",
            "triade-omega-mcp.onrender.com:*",
        ],
        allowed_origins=[],
    )
    return server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=settings,
        max_request_body_size=16384,
    )


app = build_public_app()
