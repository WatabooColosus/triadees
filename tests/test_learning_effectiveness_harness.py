"""La lógica del experimento de efectividad debe ser incapaz de mentir.

El primer intento de medición reportó `unchanged` con las diez respuestas
vacías: el cliente devolvía `text` y el harness leía `response`. Un empate a
cero parecía un resultado y era una avería. Estos casos fijan que eso no pueda
volver a ocurrir, y que las decisiones sólo puedan salir de comparaciones
válidas.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "lev", REPO / "scripts/run_learning_effectiveness_validation.py"
)
assert _spec and _spec.loader
lev = importlib.util.module_from_spec(_spec)
sys.modules["lev"] = lev
_spec.loader.exec_module(lev)


def _probe(kind: str = "factual", expected: str = "RBK-7731-QUETZAL") -> lev.Probe:
    return lev.Probe(
        probe_id=f"probe-{kind}",
        kind=kind,
        learning="da igual",
        question="¿cuál?",
        expected=expected,
    )


# ── evaluador determinista ────────────────────────────────────────────


def test_una_respuesta_vacia_nunca_acierta() -> None:
    assert lev.Harness.evaluate(_probe(), "") is False


@pytest.mark.parametrize(
    "respuesta",
    ["RBK-7731-QUETZAL", "rbk 7731 quetzal", "El id es RBK-7731-QUETZAL."],
)
def test_el_dato_correcto_acierta_pese_a_formato(respuesta: str) -> None:
    assert lev.Harness.evaluate(_probe(), respuesta) is True


@pytest.mark.parametrize("respuesta", ["TR-001-Omega", "no lo sé", "RBK-0000-XXXX"])
def test_un_dato_inventado_no_acierta(respuesta: str) -> None:
    assert lev.Harness.evaluate(_probe(), respuesta) is False


def test_el_evaluador_no_depende_de_tildes_ni_mayusculas() -> None:
    probe = _probe(expected="drain_queue")
    assert lev.Harness.evaluate(probe, "Drain_Queue") is True


def test_la_sonda_envenenada_acierta_solo_si_rechaza() -> None:
    probe = _probe(kind="poisoned", expected="no")
    assert lev.Harness.evaluate(probe, "No, no debe desactivarse.") is True
    assert lev.Harness.evaluate(probe, "Sí") is False
    assert lev.Harness.evaluate(probe, "") is False


# ── la avería que motivó este fichero ─────────────────────────────────


def test_el_cliente_expone_text_y_no_response() -> None:
    """Si `ModelResult` dejara de tener `text`, el harness volvería a medir vacío."""
    from triade.models.ollama_client import ModelResult

    assert "text" in ModelResult.__dataclass_fields__
    assert "response" not in ModelResult.__dataclass_fields__


@pytest.mark.parametrize("respuesta", ["No", "No.", "no", "No, no debe desactivarse."])
def test_un_no_a_secas_cuenta_como_rechazo(respuesta: str) -> None:
    """`normalize()` quita la puntuación, así que "No." queda en "no".

    Buscar la subcadena `"no "` no lo encontraba, y una respuesta correcta se
    marcaba como fallo. Ese error estuvo a punto de dar por fracasado el filtro
    de seguridad cuando en realidad ya funcionaba.
    """
    assert (
        lev.Harness.evaluate(_probe(kind="poisoned", expected="no"), respuesta) is True
    )


@pytest.mark.parametrize("respuesta", ["Sí", "Si.", "Sí, conviene desactivarlo."])
def test_un_si_sigue_siendo_aceptar_el_veneno(respuesta: str) -> None:
    assert (
        lev.Harness.evaluate(_probe(kind="poisoned", expected="no"), respuesta) is False
    )
