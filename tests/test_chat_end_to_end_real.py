"""Cierre conversacional real de Fase 1.

La prueba se ejecuta contra un proceso ya levantado en 127.0.0.1:8010 cuando
`TRIADE_REAL_E2E=1`. No sustituye Ollama por un mock: si el modo real está
solicitado, cualquier fallo de frontend, API, Runner, Central o modelo local
hace fallar la prueba.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, cast
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest

BASE_URL = os.getenv("TRIADE_E2E_BASE_URL", "http://127.0.0.1:8010")


def _json_request(path: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Request-ID": "phase1-real-e2e"},
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


@pytest.mark.skipif(
    os.getenv("TRIADE_REAL_E2E") != "1",
    reason="requiere un runtime local levantado y TRIADE_REAL_E2E=1",
)
def test_real_chat_frontend_api_central_local_model() -> None:
    """Prueba el trayecto SPA → /api/run → Central → Ollama → SPA."""
    try:
        with urlopen(f"{BASE_URL}/", timeout=15) as response:
            html = response.read().decode("utf-8")
            assert response.status == 200
    except URLError as exc:  # pragma: no cover - diagnóstico del entorno real
        pytest.fail(f"frontend no accesible: {exc}")

    scripts = re.findall(r'<script[^>]+src="([^"]+\.js)"', html)
    assert scripts, "la SPA no publica un bundle JavaScript"
    with urlopen(f"{BASE_URL}{scripts[0]}", timeout=15) as response:
        bundle = response.read().decode("utf-8")
    assert "/api/run" in bundle, "el frontend no apunta al endpoint conversacional"

    payload = _json_request(
        "/api/run",
        {
            "text": "Responde únicamente: TRIADA_VIVA",
            "source": "phase1-real-e2e",
            "use_ollama": True,
            "auto_select_models": True,
            "semantic_recall_enabled": False,
            "debug": False,
        },
    )
    assert payload.get("status") not in {"error", "failed"}
    assert payload.get("response") == "TRIADA_VIVA"
    assert payload.get("run_id")
    memory_diff = cast(dict[str, Any], payload.get("memory_diff") or {})
    assert memory_diff.get("episode_id")
    assert memory_diff.get("db_path")
    models = cast(dict[str, Any], payload.get("models") or {})
    central_models = cast(dict[str, Any], models.get("central") or {})
    assert central_models.get("provider") == "ollama"
    assert central_models.get("ok") is True
