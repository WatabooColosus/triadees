"""El `request_id` une lo que vio el cliente con lo que quedó escrito.

Antes de esto la única correlación era `run_id`, que nace dentro del Runner: si
la petición moría antes —safety, autenticación, validación— no quedaba nada que
la ligara a sus trazas. Estas pruebas fijan las tres propiedades que lo hacen
útil: que siempre haya uno, que sobreviva al guardián y que no se contagie entre
peticiones.
"""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

from triade.core.request_context import (
    REQUEST_ID_HEADER,
    get_request_id,
    new_request_id,
    normalize_request_id,
)


@pytest.fixture
def client() -> TestClient:
    import apps.single_port_app as app_module

    return TestClient(app_module.app)


def test_genera_un_id_cuando_el_cliente_no_manda_ninguno(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER, "").startswith("req-")


def test_respeta_el_id_del_cliente(client: TestClient) -> None:
    response = client.get("/health/live", headers={REQUEST_ID_HEADER: "cert-phase-8"})
    assert response.headers[REQUEST_ID_HEADER] == "cert-phase-8"


def test_dos_peticiones_no_comparten_id(client: TestClient) -> None:
    """El ContextVar se resetea: sin eso, la segunda hereda el de la primera."""
    primero = client.get("/health/live", headers={REQUEST_ID_HEADER: "el-primero"})
    segundo = client.get("/health/live")
    assert primero.headers[REQUEST_ID_HEADER] == "el-primero"
    assert segundo.headers[REQUEST_ID_HEADER] != "el-primero"
    assert segundo.headers[REQUEST_ID_HEADER].startswith("req-")


@pytest.mark.parametrize(
    "hostil",
    [
        "con espacio",
        "salto\nde-linea",
        "x" * 65,
        "",
        "punto;coma",
        "../../etc/passwd",
    ],
)
def test_descarta_ids_no_seguros_y_genera_uno(client: TestClient, hostil: str) -> None:
    """Un id inválido acaba en logs, en la base y en JSON: se descarta entero.

    No se sanea ni se trunca a propósito — un id a medias se parece demasiado a
    uno bueno y correlacionaría cosas distintas.
    """
    response = client.get("/health/live", headers={REQUEST_ID_HEADER: hostil})
    devuelto = response.headers[REQUEST_ID_HEADER]
    assert devuelto != hostil
    assert devuelto.startswith("req-")


def test_normalize_acepta_lo_seguro_y_rechaza_lo_demas() -> None:
    assert normalize_request_id("abc-123_ok.9:x") == "abc-123_ok.9:x"
    assert normalize_request_id(None).startswith("req-")
    assert normalize_request_id("tiene espacio").startswith("req-")


def test_ids_generados_son_distintos() -> None:
    assert len({new_request_id() for _ in range(200)}) == 200


def test_fuera_de_una_peticion_no_hay_id() -> None:
    """En workers y metabolismo no hay petición: inventar un id mentiría."""
    assert get_request_id() is None


def test_una_peticion_rechazada_por_el_guardian_tambien_lleva_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El caso que fija el orden de los middlewares.

    `request_id_middleware` tiene que envolver a `public_guarded_mode`. Si se
    registrara al revés, un 403 saldría sin cabecera — y esa es justo la
    petición que más falta hace poder rastrear.
    """
    monkeypatch.setenv("TRIADE_PUBLIC_GUARDED", "1")
    import apps.single_port_app as app_module

    importlib.reload(app_module)
    try:
        with TestClient(app_module.app) as guarded:
            response = guarded.post("/api/run", json={"text": "hola"})
        assert response.status_code == 403
        assert response.json()["detail"] == "authenticated_session_required"
        assert response.headers.get(REQUEST_ID_HEADER, "").startswith("req-")
    finally:
        monkeypatch.delenv("TRIADE_PUBLIC_GUARDED", raising=False)
        os.environ.pop("TRIADE_PUBLIC_GUARDED", None)
        importlib.reload(app_module)
