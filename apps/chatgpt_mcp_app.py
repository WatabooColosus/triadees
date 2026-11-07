"""Opt-in MCP v2 Streamable HTTP adapter for a real, external Tríade runtime.

This application exposes three MCP tools, delegates to the already hardened
ChatGPT Actions gateway and never opens the original Bodega. No persistent
learning or execution claims are made without observing upstream evidence.

Requires optional `mcp>=2.0,<3` installed via requirements-mcp.txt.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from apps import chatgpt_actions_app as gateway


class BearerGuard:
    """Require a configured, constant-time checked bearer for all MCP traffic."""

    def __init__(self, inner: ASGIApp) -> None:
        self.inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.inner(scope, receive, send)
            return
        secret = os.environ.get("TRIADE_ACTIONS_TOKEN", "").strip()
        if not secret:
            response = JSONResponse({"error": "gateway_not_configured"}, status_code=503)
        else:
            raw = Headers(scope=scope).get("authorization", "")
            scheme, separator, supplied = raw.partition(" ")
            if (
                not separator
                or scheme.lower() != "bearer"
                or not hmac.compare_digest(supplied, secret)
            ):
                response = JSONResponse(
                    {"error": "invalid_token"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            else:
                await self.inner(scope, receive, send)
                return
        await response(scope, receive, send)


def _allowlisted_hosts() -> list[str]:
    """Set explicit public Host names; never use a wildcard that accepts any host."""
    local = ["127.0.0.1", "localhost", "[::1]"]
    raw = os.environ.get("TRIADE_MCP_PUBLIC_HOST", "").strip().lower()
    if not raw:
        raw = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip().lower()
    if raw:
        # The provider should pass a bare domain, not a URL or an arbitrary pattern.
        if (
            ":" in raw
            or "/" in raw
            or "*" in raw
            or " " in raw
            or raw.startswith(".")
            or raw.endswith(".")
        ):
            raise ValueError("TRIADE_MCP_PUBLIC_HOST must be a bare DNS name")
        local.append(raw)
    return [part for host in local for part in (host, host + ":*")]


def build_app() -> ASGIApp:
    """Construct the official MCP v2 transport, guarded by bearer authentication."""
    from mcp.server.mcpserver import MCPServer
    from mcp.server.transport_security import TransportSecuritySettings

    mcp = MCPServer(
        "Tríade Ω",
        instructions=(
            "Consultar el runtime Tríade real con evidencia. "
            "No declares actividad ni aprendizaje certificados sin pruebas independientes. "
            "La acción de ejecutar puede modificar la Bodega; está desactivada por defecto."
        ),
    )

    @mcp.tool(description="Consulta el estado real del runtime (solo lectura, resumen filtrado).")
    def triade_estado() -> dict[str, Any]:
        return gateway.status(None)

    @mcp.tool(description="Consulta estadísticas de aprendizaje de Tríade (solo lectura, sin datos privados).")
    def triade_aprendizaje(limit: int = 20) -> dict[str, Any]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        return gateway.learning(None, limit)

    @mcp.tool(
        description=(
            "Ejecuta un ciclo del runtime Tríade original. PUEDE ESCRIBIR en la "
            "Bodega. Está desactivado por defecto y requiere autorización explícita."
        )
    )
    def triade_ejecutar(text: str) -> dict[str, Any]:
        if not 1 <= len(text) <= 3000:
            raise ValueError("text length must be 1..3000")
        return gateway.run(gateway.RunInput(text=text, use_ollama=False), None)

    @mcp.custom_route("/health", methods=["GET"])
    def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "triade-mcp-gateway"})

    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowlisted_hosts(),
        allowed_origins=[],  # No browser-origin access is required for ChatGPT MCP.
    )
    server = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=settings,
        max_request_body_size=32768,
    )
    return BearerGuard(server)


# Uvicorn entrypoint for separate, low-resource deployment.
app = build_app()
