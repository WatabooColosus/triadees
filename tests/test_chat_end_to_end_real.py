"""Certificación real del runtime: conversación y organismo completo.

Dos niveles, ambos contra un proceso ya levantado en 127.0.0.1:8010:

- `TRIADE_REAL_E2E=1` prueba el circuito conversacional
  (SPA → `/api/run` → Runner → Central → Ollama local → Bodega).
- `TRIADE_FULL_CERT=1` añade la certificación full: falla si el runtime está
  en modo conversacional reducido, si los workers, LIFE_PULSE o el metabolismo
  no están activos, o si Ollama, la API o el frontend no son accesibles.

No se sustituye Ollama por un mock: si el modo real está solicitado, cualquier
fallo de frontend, API, Runner, Central o modelo local hace fallar la prueba.
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

real_e2e = pytest.mark.skipif(
    os.getenv("TRIADE_REAL_E2E") != "1",
    reason="requiere un runtime local levantado y TRIADE_REAL_E2E=1",
)
full_cert = pytest.mark.skipif(
    os.getenv("TRIADE_FULL_CERT") != "1",
    reason="certificación full: requiere el organismo completo y TRIADE_FULL_CERT=1",
)


def _json_request(path: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Request-ID": "phase1-real-e2e"},
        method="POST",
    )
    with urlopen(request, timeout=300) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def _get_json(path: str, timeout: int = 180) -> dict[str, Any]:
    try:
        with urlopen(f"{BASE_URL}{path}", timeout=timeout) as response:
            assert response.status == 200, f"{path} devolvió {response.status}"
            return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
    except URLError as exc:  # pragma: no cover - diagnóstico del entorno real
        pytest.fail(f"{path} no accesible: {exc}")


@real_e2e
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
        assert response.status == 200, "el bundle declarado en el HTML no se sirve"
        bundle = response.read().decode("utf-8")
    assert "/api/run" in bundle, "el frontend no apunta al endpoint conversacional"

    # El contrato del sistema —status, run_id, Central en Ollama local y
    # episodio persistido— se exige en CADA intento. Lo único que se reintenta
    # es la cadena exacta: la produce un modelo local de 3B con temperatura, y
    # medido sobre este runtime falla ~1 de cada 7 escribiendo `TRIADE_VIVA`
    # (el nombre del propio sistema) en lugar de `TRIADA_VIVA`. Reintentar la
    # transcripción no rebaja lo que se prueba: si la ruta estuviera rota, los
    # asertos de cada intento fallarían igual y no habría segundo intento.
    ultima: dict[str, object] = {}
    for _ in range(3):
        payload = _json_request(
            "/api/run",
            {
                "text": "Responde únicamente: TRIADA_VIVA",
                "source": "phase1-real-e2e",
                "use_ollama": True,
                "auto_select_models": True,
                "debug": False,
            },
        )
        assert payload.get("status") not in {"error", "failed"}
        assert payload.get("run_id")
        memory_diff = cast(dict[str, Any], payload.get("memory_diff") or {})
        assert memory_diff.get("episode_id")
        assert memory_diff.get("db_path")
        models = cast(dict[str, Any], payload.get("models") or {})
        central_models = cast(dict[str, Any], models.get("central") or {})
        assert central_models.get("provider") == "ollama"
        assert central_models.get("ok") is True
        ultima = payload
        if payload.get("response") == "TRIADA_VIVA":
            break
    assert ultima.get("response") == "TRIADA_VIVA", (
        "el modelo local no devolvió la frase exacta en 3 intentos: "
        f"{ultima.get('response')!r}"
    )


@real_e2e
@full_cert
def test_full_runtime_is_not_conversation_only() -> None:
    """La certificación full falla si el organismo arrancó recortado.

    `conversation_only` cortocircuita el lifespan: no arranca workers, ni
    runner continuo, ni metabolismo. La app sigue devolviendo 200 y el chat
    sigue contestando, así que sin esta comprobación un runtime reducido se
    certifica como completo.
    """
    deep = _get_json("/health/deep")
    runtime_mode = cast(dict[str, Any], deep.get("runtime_mode") or {})
    assert runtime_mode.get("conversation_only") is False, (
        "runtime en modo conversacional reducido: "
        f"{runtime_mode}. La certificación full exige el organismo completo."
    )
    assert runtime_mode.get("status") != "conversation_only"
    assert runtime_mode.get("status") != "isolated_test_runtime"


@real_e2e
@full_cert
def test_full_runtime_organs_are_active() -> None:
    """Workers, LIFE_PULSE, Ollama y Bodega, activos a la vez."""
    heartbeat = _get_json("/api/runtime/heartbeat")

    assert heartbeat.get("workers_active") is True, "workers requeridos apagados"
    assert heartbeat.get("mode") == "full_local_guarded", (
        f"modo de runtime inesperado: {heartbeat.get('mode')}"
    )

    always_on = cast(dict[str, Any], heartbeat.get("always_on") or {})
    assert always_on.get("status") == "running", f"always_on no corre: {always_on}"
    assert always_on.get("background_thread_alive") is True

    services = cast(
        dict[str, Any], (heartbeat.get("runtime_state") or {}).get("services") or {}
    )
    life_pulse = cast(dict[str, Any], services.get("life_pulse") or {})
    assert life_pulse.get("running") is True, f"LIFE_PULSE apagado: {life_pulse}"

    ollama_health = cast(dict[str, Any], heartbeat.get("ollama_health") or {})
    assert ollama_health.get("ok") is True, f"Ollama inaccesible: {ollama_health}"
    assert ollama_health.get("required_models_present") is True

    ollama_blood = cast(dict[str, Any], heartbeat.get("ollama_blood") or {})
    assert ollama_blood.get("can_reason") is True

    semantic_memory = cast(dict[str, Any], services.get("semantic_memory") or {})
    assert semantic_memory.get("status") == "ok", f"Bodega degradada: {semantic_memory}"

    worker_loop = cast(dict[str, Any], services.get("worker_loop") or {})
    assert worker_loop.get("status") == "ok", f"worker_loop degradado: {worker_loop}"


@real_e2e
@full_cert
def test_full_runtime_metabolism_is_running() -> None:
    """El metabolismo requerido no puede estar apagado en la certificación."""
    status = _get_json("/api/runtime/metabolism/status")
    metabolism = cast(dict[str, Any], status.get("metabolism") or {})
    assert metabolism.get("enabled") is True, "metabolismo requerido apagado"
    assert metabolism.get("running") is True, f"metabolismo no corre: {metabolism}"
    assert metabolism.get("last_tick_error") is None
    assert int(metabolism.get("cycle_count") or 0) > 0, (
        "el metabolismo está declarado pero no ha completado ningún ciclo"
    )


@real_e2e
@full_cert
def test_url_stays_available_while_the_organism_works() -> None:
    """La URL no puede caerse mientras el organismo trabaja por detrás.

    Es la condición que motivó apagar el runtime completo: si los procesos de
    fondo saturan el proceso, `/` y `/health` dejan de responder. Apagar el
    organismo para conseguir verde no es una reparación, así que esto se
    comprueba con el organismo encendido.
    """
    for _ in range(10):
        with urlopen(f"{BASE_URL}/health", timeout=60) as response:
            assert response.status == 200
        with urlopen(f"{BASE_URL}/", timeout=60) as response:
            assert response.status == 200
            assert b'<div id="root">' in response.read()
