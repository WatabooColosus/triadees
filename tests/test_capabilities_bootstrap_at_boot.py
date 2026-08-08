"""Las capacidades núcleo tienen que existir cuando el runtime arranca.

`bootstrap_core_capabilities` es idempotente y estaba escrito desde hacía
tiempo, pero sólo lo llamaban los tests. Consecuencia medida el 2026-08-08 sobre
la base viva: `capability_registry` y `capability_history` en cero,
`CapabilityMatrix` sin nada que leer —y por eso contado como módulo sin
importador— y `CapabilityPolicyGuard` resolviendo sobre un registro vacío.

Un arranque que declara capacidades y no las registra deja al sistema
respondiendo «no existe» sobre lo que sí tiene.
"""

from __future__ import annotations

import ast
from pathlib import Path

from triade.capabilities import CapabilityRegistry, bootstrap_core_capabilities

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_el_lifespan_arranca_las_capacidades_nucleo() -> None:
    """Si alguien lo quita, `capability_registry` vuelve a quedarse en cero."""
    fuente = (REPO_ROOT / "apps/single_port_app.py").read_text(encoding="utf-8")

    assert "bootstrap_core_capabilities()" in fuente, (
        "el lifespan dejó de arrancar las capacidades núcleo: el registro "
        "volvería a estar vacío y la matriz de capacidades sin nada que leer"
    )


def test_arrancarlo_dos_veces_no_duplica_ni_pisa(tmp_path: Path) -> None:
    """Es un arranque, no una migración: nunca reescribe lo ya registrado.

    Importa aquí más que en otros sitios: en este repositorio ya hubo rutinas de
    arranque que borraron lo aprendido.
    """
    db_path = tmp_path / "triade.db"

    primero = bootstrap_core_capabilities(db_path)
    registry = CapabilityRegistry(db_path)
    registry.set_state(primero[0]["capability_id"], primero[0]["version"], "deprecated")

    segundo = bootstrap_core_capabilities(db_path)

    assert len(segundo) == len(primero)
    estado = registry.get(primero[0]["capability_id"], primero[0]["version"])
    assert estado["state"] == "deprecated", (
        "el arranque pisó un estado que alguien había cambiado a propósito"
    )


def test_el_arranque_no_es_una_importacion_artificial() -> None:
    """La matriz se conecta cuando tiene datos, no importándola por importar."""
    arbol = ast.parse((REPO_ROOT / "apps/single_port_app.py").read_text("utf-8"))
    importados = {
        alias.name
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.ImportFrom)
        for alias in nodo.names
    }

    assert "CapabilityMatrix" not in importados, (
        "importar la matriz sólo para que deje de figurar como huérfana sería "
        "fabricar la conexión; se conecta cuando haya un consumidor real"
    )
