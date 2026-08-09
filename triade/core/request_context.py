"""Identidad de la petición HTTP, propagada a todo lo que cuelga de ella.

Hasta ahora Tríade sólo sabía correlacionar por `run_id`, que **nace dentro**
del Runner: si algo fallaba antes de llegar ahí —safety, autenticación, una
excepción en la ruta— no quedaba ningún hilo que uniera lo que vio el cliente
con lo que quedó escrito. Y al revés: quien tenía un `run_id` no podía volver a
la petición que lo originó.

El `request_id` cubre ese hueco. Entra por la cabecera `X-Request-ID` si el
cliente la manda —lo hacen los proxies y las suites de certificación— y si no,
se genera. Vive en un `ContextVar`, no en un argumento, porque atravesarlo por
las firmas de Runner → Central → Bodega significaría tocar decenas de llamadas
para un dato que sólo es trazabilidad.

Nota sobre hilos: FastAPI ejecuta los endpoints síncronos en un threadpool, y
`anyio.to_thread.run_sync` **copia el contexto**, así que lo que se fija en el
middleware se lee sin más dentro del endpoint.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

# El valor entra desde fuera y acaba en logs, en la base y en respuestas JSON.
# Se acota a lo que no puede romper ninguna de las tres: sin espacios, sin
# control chars, sin saltos de línea que partan una línea de log en dos.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("triade_request_id", default=None)


def new_request_id() -> str:
    """Genera un identificador propio cuando el cliente no trae uno usable."""
    return f"req-{uuid.uuid4().hex[:12]}"


def normalize_request_id(candidate: str | None) -> str:
    """Devuelve el id del cliente si es seguro; si no, uno nuevo.

    No se trunca ni se limpia un valor inválido: un id a medias se parece
    demasiado a uno bueno y acabaría correlacionando cosas distintas. Ante la
    duda, se genera uno y el del cliente se descarta.
    """
    if candidate and _SAFE_REQUEST_ID.match(candidate):
        return candidate
    return new_request_id()


def set_request_id(value: str | None):
    """Fija el id de la petición en curso. Devuelve el token para restaurarlo."""
    return _request_id.set(value)


def reset_request_id(token) -> None:
    """Restaura el valor anterior. Evita que un id se filtre a otra petición."""
    try:
        _request_id.reset(token)
    except (ValueError, RuntimeError):
        # El token pertenece a otro contexto: no hay nada que restaurar.
        _request_id.set(None)


def get_request_id() -> str | None:
    """El id de la petición en curso, o None fuera de una petición HTTP.

    Devuelve None a propósito en los ciclos de fondo —workers, metabolismo,
    always-on—: ahí no hay petición, e inventar un id sugeriría que la hubo.
    """
    return _request_id.get()
