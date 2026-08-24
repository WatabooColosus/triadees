"""Una retirada escrita no excusa a cualquier tabla, sólo a la que retira.

`LEGACY_RETIRE` dice: la decisión de retirar está tomada,
la migración está en el repositorio, y lo que falta es un acto de operador que
el sistema exige a propósito. Es la clase que faltaba para `goals`, cuya
retirada (`036_retire_goals.sql`) está escrita desde antes de esta sesión y no
puede aplicarse sin rebasar el ancla de identidad.

El riesgo evidente de una clase así es que degenere en «hay un fichero de
migración por ahí, luego esta tabla está excusada». Por eso la evidencia
comprueba las dos mitades: que el fichero exista y que retire **esa** tabla.
"""

from __future__ import annotations

from pathlib import Path

from triade.observability.activation_contracts import (
    ContractVerifier,
    _contract,
    load_contracts,
)

ROOT = Path(__file__).resolve().parents[1]


def _verdict(evidencia: tuple[str, ...], subject: str = "table:goals"):
    contrato = _contract(
        subject,
        "LEGACY_RETIRE",
        decided_at="2026-08-12",
        reason="prueba",
        evidence=evidencia,
    )
    return ContractVerifier(ROOT).verify(contrato, structural_only=True)


def test_la_migracion_que_retira_esa_tabla_sostiene_el_contrato():
    verdict = _verdict(
        ("retirement_migration=triade/memory/migrations/036_retire_goals.sql",)
    )
    assert verdict.holds


def test_una_migracion_que_retira_otra_tabla_no_sirve_de_excusa():
    """Lo que impide que cualquier migración excuse a cualquier tabla."""
    verdict = _verdict(
        ("retirement_migration=triade/memory/migrations/036_retire_goals.sql",),
        subject="table:semantic_memory",
    )
    assert not verdict.holds
    assert verdict.failed
    # Y al caerse, el sujeto vuelve a la deuda real diciéndolo.
    assert verdict.to_dict()["classification"] == "REAL_BROKEN"


def test_una_migracion_que_no_existe_no_sostiene_nada():
    verdict = _verdict(
        ("retirement_migration=triade/memory/migrations/999_inventada.sql",)
    )
    assert not verdict.holds


def test_goals_esta_declarada_y_apunta_a_su_retirada_real():
    contrato = load_contracts()["table:goals"]
    assert contrato.classification == "LEGACY_RETIRE"
    kinds = {e.kind for e in contrato.evidence}
    # La retirada, y el gate humano que impide aplicarla sin firma.
    assert "retirement_migration" in kinds
    assert "human_gate" in kinds
