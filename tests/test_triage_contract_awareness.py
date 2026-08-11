"""El triaje de deuda contaba dos veces decisiones ya tomadas.

El repositorio tenía dos sistemas para lo mismo y no se hablaban:

- los **contratos de activación** deciden y documentan, con evidencia, por qué
  una tabla vacía o una tarea sin ejecutar es correcta (`AUDIT_LEDGER`,
  `HISTORICAL`, `NO_EXTERNAL_STIMULUS`, `HUMAN_GATED`…);
- `scripts/triage_debt.py` los ignoraba y volvía a etiquetar esos mismos
  sujetos como `incomplete_subsystem`.

Medido el 2026-08-11: `hardware_senses` y `evidence_remediation_audit` figuraban
como subsistema incompleto teniendo contrato desde el 2026-08-08. De 34
hallazgos, 11 eran decisiones ya documentadas.

Contar dos veces no sólo infla la cifra: empuja a «arreglarla» inventándole un
lector a una bitácora de sólo escritura. Un lector falso no conecta nada — hace
parecer que hubo consumo, que es peor que la tabla huérfana.

Lo que se comprueba aquí es que el contrato **no sella**: excusa sólo mientras su
evidencia se sostenga, y `DEUDA_REAL` no excusa nunca.
"""

from __future__ import annotations

from scripts.triage_debt import CONTRACTED_NOT_PENDING


def test_deuda_real_nunca_excusa() -> None:
    """Hay un contrato que declara ser deuda de verdad. No puede taparse solo.

    Sería el agujero evidente: usar el sistema de contratos para excusar lo
    único que dice de sí mismo que no tiene excusa.
    """
    assert "DEUDA_REAL" not in CONTRACTED_NOT_PENDING


def test_las_clases_excusables_son_las_esperadas() -> None:
    """La lista es cerrada a propósito: una clase nueva no excusa por defecto.

    Si mañana alguien añade una clasificación al catálogo de contratos, entra
    como deuda hasta que se decida explícitamente que no lo es.
    """
    assert CONTRACTED_NOT_PENDING == {
        "AUDIT_LEDGER",
        "HISTORICAL",
        "ON_DEMAND",
        "NO_EXTERNAL_STIMULUS",
        "EXPECTED_EMPTY",
        "EXPERIMENTAL",
        "HUMAN_GATED",
    }


def test_una_clase_desconocida_no_excusa() -> None:
    assert "INVENTADA" not in CONTRACTED_NOT_PENDING
    assert "" not in CONTRACTED_NOT_PENDING


def test_los_contratos_del_catalogo_declaran_evidencia() -> None:
    """Sin evidencia, un contrato sería una etiqueta que se cree a sí misma.

    Es la condición que hace que reverificar signifique algo: el veredicto se
    calcula comprobando estas evidencias contra el repositorio y la base viva,
    así que un contrato sin ninguna pasaría siempre.
    """
    from triade.observability.activation_contracts import load_contracts

    contratos = load_contracts()
    assert contratos, "el catálogo de contratos no debería estar vacío"
    sin_evidencia = [
        sujeto for sujeto, contrato in contratos.items() if not contrato.evidence
    ]
    assert sin_evidencia == []
