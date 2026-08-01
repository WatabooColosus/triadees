"""Fijar temperatura y semilla para que una evaluación sea reproducible.

Hasta ahora `generate()` no exponía `options`, así que una medición
control/tratamiento no podía declarar su temperatura: ambos grupos compartían
el defecto de Ollama, pero sin dejarlo por escrito en la evidencia.

Lo importante es que añadirlo no cambie nada para quien no lo use.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from triade.models.ollama_client import OllamaClient


class _CapturaPayload:
    """Sustituye a urlopen y guarda el cuerpo enviado."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        self.payloads.append(json.loads(request.data.decode("utf-8")))

        class _Resp:
            def read(self_inner) -> bytes:
                return b'{"response": "ok"}'

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a: object) -> None:
                return None

        return _Resp()


@pytest.fixture
def captura(monkeypatch: pytest.MonkeyPatch) -> _CapturaPayload:
    cap = _CapturaPayload()
    monkeypatch.setattr("urllib.request.urlopen", cap)
    return cap


def test_las_options_llegan_al_payload(captura) -> None:
    OllamaClient().generate(
        "m", "hola", options={"temperature": 0, "seed": 42, "top_p": 0.9}
    )
    assert captura.payloads[0]["options"] == {
        "temperature": 0,
        "seed": 42,
        "top_p": 0.9,
    }


def test_sin_options_el_payload_no_cambia(captura) -> None:
    """Ninguna llamada existente debe alterar su comportamiento."""
    OllamaClient().generate("m", "hola")
    payload = captura.payloads[0]
    assert "options" not in payload
    assert payload == {"model": "m", "prompt": "hola", "stream": False}


def test_control_y_tratamiento_reciben_las_mismas_options(captura) -> None:
    opciones = {"temperature": 0, "seed": 7}
    c = OllamaClient()
    c.generate("m", "control", options=opciones)
    c.generate("m", "tratamiento con memoria", options=opciones)
    assert captura.payloads[0]["options"] == captura.payloads[1]["options"]
    assert captura.payloads[0]["prompt"] != captura.payloads[1]["prompt"]


def test_las_options_no_se_comparten_por_referencia(captura) -> None:
    """Mutar el dict del llamante no debe reescribir un payload ya enviado."""
    opciones = {"temperature": 0}
    OllamaClient().generate("m", "hola", options=opciones)
    opciones["temperature"] = 1
    assert captura.payloads[0]["options"] == {"temperature": 0}


def test_el_system_sigue_funcionando_junto_a_options(captura) -> None:
    OllamaClient().generate("m", "hola", system="eres X", options={"seed": 1})
    payload = captura.payloads[0]
    assert payload["system"] == "eres X"
    assert payload["options"] == {"seed": 1}
