#!/usr/bin/env python3
"""Clasifica cada hallazgo del informe de deuda con su evidencia.

El informe dice *qué* está roto; esto dice *de qué clase* es cada rotura, que es
lo que decide si hay que arreglarla, documentarla o descartarla. Sin esa
separación un contador de 100 no es accionable: mezcla cortes reales con
subsistemas a medio conectar y con límites conocidos del análisis estático.

Las seis clases y la regla que las decide, todas comprobables:

`confirmed_break`
    Hay lector vivo, hay escritor alcanzable desde un entrypoint arrancado, y
    aun así el dato no llega. Es un corte y hay que arreglarlo.

`incomplete_subsystem`
    El código existe pero el circuito nunca se cerró: la tabla no está creada en
    la base viva, o su escritor no lo alcanza ningún entrypoint. No es un fallo
    de conexión, es una capacidad sin terminar.

`legacy_expected`
    Se compara a propósito algo que ya nadie debe escribir — típicamente una
    migración que retira un estado. La comparación es correcta.

`detector_false_positive`
    El análisis estático no puede ver la escritura: `SET status = ?` no dice qué
    valor manda. Se marca como tal **sólo** cuando se demuestra que existe una
    escritura parametrizada sobre esa columna en un módulo que lee ese estado.

`contracted_by_design`
    Tiene un contrato de activación cuya evidencia **se sostiene ahora mismo**:
    una bitácora de sólo escritura, una tabla histórica, una capacidad que
    espera un estímulo externo que no ha llegado. La decisión ya se tomó y está
    documentada; volver a contarla infla la deuda y empuja a «arreglarla»
    inventándole un lector, que no conecta nada y hace parecer que hubo consumo.
    Si la evidencia deja de sostenerse, el sujeto vuelve a las reglas de arriba.

`resolved`
    Corregido en esta fase, con prueba.

Ante la duda no se clasifica como falso positivo: se deja `confirmed_break` o
`incomplete_subsystem`, que es el lado que obliga a mirarlo.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.observability.activation_contracts import ContractVerifier, load_contracts
from triade.observability.alias_debt import build_alias_debt, profiles_from_artifact
from triade.observability.code_graph import build_module_index, reachable_modules
from triade.observability.introspection import build_debt_report

#: Escritura cuyo valor no es estáticamente visible.
_PARAM_WRITE = re.compile(
    r"\bSET\s+(status|state|decision|verdict)\s*=\s*\?", re.IGNORECASE
)
#: Migración: la misma sentencia escribe un estado y compara otro.
_MIGRATION = re.compile(
    r"\bSET\s+(?:status|state)\s*=\s*'[^']+'\s+WHERE\s+(?:status|state)\s*=\s*'([^']+)'",
    re.IGNORECASE,
)


def _live_tables(db: Path) -> set[str]:
    if not db.exists():
        return set()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {
            str(r[0])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


def _scan_sources(root: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Estados migrados y módulos con escritura parametrizada."""
    migrados: set[str] = set()
    parametrizados: dict[str, set[str]] = {}
    for path in root.rglob("*.py"):
        if any(p in {"__pycache__", ".git", "node_modules"} for p in path.parts):
            continue
        try:
            texto = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        relativo = path.relative_to(root).as_posix()
        migrados.update(_MIGRATION.findall(texto))
        if _PARAM_WRITE.search(texto):
            parametrizados.setdefault(relativo, set()).add("param_write")
    return migrados, parametrizados


def _readers_reachable(tabla: str, root: Path, alcanzables: set[str]) -> list[str]:
    """Ficheros que leen la tabla y que además alguien ejecuta."""
    patron = re.compile(
        rf"\bFROM\s+{re.escape(tabla)}\b|\bJOIN\s+{re.escape(tabla)}\b", re.IGNORECASE
    )
    vivos: list[str] = []
    for relativo in sorted(alcanzables):
        if not relativo.endswith(".py"):
            continue
        try:
            texto = (root / relativo).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if patron.search(texto):
            vivos.append(relativo)
    return vivos


def _classify_status(
    valor: str,
    ficheros: list[str],
    migrados: set[str],
    parametrizados: dict[str, set[str]],
    tablas_vivas: set[str],
    root: Path,
) -> tuple[str, str, str]:
    """(clasificación, severidad, evidencia) para un estado señalado."""
    if valor in migrados:
        return (
            "legacy_expected",
            "info",
            "comparado únicamente para migrarlo: hay un UPDATE que lo retira",
        )
    # ¿Algún fichero que lo compara escribe esa columna de forma parametrizada?
    con_param = [f for f in ficheros if f in parametrizados]
    if con_param:
        return (
            "detector_false_positive",
            "info",
            (
                f"escritura parametrizada (SET status = ?) en {con_param[0]}: "
                "el valor no es visible al análisis estático"
            ),
        )
    # ¿El módulo que lo compara opera sobre una tabla que no existe?
    for fichero in ficheros:
        try:
            texto = (root / fichero).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        referidas = set(
            re.findall(r"\bFROM\s+([a-z_][a-z0-9_]*)", texto, re.IGNORECASE)
        )
        if referidas and not (referidas & tablas_vivas):
            return (
                "incomplete_subsystem",
                "medium",
                (
                    f"{fichero} opera sobre tablas ausentes en la base viva: "
                    f"{sorted(referidas)[:3]}"
                ),
            )
    return (
        "confirmed_break",
        "high",
        "comparado en código productivo y sin escritor visible ni parametrizado",
    )


#: Veredictos de contrato que significan «esto ya se triró, con evidencia, y no
#: es trabajo pendiente». `REAL_BROKEN` queda fuera a propósito: hay un contrato
#: que dice exactamente eso de sí mismo, y excusarlo sería usar el sistema de
#: contratos para tapar lo único que declara no tener excusa.
CONTRACTED_NOT_PENDING = frozenset(
    {
        "ON_DEMAND",
        "EXPECTED_EMPTY",
        "FUTURE_DECLARED",
        "HUMAN_GATED",
        "LEGACY_RETIRE",
        "MANUAL_TOOL",
        "TEST_ONLY",
    }
)


def _contract_verdicts(
    root: Path,
    db: Path,
    tablas_vivas: set[str],
    perfiles: dict[str, dict[str, Any]],
    alcanzables: set[str],
) -> dict[str, Any]:
    """Veredicto de contrato por sujeto, **reverificado sobre la base viva**.

    El repositorio ya tenía dos sistemas para lo mismo y no se hablaban: los
    contratos de activación deciden y documentan por qué una tabla vacía o una
    tarea sin ejecutar es correcta, y este triaje los ignoraba y las volvía a
    contar como `incomplete_subsystem`. Medido el 2026-08-11: `hardware_senses`
    y `evidence_remediation_audit` figuraban como subsistema incompleto teniendo
    contratos verificables desde el 2026-08-08, con su evidencia.

    Contar dos veces una decisión ya tomada infla la deuda y, peor, empuja a
    «arreglarla» inventándole un lector a una bitácora. Un lector falso no
    conecta nada: hace parecer que hubo consumo.

    Lo que **no** hace esto es fiarse de la etiqueta. El contrato sólo excusa si
    su evidencia se sostiene ahora mismo: si un fichero declarado desaparece o
    una tabla que se decía vacía empieza a tener filas, el veredicto deja de
    sostenerse y el sujeto vuelve a la deuda con el resto de reglas.
    """
    contratos = load_contracts()
    if not contratos:
        return {}
    verificador = ContractVerifier(
        root,
        table_profiles={
            tabla: {"rows": (perfiles.get(tabla) or {}).get("rows", 0)}
            for tabla in tablas_vivas
        },
        db_path=db,
        reachable=alcanzables,
    )
    return {
        sujeto: verificador.verify(contrato) for sujeto, contrato in contratos.items()
    }


def triage(root: Path, db: Path, cache: Path) -> dict[str, Any]:
    root = root.resolve()
    index = build_module_index(root)
    alcanzables = reachable_modules(root, index)
    tablas_vivas = _live_tables(db)
    migrados, parametrizados = _scan_sources(root)

    # El informe y los perfiles deben salir de la misma fotografía. Antes el
    # parámetro ``cache`` se ignoraba aquí: el informe se leía del cache global
    # mientras ``perfiles`` se cargaba del directorio solicitado. Con un cache
    # nuevo eso convertía todos los escritores en cero y fabricaba cortes.
    informe = build_debt_report(root, db, cache_dir=cache, allow_build=True)
    perfiles = profiles_from_artifact(
        json.loads((cache / "table_graph.json").read_text(encoding="utf-8"))
        if (cache / "table_graph.json").exists()
        else None
    )
    alias = build_alias_debt(root, table_profiles=perfiles)
    por_muerto = {h["dead"]: h for h in alias["findings"]}
    veredictos = _contract_verdicts(root, db, tablas_vivas, perfiles, alcanzables)

    hallazgos: list[dict[str, Any]] = []
    contador = 0
    for categoria, entrada in sorted((informe.get("items") or {}).items()):
        for nombre in entrada.get("items") or entrada.get("sample", []):
            contador += 1
            detalle = por_muerto.get(nombre, {})
            evidencia_alias = detalle.get("evidence") or {}
            perfil = perfiles.get(nombre, {})

            prefijo = (
                "task_type" if categoria == "task_types_never_executed" else "table"
            )
            veredicto = veredictos.get(f"{prefijo}:{nombre}")

            if (
                veredicto is not None
                and veredicto.holds
                and veredicto.classification in CONTRACTED_NOT_PENDING
            ):
                # Decisión ya tomada, documentada y con su evidencia comprobada
                # en esta misma medición. No es trabajo pendiente.
                clase, sev = "contracted_by_design", "low"
                ev = f"contrato {veredicto.classification} vigente: {veredicto.reason}"
                fuente = ""
            elif categoria in {
                "alias_debt_dead_status_value",
                "alias_debt_suspected_dead_status",
            }:
                ficheros = evidencia_alias.get("compared_in") or []
                clase, sev, ev = _classify_status(
                    nombre, ficheros, migrados, parametrizados, tablas_vivas, root
                )
                fuente = ficheros[0] if ficheros else ""
            elif (
                nombre
                and nombre not in tablas_vivas
                and categoria.startswith(("alias_debt", "tables_"))
            ):
                clase, sev = "incomplete_subsystem", "medium"
                ev = "la tabla no existe en la base viva: circuito nunca cerrado"
                fuente = ""
            elif categoria in {
                "alias_debt_orphan_reader",
                "tables_with_writer_and_no_rows",
            }:
                escritores = int(perfil.get("writers") or 0)
                # Un lector sin escritor sólo es un corte si alguien lo ejecuta.
                # `neuron_certifications` tenía 1 lector y 0 escritores, y la
                # regla lo llamó corte confirmado: pero su lector,
                # `neuron_factory/certification.py`, no lo alcanza ningún
                # entrypoint arrancado. Nadie recibe nunca ese caso vacío, así
                # que es una capacidad sin terminar, no una rotura en marcha.
                lectores_vivos = _readers_reachable(nombre, root, alcanzables)
                if escritores == 0 and lectores_vivos:
                    clase, sev = "confirmed_break", "high"
                    ev = (
                        "hay lector alcanzable desde un entrypoint y ningún "
                        "escritor: siempre devuelve el caso vacío"
                    )
                elif escritores == 0:
                    clase, sev = "incomplete_subsystem", "medium"
                    ev = (
                        "sin escritor, y su lector no lo alcanza ningún "
                        "entrypoint arrancado: capacidad sin terminar"
                    )
                else:
                    clase, sev = "incomplete_subsystem", "medium"
                    ev = (
                        f"{escritores} escritor(es) declarados y 0 filas: la ruta de "
                        "escritura existe y no se ha ejecutado nunca"
                    )
                fuente = ""
            elif categoria == "entrypoints_without_launcher":
                clase, sev = "legacy_expected", "low"
                ev = "guard __main__ sin lanzador: utilidad manual, no ruta viva"
                fuente = nombre
            elif categoria == "modules_unreachable_from_entrypoint":
                # No es «nadie lo importa» —eso es la categoría de abajo y da
                # cero—: es que sus importadores tampoco los alcanza nada. Una
                # isla de módulos que se importan entre sí pasa los dos filtros
                # antiguos, y así se acumularon 35 sin aparecer en ningún
                # contador. Se clasifica como subsistema sin terminar porque es
                # exactamente eso: el código existe y el circuito nunca se
                # cerró. Convertirlo en falso positivo exigiría demostrar un
                # arranque que el grafo no ve, y esa prueba se aporta, no se
                # presume.
                clase, sev = "incomplete_subsystem", "medium"
                ev = (
                    "ningún entrypoint arrancado lo alcanza por imports: "
                    "existe, pero el sistema no lo conecta"
                )
                fuente = nombre
            elif categoria == "modules_without_importer":
                clase = (
                    "incomplete_subsystem"
                    if nombre not in alcanzables
                    else "detector_false_positive"
                )
                sev, ev = "medium", "sin importador en el repositorio"
                fuente = nombre
            else:
                clase, sev = "incomplete_subsystem", "medium"
                ev = entrada.get("evidence", "")
                fuente = nombre

            hallazgos.append(
                {
                    "id": f"D{contador:03d}",
                    "category": categoria,
                    "source_file": fuente,
                    "source_symbol": "",
                    "table_or_status": nombre,
                    "readers": perfil.get("readers", "UNKNOWN"),
                    "writers": perfil.get("writers", "UNKNOWN"),
                    "runtime_rows": perfil.get("rows", "UNKNOWN"),
                    "classification": clase,
                    "severity": sev,
                    "impact": detalle.get("detail", entrada.get("evidence", "")),
                    "evidence": ev,
                    "recommended_action": "",
                    "resolution_status": "open",
                    "tests": [],
                }
            )

    resumen: dict[str, int] = {}
    for h in hallazgos:
        resumen[h["classification"]] = resumen.get(h["classification"], 0) + 1
    graph_index: dict[str, Any] = {}
    try:
        graph_index = json.loads((cache / "index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_sha": graph_index.get("commit_sha") or "",
        "graph_generation_id": graph_index.get("generation_id"),
        "graphs_generated_at": graph_index.get("generated_at"),
        "graph_database": graph_index.get("database"),
        "graph_cache": str(cache.resolve()),
        "debt_items_total": informe.get("debt_items_total"),
        "findings_classified": len(hallazgos),
        "by_classification": resumen,
        "by_category": {k: v["count"] for k, v in (informe.get("items") or {}).items()},
        "findings": hallazgos,
        "simulated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--db", default="triade/memory/triade.db")
    parser.add_argument("--cache", default="artifacts/internal_graphs")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    informe = triage(Path(args.root), Path(args.db), Path(args.cache))
    salida = Path(
        args.output or f"artifacts/debt/debt-triage-{datetime.now(UTC):%Y%m%d}.json"
    )
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps(informe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(informe["by_classification"], indent=2, ensure_ascii=False))
    print(f"clasificados: {informe['findings_classified']} -> {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
