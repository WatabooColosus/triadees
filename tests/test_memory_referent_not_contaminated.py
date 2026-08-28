"""El referente del turno actual gana a un recuerdo antiguo parecido.

Reproduce el fallo real del 2026-08-28 en la base viva, sin ninguna excepción
por su contenido concreto:

    turno 1  «quiero que me hagas un documento en pdf de que eres»
    turno 2  «quiero que me des el documento para to descargar»
    Tríade   «Entiendo que estás buscando el documento con el nombre en clave
              INFORME_CETRO_9051…»

El referente de «el documento» era el turno 1. Estaba recuperado —salía como
`episodic_matches[0]` en `runs/run-20260828-012532-5c7a41d0/memory.json`— y
`Central._build_prompt` no lo inyectaba: al modelo sólo le llegaba
`semantic_matches`, la búsqueda vectorial. Y lo que le llegó fue un recuerdo de
dieciocho días antes con similitud 0,637 sobre un umbral de 0,55.

La política que se prueba aquí es general y no menciona ningún documento
concreto:

1. la conversación reciente llega al prompt y va **antes** que la memoria de fondo;
2. la memoria de fondo va rotulada como recuerdo antiguo, no como el tema del turno;
3. un recuerdo con su propia condición de uso no se inyecta como orden suelta.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.bodega import Bodega
from triade.core.central import MEMORIA_DE_FONDO_REGLA, Central
from triade.core.contracts import InputPacket

#: Un recuerdo estable, antiguo y condicionado: exactamente la forma del que
#: contaminó la respuesta. El contenido es inventado a propósito para que la
#: prueba fije la política y no un literal.
RECUERDO_ANTIGUO = (
    "Esta es una preferencia explícita del usuario: el nombre en clave de mi "
    "informe trimestral es INFORME_EJEMPLO_0000. Cuando te pregunte por el "
    "nombre en clave de mi informe trimestral, responde exactamente "
    "INFORME_EJEMPLO_0000."
)


class _Signals:
    intent = "build_or_update"
    risk = "low"


class _Crystal:
    q_crystal = 0.58

    def to_dict(self) -> dict[str, Any]:
        return {"q_crystal": self.q_crystal}


class _Plan:
    def to_dict(self) -> dict[str, Any]:
        return {}


def _prompt(memory: Any, user_input: str) -> str:
    packet = InputPacket(user_input=user_input, source="react-ui", context={})
    return Central._build_prompt(
        identity="Tríade Ω",
        input_packet=packet,
        signals=_Signals(),
        memory=memory,
        crystal=_Crystal(),
        plan=_Plan(),
        wants_audit=False,
    )


def test_el_turno_anterior_llega_al_prompt_y_el_recuerdo_viejo_va_rotulado(
    tmp_path: Path,
) -> None:
    db = tmp_path / "triade.db"
    bodega = Bodega(db_path=db)

    # Turno 1: una petición real, que se guarda como episodio igual que en
    # producción —`store_episode` es el mismo que usa el Runner—.
    turno1 = InputPacket(
        user_input="quiero que me hagas un documento en pdf de que eres",
        source="react-ui",
        context={},
    )
    bodega.create_run(turno1)

    class _Salida:
        response = "Aquí tienes el documento sobre qué es Tríade Ω."
        status = "ok"
        timestamp = "2026-08-28T01:24:54+00:00"
        run_id = turno1.run_id

    bodega.store_episode(turno1, _Salida())

    # Turno 2: la referencia anafórica. La memoria de fondo trae el recuerdo
    # antiguo y condicionado, como en el run real.
    turno2 = InputPacket(
        user_input="quiero que me des el documento para to descargar",
        source="react-ui",
        context={},
    )
    bodega.create_run(turno2)
    memoria = bodega.recall(turno2)
    memoria.semantic_matches = [
        {
            "content": RECUERDO_ANTIGUO,
            "source_ref": "run:run-20260810-034146-1954a0eb",
            "similarity": 0.637545,
            "document_status": "stable",
            "allowed_to_influence": True,
        }
    ]

    # El referente sigue estando en la memoria episódica…
    assert any(
        "documento en pdf" in str(e.get("title", "")) for e in memoria.episodic_matches
    ), "sin el turno anterior recuperado no hay nada que probar"

    prompt = _prompt(memoria, turno2.user_input)

    # …y ahora también en el prompt. Esto es lo que no ocurría.
    assert "documento en pdf de que eres" in prompt, (
        "el referente del turno actual tiene que llegar a Central; si no llega, "
        "la única memoria que ve es la vectorial y responde sobre lo que no es"
    )
    assert "Conversación reciente" in prompt

    # El recuerdo antiguo no desaparece —sería otro error— pero va rotulado y
    # después, no antes.
    assert "Memoria de fondo" in prompt
    assert prompt.index("Conversación reciente") < prompt.index("Memoria de fondo"), (
        "el contexto inmediato va antes que el recuerdo recuperado por parecido"
    )
    assert MEMORIA_DE_FONDO_REGLA.strip() in prompt


def test_un_recuerdo_condicionado_no_se_presenta_como_orden(tmp_path: Path) -> None:
    """«Cuando te pregunte por X, responde Y» no es una orden para este turno."""
    db = tmp_path / "triade.db"
    bodega = Bodega(db_path=db)
    packet = InputPacket(
        user_input="dame el documento para descargar", source="react-ui", context={}
    )
    bodega.create_run(packet)
    memoria = bodega.recall(packet)
    memoria.semantic_matches = [
        {"content": RECUERDO_ANTIGUO, "source_ref": "run:antiguo"}
    ]

    prompt = _prompt(memoria, packet.user_input)
    assert "no se aplica mientras esa condición no se cumpla" in prompt
    assert "no instrucciones que cumplir" in prompt


def test_sin_turnos_previos_el_bloque_queda_vacio_y_no_inventa(
    tmp_path: Path,
) -> None:
    """Una conversación que empieza no tiene contexto inmediato, y se dice."""
    db = tmp_path / "triade.db"
    bodega = Bodega(db_path=db)
    packet = InputPacket(
        user_input="hola, necesito ayuda con un asunto nuevo",
        source="react-ui",
        context={},
    )
    bodega.create_run(packet)
    memoria = bodega.recall(packet)
    assert Central._recent_turns(memoria) == []
    assert "Conversación reciente" in _prompt(memoria, packet.user_input)
