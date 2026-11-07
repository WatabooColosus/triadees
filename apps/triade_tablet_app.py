"""Tablet-first, read-only public web console mounted beside the existing MCP.

Public endpoints share the same providers as the MCP tools. They never access
Tríade's private Bodega, runtime, secret env vars, or command execution.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

ASSETS = Path(__file__).resolve().parent / "tablet_assets"

SAFE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
PAGE_HEADERS = {
    **SAFE_HEADERS,
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "font-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "manifest-src 'self'; worker-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
}


def attach_tablet_routes(
    app: Any,
    *,
    status_provider: Callable[[], dict[str, Any]],
    code_provider: Callable[[], dict[str, Any]],
    plan_provider: Callable[[str], dict[str, Any]],
) -> Any:
    """Expose the public observatory via a mobile-first web UI and JSON APIs."""

    async def home(_request: Request) -> FileResponse:
        return FileResponse(
            ASSETS / "index.html",
            media_type="text/html; charset=utf-8",
            headers=PAGE_HEADERS,
        )

    async def stylesheet(_request: Request) -> FileResponse:
        return FileResponse(
            ASSETS / "ui.css",
            media_type="text/css; charset=utf-8",
            headers=SAFE_HEADERS,
        )

    async def javascript(_request: Request) -> FileResponse:
        return FileResponse(
            ASSETS / "ui.js",
            media_type="text/javascript; charset=utf-8",
            headers=SAFE_HEADERS,
        )

    async def manifest(_request: Request) -> FileResponse:
        return FileResponse(
            ASSETS / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers=SAFE_HEADERS,
        )

    async def icon(_request: Request) -> FileResponse:
        return FileResponse(
            ASSETS / "icon.svg",
            media_type="image/svg+xml",
            headers=SAFE_HEADERS,
        )

    async def worker(_request: Request) -> FileResponse:
        return FileResponse(
            ASSETS / "sw.js",
            media_type="text/javascript",
            headers={**SAFE_HEADERS, "Service-Worker-Allowed": "/"},
        )

    async def status(_request: Request) -> JSONResponse:
        return JSONResponse(status_provider(), headers=SAFE_HEADERS)

    async def code(_request: Request) -> JSONResponse:
        # This fetches a fixed *public* GitHub URL; it can be unavailable.
        # A failed verification must remain visible, never become a fake SHA.
        return JSONResponse(code_provider(), headers=SAFE_HEADERS)

    async def plan(request: Request) -> JSONResponse:
        content_type = request.headers.get("content-type", "").split(";", 1)[0]
        if content_type.lower() != "application/json":
            return JSONResponse(
                {"error": "Se requiere application/json"},
                status_code=415,
                headers=SAFE_HEADERS,
            )
        if (
            request.headers.get("content-length", "").isdigit()
            and int(request.headers["content-length"]) > 2048
        ):
            return JSONResponse(
                {"error": "Solicitud demasiado extensa"},
                status_code=413,
                headers=SAFE_HEADERS,
            )
        body = await request.body()
        if len(body) > 2048:
            return JSONResponse(
                {"error": "Solicitud demasiado extensa"},
                status_code=413,
                headers=SAFE_HEADERS,
            )
        try:
            parsed = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse(
                {"error": "JSON inválido"}, status_code=400, headers=SAFE_HEADERS
            )
        if (
            not isinstance(parsed, dict)
            or set(parsed) != {"objetivo"}
            or not isinstance(parsed["objetivo"], str)
        ):
            return JSONResponse(
                {"error": "Solo se acepta un objetivo de texto"},
                status_code=400,
                headers=SAFE_HEADERS,
            )
        objetivo = parsed["objetivo"].strip()
        if not 1 <= len(objetivo) <= 500:
            return JSONResponse(
                {"error": "El objetivo debe tener entre 1 y 500 caracteres"},
                status_code=422,
                headers=SAFE_HEADERS,
            )
        return JSONResponse(plan_provider(objetivo), headers=SAFE_HEADERS)

    # Keep the existing MCP transport and health endpoint unchanged.
    app.routes.extend(
        [
            Route("/", home, methods=["GET"], name="triade-tablet-home"),
            Route("/ui.css", stylesheet, methods=["GET"]),
            Route("/ui.js", javascript, methods=["GET"]),
            Route("/manifest.webmanifest", manifest, methods=["GET"]),
            Route("/icon.svg", icon, methods=["GET"]),
            Route("/sw.js", worker, methods=["GET"]),
            Route("/api/public/status", status, methods=["GET"]),
            Route("/api/public/code", code, methods=["GET"]),
            Route("/api/public/plan", plan, methods=["POST"]),
        ]
    )
    return app
