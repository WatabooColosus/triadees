"""§7 — el readiness llega a la respuesta, o el modelo contesta a ciegas.

Medido en la batería del 2026-08-26: la UI mostraba `diagnosis_count 0 < 5` y
`test_plan_count 0 < 3`, y al preguntar «¿Qué le falta exactamente para pasar de
candidata a funcional?» la respuesta no usaba ese dato.

No estaba mal calculado. **No llegaba**: `readiness` no aparecía ni en
`runner.py` ni en `bodega_global_context.py`, así que el contexto que el modelo
tenía delante no lo contenía.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from triade.core.bodega_global_context import (
    _asks_about_neuron_readiness,
    build_bodega_global_context,
)

RAIZ = Path(__file__).resolve().parents[1]
BASE_VIVA = RAIZ / "triade" / "memory" / "triade.db"


@pytest.mark.parametrize(
    "pregunta",
    [
        "¿Qué le falta a una neurona para pasar a funcional?",
        "¿Qué evidencia exigirías antes de promover la neurona candidata?",
        "¿Cuál es el readiness de las neuronas?",
    ],
)
def test_una_pregunta_de_readiness_lo_pide(pregunta):
    assert _asks_about_neuron_readiness(pregunta)


@pytest.mark.parametrize(
    "pregunta",
    ["¿Cuál es la capital de Francia?", "hola qué tal", "resume el último informe"],
)
def test_una_pregunta_cualquiera_no_lo_pide(pregunta):
    """No es un filtro de temas: es un freno de coste.

    `evaluate_stable_readiness()` midió 0,69 s de CPU. Calcularlo en cada run
    repetiría el error de `pulse_check`, que se llevó 458 de los 600 minutos
    diarios de presupuesto y metió el organismo en `observe_only`.
    """
    assert not _asks_about_neuron_readiness(pregunta)


def test_el_contexto_no_calcula_readiness_si_nadie_pregunta():
    contexto = build_bodega_global_context(
        "hola qué tal", db_path=BASE_VIVA, semantic_recall_enabled=False
    )
    assert contexto["neuron_readiness"]["status"] == "not_requested"


@pytest.mark.skipif(not BASE_VIVA.is_file(), reason="sin base viva")
def test_el_readiness_llega_al_contexto_con_sus_bloqueadores():
    """El puente entero: pregunta -> readiness -> contexto del modelo."""
    contexto = build_bodega_global_context(
        "¿Qué le falta a la neurona candidata para pasar a funcional?",
        db_path=BASE_VIVA,
        semantic_recall_enabled=False,
    )
    readiness = contexto["neuron_readiness"]
    assert readiness["status"] == "ok"
    assert readiness["not_ready_count"] >= 0
    assert "thresholds" in readiness.get("summary", {})

    for fila in readiness["not_ready"]:
        # Sin nombre no se puede responder «a ESTA neurona le falta X».
        assert fila["name"]
        assert fila["neuron_id"] is not None
        # Los bloqueadores se pasan literales: reformularlos aquí sería
        # reinterpretar la evidencia antes de que el modelo la vea.
        assert isinstance(fila["blockers"], list)


@pytest.mark.skipif(not BASE_VIVA.is_file(), reason="sin base viva")
def test_la_lista_va_acotada():
    """35 neuronas en el prompt son ruido, no contexto."""
    contexto = build_bodega_global_context(
        "¿qué le falta a cada neurona?",
        db_path=BASE_VIVA,
        semantic_recall_enabled=False,
    )
    assert len(contexto["neuron_readiness"]["not_ready"]) <= 5


@pytest.mark.skipif(not BASE_VIVA.is_file(), reason="sin base viva")
def test_el_readiness_entra_en_el_payload_que_recibe_el_modelo():
    """El tramo final del puente, y el que faltaba.

    La primera versión wireó el readiness sólo en `_chain_of_thought_rules`,
    que es la **rama de respaldo**: con Ollama disponible los pasos los genera
    el modelo y esa rama no se ejecuta nunca. El puente quedaba construido y
    sin tránsito, igual que antes.

    Esto comprueba lo que sí es verificable sin depender de la calidad del
    modelo: que el dato llega a su prompt.
    """
    import types

    from triade.core.central import Central

    contexto = build_bodega_global_context(
        "¿Qué le falta a una neurona candidata para pasar a funcional?",
        db_path=BASE_VIVA,
        semantic_recall_enabled=False,
    )
    paquete = types.SimpleNamespace(
        user_input="x", context={"bodega_global_context": contexto}
    )
    readiness = Central._neuron_readiness_of(paquete)

    assert readiness is not None
    assert readiness["thresholds"]
    assert len(readiness["not_ready"]) <= 3
    for fila in readiness["not_ready"]:
        assert fila["name"]
        assert fila["blockers"]


@pytest.mark.skipif(not BASE_VIVA.is_file(), reason="sin base viva")
def test_sin_pregunta_relevante_no_se_infla_el_prompt():
    import types

    from triade.core.central import Central

    contexto = build_bodega_global_context(
        "hola", db_path=BASE_VIVA, semantic_recall_enabled=False
    )
    paquete = types.SimpleNamespace(
        user_input="x", context={"bodega_global_context": contexto}
    )
    assert Central._neuron_readiness_of(paquete) is None
