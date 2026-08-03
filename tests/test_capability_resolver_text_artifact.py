"""`write_governed_text_artifact` sólo se activaba escribiendo su propio nombre.

La regla era `if "write_governed_text_artifact" in low`: había que teclear el
identificador interno dentro de la petición. Ningún humano pide nada así, y por
eso el tipo de tarea acumulaba cero ejecuciones teniendo handler, política de
concurrencia y clave de exclusión. La capacidad estaba muerta por construcción,
no por falta de código.

Lo que no puede pasar al abrirla: que se coma peticiones de modificación de
código, que tienen que seguir exigiendo aprobación humana.
"""

from __future__ import annotations

import pytest

from triade.core.capability_resolver import CapabilityResolver


@pytest.fixture
def resolver() -> CapabilityResolver:
    return CapabilityResolver()


@pytest.mark.parametrize(
    "peticion",
    [
        "escribe un documento con el resumen de la auditoría",
        "redacta un informe del estado de los workers",
        "genera un reporte con las conclusiones",
        "crea un acta de la sesión",
        "documenta el resultado en un artefacto",
    ],
)
def test_una_peticion_humana_normal_llega_a_la_capacidad(
    resolver: CapabilityResolver, peticion: str
) -> None:
    resolucion = resolver.resolve(peticion)
    assert resolucion.capability == "write_governed_text_artifact"
    assert resolucion.worker_task_type == "write_governed_text_artifact"
    assert resolucion.available is True
    assert resolucion.requires_human_approval is False


def test_el_identificador_literal_sigue_funcionando(
    resolver: CapabilityResolver,
) -> None:
    """Lo usan las pruebas end-to-end y el arranque manual."""
    resolucion = resolver.resolve("ejecuta write_governed_text_artifact")
    assert resolucion.worker_task_type == "write_governed_text_artifact"


@pytest.mark.parametrize(
    "peticion",
    [
        "corrige el archivo runner.py",
        "repara el módulo de workers",
        "crea una función nueva en el pipeline",
    ],
)
def test_modificar_codigo_sigue_exigiendo_aprobacion_humana(
    resolver: CapabilityResolver, peticion: str
) -> None:
    """La puerta que no se puede saltar: escribir texto no es tocar código."""
    resolucion = resolver.resolve(peticion)
    assert resolucion.capability != "write_governed_text_artifact"
    assert resolucion.requires_human_approval is True
    assert resolucion.worker_task_type is None


@pytest.mark.parametrize(
    ("peticion", "esperada"),
    [
        ("investiga la empresa Xiaos Medellin", "web_research"),
        ("instala el paquete numpy", "environment_install"),
        ("ejecuta la prueba", "test_suite"),
        ("compila el frontend", "project_build"),
        ("audita el repositorio", "diagnostic"),
    ],
)
def test_no_le_roba_peticiones_a_las_otras_capacidades(
    resolver: CapabilityResolver, peticion: str, esperada: str
) -> None:
    assert resolver.resolve(peticion).capability == esperada


@pytest.mark.parametrize(
    "peticion",
    ["escribe un resumen", "redacta una nota", "genera un texto"],
)
def test_lo_que_se_pide_en_chat_sigue_siendo_chat(
    resolver: CapabilityResolver, peticion: str
) -> None:
    """Contestar «escribe un resumen» con un fichero sorprendería.

    Por eso `resumen`, `nota` y `texto` quedan fuera de `ARTEFACTO_TEXTO`: la
    capacidad se abre para entregables pedidos como tales, no para cualquier
    petición de redacción.
    """
    assert resolver.resolve(peticion).capability == "conversation"


def test_una_frase_sin_orden_sigue_siendo_conversacion(
    resolver: CapabilityResolver,
) -> None:
    resolucion = resolver.resolve("el documento estaba muy bien redactado")
    assert resolucion.actionable is False
    assert resolucion.capability == "conversation"
