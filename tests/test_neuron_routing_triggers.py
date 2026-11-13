"""El routing debe mirar lo que la neurona declara, no cómo se llama.

Hallazgo de la auditoría (2026-07-31), con datos:

| Neurona | Runs | Activaciones reales |
|---|---|---|
| `neurona-llamo-santiago-wataboo-creador` | 43 | **43** |
| Neurona Visual | 35 | **0** |
| Neurona de Código y Reparación | 35 | **0** |

Las dos neuronas construidas para un oficio nunca reciben tráfico real: solo
pulsos sintéticos. Y por eso no pueden alcanzar `stable`, que exige al menos una
activación no sintética.

La causa estaba en `should_activate`:

1. Una cadena `if/elif` con **cuatro dominios escritos a mano**
   (`federation_android_edge`, `system_governance`, `model_runtime`,
   `memory_governance`). Los dominios reales de esas dos neuronas —
   `vision_image_understanding` y `code_repair_build_tests`— no estaban, así que
   no podían coincidir jamás.
2. Un fallback que activa la neurona si **un trozo de su nombre** aparece en el
   texto. Por eso ganaba `neurona-llamo-santiago-wataboo-creador`: su nombre está
   hecho de palabras de conversación. `Neurona Visual` necesitaría que alguien
   escribiera literalmente "neurona visual".

El routing premiaba a las neuronas bautizadas con fragmentos de chat y mataba de
hambre a las construidas para trabajar.

La tabla `neurons` ya tiene una columna `triggers`, y 11 de 13 neuronas la
rellenan. Nadie la leía.
"""

from __future__ import annotations

from typing import Any

from triade.core.experimental_neuron_runtime import should_activate


class _Signals:
    intent = ""


def _neuron(**kwargs: Any) -> dict[str, Any]:
    base = {"name": "Neurona Visual", "domain": "vision_image_understanding"}
    base.update(kwargs)
    return base


def _activate(neuron: dict[str, Any], text: str) -> dict[str, Any]:
    return should_activate(
        neuron,
        user_input=text,
        context={},
        signals=_Signals(),
        edge_usage={},
    )


# ── el defecto que se corrige ───────────────────────────────────────────


def test_a_declared_trigger_activates_the_neuron() -> None:
    """Lo que la neurona declara saber hacer debe poder activarla."""
    neuron = _neuron(triggers='["dibujar", "imagen", "visual"]')
    assert _activate(neuron, "¿Cómo se aprende a dibujar?")["active"]


def test_triggers_work_for_the_code_neuron_too() -> None:
    neuron = _neuron(
        name="Neurona de Código y Reparación",
        domain="code_repair_build_tests",
        triggers='["test", "error", "reparar", "deadlock"]',
    )
    assert _activate(neuron, "hay un deadlock en el worker")["active"]


def test_triggers_accept_a_list_not_only_json() -> None:
    """El registro devuelve a veces la lista ya decodificada."""
    neuron = _neuron(triggers=["dibujar", "imagen"])
    assert _activate(neuron, "quiero aprender a dibujar en madera")["active"]


def test_an_unrelated_question_does_not_activate_it() -> None:
    """Enrutar de más es tan malo como no enrutar: gasta modelo y ensucia evidencia."""
    neuron = _neuron(triggers='["dibujar", "imagen", "visual"]')
    assert not _activate(neuron, "cuánto cuesta el pan")["active"]


def test_generic_triggers_do_not_activate_everything() -> None:
    """`every_session` y `relevant_context` no son palabras del usuario.

    Once de trece neuronas las declaran. Si se tratasen como texto a buscar,
    activarían siempre o nunca, y en ambos casos la evidencia dejaría de
    significar algo.
    """
    neuron = _neuron(triggers='["every_session", "relevant_context"]')
    assert not _activate(neuron, "cualquier cosa que escriba el usuario")["active"]


def test_the_reason_says_it_matched_a_trigger() -> None:
    """Una activación sin motivo auditable no sirve como evidencia."""
    neuron = _neuron(triggers='["dibujar"]')
    result = _activate(neuron, "enséñame a dibujar")
    assert any("trigger" in r for r in result["reasons"])


# ── lo que NO debe romperse ─────────────────────────────────────────────


def test_the_hardcoded_domains_keep_working() -> None:
    neuron = {"name": "gobernanza", "domain": "system_governance", "triggers": "[]"}
    assert _activate(neuron, "audita el estado del sistema")["active"]


def test_a_neuron_without_triggers_still_falls_back_to_its_name() -> None:
    """No se retira el fallback: se le añade una vía mejor.

    Quitarlo dejaría sin activarse a las neuronas que hoy sí funcionan por
    nombre, y eso sería cambiar un sesgo por otro.
    """
    neuron = {"name": "neurona-santiago-creador", "domain": "otro", "triggers": "[]"}
    assert _activate(neuron, "quién es santiago")["active"]


def test_malformed_triggers_do_not_crash_the_run() -> None:
    """Un contrato roto no puede tumbar el ciclo cognitivo entero."""
    for bad in ("{no es json", None, 42, '{"no": "una lista"}'):
        assert isinstance(_activate(_neuron(triggers=bad), "hola")["active"], bool)
