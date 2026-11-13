"""Las razones por las que se retiró `CapabilityMatrix`, hechas comprobables.

Retirar un módulo por «está duplicado» sólo vale mientras siga estándolo. Estas
pruebas no comprueban que el fichero no exista —eso lo dice `git`— sino que las
tres razones del veredicto se sostienen hoy:

1. el detector de ciclos buscaba algo que el registro **impide al escribir**;
2. el juicio sobre baseline y rollback de una capacidad crítica lo tiene el
   módulo que también aplica la regla constitucional;
3. el recuento por estado y dominio lo publica el observador del registro.

Si alguna deja de ser cierta, la retirada deja de estar justificada y hay que
volver a decidir. Veredicto completo en `docs/debt/CAPABILITY_MATRIX_VERDICT.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from triade.capabilities import (
    CapabilityDefinition,
    CapabilityObservability,
    CapabilityRegistry,
)

ROOT = Path(__file__).resolve().parents[1]


def _definicion(capability_id: str, **extra: object) -> CapabilityDefinition:
    contrato: dict[str, object] = {"type": "object"}
    return CapabilityDefinition(
        capability_id=capability_id,
        name=capability_id,
        domain="pruebas",
        version="1.0.0",
        owner="tests",
        component=f"triade.{capability_id}",
        state="active",
        input_contract=contrato,
        output_contract=contrato,
        **extra,  # type: ignore[arg-type]
    )


def test_el_registro_impide_los_ciclos_al_escribir(tmp_path: Path) -> None:
    """Por eso `_detect_cycles()` devolvía `[]` para siempre.

    Era la única parte de la matriz que ningún otro módulo hacía. Y buscaba una
    forma que no puede llegar a existir: `register()` la rechaza antes de
    guardarla. Un detector cuya respuesta está decidida de antemano es la misma
    figura que este repositorio persigue con `dead_status_value`.
    """
    registry = CapabilityRegistry(tmp_path / "triade.db")
    registry.register(_definicion("base"))
    registry.register(_definicion("media", dependencies=("base",)))

    with pytest.raises(ValueError, match="ciclo"):
        registry.register(_definicion("base_v2", dependencies=("media",)))
        registry.register(_definicion("base", dependencies=("media",)))


def test_una_critica_sin_rollback_no_llega_a_registrarse(tmp_path: Path) -> None:
    """Por eso `without_rollback` era el segundo contador imposible.

    La matriz contaba «capacidades críticas sin `rollback_policy`». El registro
    rechaza esa combinación al escribir, igual que los ciclos: el contador no
    podía pasar de cero por construcción, no por buena salud.
    """
    registry = CapabilityRegistry(tmp_path / "triade.db")

    with pytest.raises(ValueError, match="requiere suite y rollback"):
        registry.register(_definicion("critica_sin_nada", critical=True))


def test_el_juicio_sobre_el_baseline_tiene_duenio(tmp_path: Path) -> None:
    """`critical_without_baseline` ya se calcula aquí, y aquí sí sirve de algo.

    `MandatoryRollbackEnforcer` no sólo mide: **aplica** la regla —bloquea la
    promoción de una capacidad crítica sin baseline, Artículo III—. La matriz
    producía el mismo número sin poder hacer nada con él.
    """
    from triade.regression.mandatory_rollback import MandatoryRollbackEnforcer

    registry = CapabilityRegistry(tmp_path / "triade.db")
    registry.register(
        _definicion(
            "critica",
            critical=True,
            rollback_policy="critica-rollback",
            evaluation_suites=("critica-suite@1.0.0",),
        )
    )

    informe = MandatoryRollbackEnforcer(
        db_path=tmp_path / "triade.db"
    ).audit_all_critical()

    assert informe["total_critical"] == 1
    assert informe["non_compliant_count"] == 1, (
        "sin baseline estable, una capacidad crítica no puede promoverse: "
        "es el mismo hecho que contaba `critical_without_baseline`"
    )


def test_el_recuento_por_estado_y_dominio_tiene_duenio(tmp_path: Path) -> None:
    """La otra mitad de la salud de la matriz, en el observador del registro.

    Éste sí tiene consumidor vivo: `triade/core/observability_view.py`, que lo
    publica en la API.
    """
    registry = CapabilityRegistry(tmp_path / "triade.db")
    registry.register(
        _definicion(
            "una",
            critical=True,
            rollback_policy="una-rollback",
            evaluation_suites=("una-suite@1.0.0",),
        )
    )
    registry.register(_definicion("otra"))

    snapshot = CapabilityObservability(tmp_path / "triade.db").snapshot()

    assert snapshot["total"] == 2
    assert snapshot["critical"] == 1
    assert snapshot["by_state"] == {"active": 2}
    assert snapshot["by_domain"] == {"pruebas": 2}
    # Y con consumidor vivo, que es lo que la matriz nunca tuvo.
    assert "CapabilityObservability" in (
        ROOT / "triade/core/observability_view.py"
    ).read_text(encoding="utf-8")
