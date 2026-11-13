"""La CSP protege de verdad y además deja cargar el favicon.

El favicon va embebido como `data:image/svg+xml` en `frontend/index.html`, para
no pedir un `/favicon.ico` que daba 404 permanente. Con `default-src 'self'` a
secas el navegador lo bloqueaba: la SPA cargaba entera, pero abría con un error
rojo en consola. Se cambió un 404 por una violación de CSP.

La relajación es `data:` **sólo para imágenes**. Estas pruebas fijan las dos
mitades: que el favicon pase y que nada más se haya abierto de paso.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Anclado al fichero, no al cwd: pytest se lanza desde sitios distintos y una
# ruta relativa hacía fallar la prueba por dónde se invocaba, no por el código.
RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def client() -> TestClient:
    import apps.single_port_app as app_module

    return TestClient(app_module.app)


def directivas(csp: str) -> dict[str, list[str]]:
    salida: dict[str, list[str]] = {}
    for trozo in csp.split(";"):
        partes = trozo.split()
        if partes:
            salida[partes[0]] = partes[1:]
    return salida


def test_la_csp_permite_imagenes_data(client: TestClient) -> None:
    csp = directivas(client.get("/health/live").headers["Content-Security-Policy"])
    assert csp["img-src"] == ["'self'", "data:"]


def test_la_csp_no_afloja_nada_mas(client: TestClient) -> None:
    """`data:` en scripts o `unsafe-inline` convertirían esto en un agujero."""
    csp = client.get("/health/live").headers["Content-Security-Policy"]
    partes = directivas(csp)

    assert partes["default-src"] == ["'self'"]
    # Todo lo que no sea img-src cae en default-src: no debe haber más excepciones.
    assert set(partes) == {"default-src", "img-src"}
    for prohibido in ("'unsafe-inline'", "'unsafe-eval'", "*"):
        assert prohibido not in csp
    # `data:` sólo puede aparecer una vez, y es la de img-src.
    assert csp.count("data:") == 1


def test_las_cabeceras_de_seguridad_siguen_puestas(client: TestClient) -> None:
    cabeceras = client.get("/health/live").headers
    assert cabeceras["X-Content-Type-Options"] == "nosniff"
    assert cabeceras["X-Frame-Options"] == "DENY"
    assert cabeceras["Referrer-Policy"] == "no-referrer"


def test_el_favicon_del_html_es_el_unico_recurso_data(client: TestClient) -> None:
    """Si alguien añade otro `data:` que no sea imagen, la CSP lo bloqueará.

    Esta prueba lo detecta antes de que aparezca como error de consola en
    producción, que es como se descubrió el del favicon.
    """
    html = (RAIZ / "frontend/index.html").read_text(encoding="utf-8")
    esquemas = set(re.findall(r"data:([a-zA-Z0-9/+.-]+)", html))
    assert esquemas <= {"image/svg+xml"}, (
        f"recursos data: no permitidos por la CSP: {esquemas - {'image/svg+xml'}}"
    )
