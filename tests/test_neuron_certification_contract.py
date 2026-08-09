"""El juicio sobre una neurona `stable` tiene una sola autoridad viva.

Hubo dos. `NeuronCertifier` pedía un manifiesto firmado a mano en
`neuron_certifications`; nadie escribió jamás una fila, así que respondía
`certification_manifest_missing` para **cualquier** neurona `stable`, siempre.
No era un gate: era un `False` constante con pasos intermedios. Su único llamador
era el runner de la fase 12, `completed` desde el 2026-07-29.

`stable_neuron_audit` responde la misma pregunta con evidencia medida
—activaciones, diagnósticos, planes de prueba— y lo consumen cinco sitios vivos.

Estas pruebas fijan el resultado de esa elección: que el contrato retirado no
vuelva por la puerta de atrás, que su bitácora histórica sobreviva, y que el
contrato que quedó siga alcanzable. Contraste completo en
`docs/debt/NEURON_CERTIFICATION_CONTRACT.md`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODIGO_PRODUCTIVO = ("triade", "apps", "scripts")


def _ficheros_productivos() -> list[Path]:
    return [
        path
        for carpeta in CODIGO_PRODUCTIVO
        for path in sorted((ROOT / carpeta).rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


def test_el_contrato_retirado_no_tiene_lector_en_produccion() -> None:
    """Un lector sin ningún escritor posible siempre recibe el caso vacío.

    Es la forma exacta del `orphan_reader` que abrió este bloque. Si alguien
    vuelve a consultar la tabla, vuelve a introducir una consulta cuyo resultado
    está decidido de antemano.
    """
    culpables = [
        path.relative_to(ROOT).as_posix()
        for path in _ficheros_productivos()
        if "neuron_certifications" in path.read_text(encoding="utf-8")
        # El detector de deuda y su triaje nombran la tabla para explicar su
        # propia historia; eso es documentación, no una consulta.
        and "observability/alias_debt.py" not in path.as_posix()
        and "triage" not in path.name
    ]

    assert not culpables, (
        f"vuelve a haber código de producción que consulta `neuron_certifications`, "
        f"una tabla que nadie puede llenar: {culpables}"
    )


def test_la_bitacora_de_la_fase_12_sobrevive_a_su_escritor(tmp_path: Path) -> None:
    """Retirar el instrumento no puede llevarse el registro de lo que hizo.

    Las 13 cuarentenas del 2026-07-29 son un cambio real de estado del organismo,
    cada una con su `rollback_ref`. Su `CREATE` tuvo que mudarse a `schemas.sql`
    porque quien reejecutaba `028` era justo el módulo retirado.
    """
    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    conn.executescript((ROOT / "triade/memory/schemas.sql").read_text(encoding="utf-8"))
    for migracion in sorted(
        (ROOT / "triade/memory/migrations").glob("[0-9][0-9][0-9]_*.sql")
    ):
        conn.executescript(migracion.read_text(encoding="utf-8"))
    conn.commit()
    tablas = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    columnas = {
        row[1]
        for row in conn.execute("PRAGMA table_info(neuron_certification_transitions)")
    }
    conn.close()

    assert "neuron_certification_transitions" in tablas
    assert "rollback_ref" in columnas, "sin `rollback_ref` la bitácora no sirve de nada"
    assert "neuron_certifications" not in tablas


def test_el_contrato_que_quedo_sigue_alcanzable() -> None:
    """Si también se cayera éste, nadie juzgaría a las neuronas `stable`.

    Retirar una de dos autoridades sólo es correcto mientras la otra siga en pie.
    """
    api = (ROOT / "apps/routes/api.py").read_text(encoding="utf-8")

    assert "audit_stable_neurons" in api, (
        "la API dejó de exponer el único juicio vivo sobre neuronas `stable`"
    )
    assert (ROOT / "triade/core/stable_neuron_audit.py").is_file()
