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


@pytest.mark.parametrize(
    "pregunta",
    [
        # Las dos que dejaron goals esperando aprobación humana desde julio.
        "puedes crear imagenes?",
        "tu podrias descargar la forma optima de hacer las cosas",
        "¿puedes crear imagenes?",
        "sabes compilar el frontend?",
        "oye, puedes compilar el frontend",
        "hola me puedes investigar algo",
        "cómo investigo esto?",
        "es posible instalar numpy",
    ],
)
def test_una_pregunta_no_abre_un_expediente(
    resolver: CapabilityResolver, pregunta: str
) -> None:
    """Preguntar por una capacidad no puede crear un goal que nadie cierra.

    `"puedes crear imagenes?"` resolvía a `repo_modification` y dejó un goal en
    `awaiting_approval` desde el 2026-07-29; `"tu podrias descargar…"` hizo lo
    mismo con `environment_install` el 1-ago. Nadie los leía y nadie avisaba.
    """
    resolucion = resolver.resolve(pregunta)
    assert resolucion.actionable is False
    assert resolucion.capability == "conversation"
    assert resolucion.worker_task_type is None
    assert resolucion.requires_human_approval is False


# ── §13: un diagnóstico es un artefacto, no una modificación de código ──────


def test_crear_un_diagnostico_enruta_a_artefacto_gobernado():
    """Input literal de la batería del 2026-08-26.

    Contestaba «Modificar código requiere alcance, workspace candidato y
    aprobación humana» y abría un objetivo pendiente de aprobación. No se pedía
    tocar código: se pedía escribir un artefacto y guardarlo si existía ruta
    gobernada para ello.

    Dos causas: `diagnóstico` no figuraba entre los sustantivos de entregable, y
    después el verbo «crea» decidía `repo_modification` por sí solo.
    """
    resolucion = CapabilityResolver().resolve(
        "Crea un diagnóstico interno breve sobre el mayor fallo que detectes en "
        "tu propio funcionamiento y guarda el resultado únicamente si existe "
        "una ruta gobernada real para hacerlo"
    )
    assert resolucion.capability == "write_governed_text_artifact"


def test_modificar_codigo_de_verdad_sigue_pidiendo_aprobacion():
    """Estrechar la regla no puede abrir la puerta al código."""
    for peticion in (
        "Crea una función nueva en el módulo de workers",
        "Repara el bug del planificador",
        "Corrige el código del handler",
    ):
        resolucion = CapabilityResolver().resolve(peticion)
        assert resolucion.capability == "repo_modification", peticion
        assert resolucion.requires_human_approval is True, peticion


def test_un_verbo_de_creacion_sin_objeto_de_codigo_no_es_modificar_codigo():
    """Lo que deja de casar cae en `unsupported_action`, que sigue bloqueado.

    Estrechar `repo_modification` no concede permisos nuevos: reclasifica.
    """
    resolucion = CapabilityResolver().resolve("Crea un poema bonito")
    assert resolucion.capability == "unsupported_action"
    assert resolucion.available is False
