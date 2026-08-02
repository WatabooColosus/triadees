"""El saber verificado tiene que llegar al modelo por las dos ramas del prompt.

Auditoría 2026-08-02, P1-03. La conclusión anterior de esta misma auditoría era
que «el modelo de 3B ignora el bloque en el prompt de producción». **Era falsa.**

Medido con inferencia real sobre el prompt exacto de producción —mismo modelo,
mismo `system`, mismas opciones, mismos campos de contexto del run— el acierto
es 5/5. El bloque funciona perfectamente cuando llega.

Lo que ocurría es que no llegaba. `Central._build_prompt` tiene dos ramas:

* `wants_audit=False` → prompt conversacional, **con** `verified_knowledge_block`;
* `wants_audit=True`  → volcado JSON de diagnóstico, **sin** el bloque.

Y `_wants_internal_audit()` se dispara con la palabra «auditoría». La pregunta
con la que se probó el circuito —«¿Qué etiqueta debo poner al principio de los
informes de auditoría?»— contenía justo esa palabra, así que el saber recién
aprendido se quedaba fuera del prompt y el modelo improvisaba «AUDIT REPORT».

El agujero es real y más ancho que la prueba: cualquier conversación legítima
sobre auditoría, trazabilidad, cristal, hipotálamo o debug pierde el saber
verificado sin que nada lo diga.

Un saber que se recupera, se filtra y se registra como inyectado tiene que
aparecer en el prompt. Si no, la traza miente.
"""

from __future__ import annotations

from typing import Any

from triade.core.central import Central

BLOQUE = (
    "<triade_verified_knowledge>\n"
    "- [exp-test] Para los informes usa siempre la etiqueta AUDITORIA-OMEGA.\n"
    "</triade_verified_knowledge>"
)


class _Packet:
    def __init__(self, user_input: str, context: dict[str, Any]) -> None:
        self.user_input = user_input
        self.context = context
        self.run_id = "run-test"


class _Signals:
    intent = "build_or_update"
    risk = "low"

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "risk": self.risk}


class _Memory:
    semantic_matches: list[dict[str, Any]] = []


class _Vacio:
    def to_dict(self) -> dict[str, Any]:
        return {}


def _prompt(user_input: str, *, wants_audit: bool) -> str:
    packet = _Packet(user_input, {"verified_knowledge_block": BLOQUE})
    return Central._build_prompt(
        "Tríade Ω",
        packet,
        _Signals(),
        _Memory(),
        _Vacio(),
        _Vacio(),
        wants_audit,
    )


class TestElSaberLlegaPorLasDosRamas:
    def test_rama_conversacional(self) -> None:
        assert "AUDITORIA-OMEGA" in _prompt("que etiqueta uso", wants_audit=False)

    def test_rama_de_auditoria_interna(self) -> None:
        """La rama que se llevaba el saber por delante."""
        prompt = _prompt("audita el ultimo run", wants_audit=True)

        assert "AUDITORIA-OMEGA" in prompt, (
            "la rama de auditoría interna descarta el saber verificado: se "
            "recupera, se filtra, se registra como inyectado y nunca llega al "
            "modelo"
        )


class TestLaPalabraAuditoriaNoPierdeElSaber:
    """El disparador es una palabra corriente en conversación legítima."""

    def test_preguntar_por_auditoria_dispara_la_rama_json(self) -> None:
        # Se fija el comportamiento actual para que quede explícito de dónde
        # venía el agujero: no es un caso rebuscado.
        assert Central._wants_internal_audit(
            "Que etiqueta debo poner al principio de los informes de auditoria?"
        )

    def test_y_aun_asi_conserva_el_saber(self) -> None:
        prompt = _prompt(
            "Que etiqueta debo poner al principio de los informes de auditoria?",
            wants_audit=True,
        )
        assert "AUDITORIA-OMEGA" in prompt

    def test_sin_bloque_no_inventa_seccion(self) -> None:
        """No se añade ruido cuando no hay nada verificado que aportar."""
        packet = _Packet("audita el run", {})
        prompt = Central._build_prompt(
            "Tríade Ω", packet, _Signals(), _Memory(), _Vacio(), _Vacio(), True
        )
        assert "triade_verified_knowledge" not in prompt
