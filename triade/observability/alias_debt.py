"""Detecta la deuda de alias: lectores que apuntan al gemelo muerto.

Todos los cortes encontrados en la auditoría del 2026-08-03 tenían la misma
forma. No era código ausente ni rutas sin ejecutar: era **un lector apuntando al
hermano muerto de la cosa que sí se escribe**.

    salience.py            lee `goals` (0 filas)      se escribe `planning_graph` (28)
    mission_planner        pedía `validated_in_runs`  se escribe `evidence_verified`
    hipotálamo             contaba `worker_tasks`     se escribe `autonomous_tasks`
    condición de gobernanza contaba `semantic_memory`  se escribe `semantic_documents`
    `_plan_memory_consolidation` encola `stable_consolidation_review`, no
    `memory_consolidation_review` — dos nombres cercanos, uno muerto

Cada uno costó una auditoría manual para salir. Encontrarlos a mano no escala:
mientras no se detecten solos, el sistema seguirá pareciendo conectado por
tener las dos mitades escritas, y no lo estará.

Tres señales, porque los alias no siempre se parecen en el nombre
----------------------------------------------------------------
1. `orphan_readers` — alguien lee una tabla que nadie llena. No necesita
   parecido léxico ninguno, y es la que caza `goals`.
2. `lexical_aliases` — dos nombres casi iguales con vitalidad opuesta. Caza
   `memory_consolidation_review` frente a `stable_consolidation_review`.
3. `dead_status_values` — un valor que el código compara en un `WHERE` y que
   nadie escribe nunca. Caza `validated_in_runs`, que fue el corte terminal del
   aprendizaje.

Todo sale de la misma evidencia que el resto de grafos: el AST del repositorio y
SQLite en solo lectura. Nada se escribe y nada se supone: cuando una tabla no
puede comprobarse, no se acusa.

Lo que este detector NO ve, y por qué importa saberlo
-----------------------------------------------------
Un informe con falsos positivos deja de leerse, y entonces la deuda de alias
vuelve a buscarse como antes: a mano. Estas son las tres categorías conocidas en
`dead_status_value`, comprobadas sobre el repositorio real el 2026-08-03:

1. **Escrituras parametrizadas.** `SET status = ?` no dice qué valor escribe.
   `longitudinal.py` escribe así, y por eso sus estados aparecen como muertos.
2. **Código de migración.** `UPDATE … SET status='internally_checked' WHERE
   status='verified'` compara un valor legado a propósito, para retirarlo. Es
   una comparación legítima de algo que nadie debe escribir ya.
3. **Módulos cuya tabla no existe en la base viva.** `longitudinal_memories` no
   está creada: sus estados no son alias, son un subsistema entero que nunca ha
   tocado producción — otra deuda, pero de otra clase.

Las tres se reconocen mirando el fichero señalado. Ninguna invalida la señal:
`validated_in_runs` salió de aquí, y era el corte terminal del aprendizaje.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .code_graph import ModuleIndex, build_module_index, iter_python_files
from .runtime_graph import build_table_graph

#: Dos nombres se consideran parientes cuando comparten esta fracción de sus
#: piezas. `stable_consolidation_review` y `memory_consolidation_review`
#: comparten 2 de 3; `goals` y `planning_graph` no comparten nada, y por eso
#: hace falta la señal de lector huérfano además de ésta.
SIMILARITY_THRESHOLD = 0.5

#: Listón más bajo para *sugerir* con quién se confunde una tabla que ya se
#: acusó por su forma. El hallazgo se sostiene solo —cero filas y lectores—, así
#: que la pista puede ser más generosa sin inventar deuda: `semantic_memory` y
#: `semantic_documents` puntúan 0.43 y son el caso real que hay que señalar.
HINT_THRESHOLD = 0.35

#: Columnas cuyo valor es un estado gobernado. Son las que producen el fallo de
#: «consulto un estado que ya nadie escribe»; comparar cualquier columna daría
#: ruido sin fin.
STATUS_COLUMNS = ("status", "state", "decision", "verdict")

_QUOTED = r"'([a-z][a-z0-9_]{2,})'"
#: `WHERE status = 'x'`, `AND status='x'`, `status IN ('x','y')`.
_COMPARED = re.compile(
    rf"\b({'|'.join(STATUS_COLUMNS)})\s*(?:=|==)\s*{_QUOTED}", re.IGNORECASE
)
_COMPARED_IN = re.compile(
    rf"\b({'|'.join(STATUS_COLUMNS)})\s+IN\s*\(([^)]*)\)", re.IGNORECASE
)
#: `SET status = 'x'` en SQL escribe.
_ASSIGNED_SQL = re.compile(
    rf"\bSET\s+({'|'.join(STATUS_COLUMNS)})\s*=\s*{_QUOTED}", re.IGNORECASE
)
#: `status="x"` en Python escribe. **Sólo comillas dobles**, y no es un detalle
#: de estilo: `WHERE status = 'x'` dentro de una cadena SQL es idéntico a un
#: kwarg de Python para una regex. Contarlo como escritura hacía que todo valor
#: comparado apareciera también como escrito, y la señal no encontraba nada
#: nunca. El SQL de este repositorio usa comilla simple dentro de cadenas con
#: comilla doble, así que la separación es limpia y comprobable.
_ASSIGNED_PY = re.compile(
    rf"\b({'|'.join(STATUS_COLUMNS)})\s*=\s*\"([a-z][a-z0-9_]{{2,}})\""
)
#: `return "candidate_reviewable"` también escribe un estado: quien llama guarda
#: lo devuelto. Sin esto el detector acusaba a `candidate_reviewable`, que
#: `neuron_formation_pipeline.py` produce en dos returns — un falso positivo, y
#: los falsos positivos son lo único que puede matar a este detector: un informe
#: en el que hay que descartar a mano deja de leerse.
_RETURNED_PY = re.compile(r"\breturn\s+\"([a-z][a-z0-9_]{2,})\"")
_LITERAL_IN_LIST = re.compile(_QUOTED)


@dataclass(frozen=True)
class AliasFinding:
    """Un alias con su evidencia, listo para abrir o descartar."""

    signal: str
    kind: str
    dead: str
    live: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pieces(name: str) -> set[str]:
    return {p for p in re.split(r"[_\-.:]", name.lower()) if p}


def piece_weights(names: Iterable[str]) -> dict[str, float]:
    """Peso de cada pieza por lo rara que es en el conjunto de nombres.

    Sin esto, `neuron_certifications` salía emparejada con las ocho tablas
    `neuron_*` del esquema: compartir el espacio de nombres daba 50 % automático
    en cualquier nombre de dos piezas. Un prefijo que llevan veinte tablas no
    dice nada sobre si dos son la misma cosa; lo que lo dice es compartir la
    pieza que casi nadie más usa.
    """
    total: dict[str, int] = {}
    cuantos = 0
    for nombre in names:
        cuantos += 1
        for pieza in _pieces(nombre):
            total[pieza] = total.get(pieza, 0) + 1
    if not cuantos:
        return {}
    return {
        pieza: math.log(cuantos / veces) / math.log(cuantos)
        for pieza, veces in total.items()
        if veces
    }


def similarity(left: str, right: str, weights: dict[str, float] | None = None) -> float:
    """Parecido entre dos nombres, ponderado por la rareza de lo que comparten."""
    a, b = _pieces(left), _pieces(right)
    if not a or not b:
        return 0.0
    if weights is None:
        return len(a & b) / max(len(a), len(b))
    peso_comun = sum(weights.get(p, 1.0) for p in a & b)
    peso_total = max(
        sum(weights.get(p, 1.0) for p in a), sum(weights.get(p, 1.0) for p in b)
    )
    return peso_comun / peso_total if peso_total else 0.0


def _table_profiles(
    root: Path, index: ModuleIndex | None, db_path: Path | None
) -> dict[str, dict[str, Any]]:
    nodes, _edges = build_table_graph(root, index, db_path)
    return {
        node.label: dict(node.metadata)
        for node in nodes
        if node.node_id.startswith("table:")
    }


def find_orphan_readers(perfiles: dict[str, dict[str, Any]]) -> list[AliasFinding]:
    """Tablas que alguien lee y nadie llena.

    Es la señal más general y la única que no depende del nombre: `goals` y
    `planning_graph` no se parecen en nada, y aun así una está viva y la otra
    sólo se lee. Un lector sobre una tabla vacía y sin escritores no devuelve
    nada nunca, y no falla: devuelve el caso vacío, que es peor porque parece
    una respuesta.
    """
    hallazgos: list[AliasFinding] = []
    pesos = piece_weights(perfiles)
    for tabla, perfil in sorted(perfiles.items()):
        filas = perfil.get("rows")
        if not isinstance(filas, int) or filas != 0:
            continue
        lectores = int(perfil.get("readers") or 0)
        escritores = int(perfil.get("writers") or 0)
        if lectores < 1:
            continue
        # Con quién se está confundiendo, si es que hay candidata: la tabla viva
        # más parecida. Puede no haberla, y el hallazgo sigue siendo válido.
        pariente = max(
            (
                (otra, similarity(tabla, otra, pesos))
                for otra, p in perfiles.items()
                if otra != tabla and isinstance(p.get("rows"), int) and p["rows"] > 0
            ),
            key=lambda par: par[1],
            default=("", 0.0),
        )
        # Que además tenga escritores no la salva: la empeora. Significa que la
        # ruta de escritura está escrita y no se ejecuta nunca, así que el
        # sistema aparenta tener el circuito completo. `semantic_memory` llegó a
        # tener 10 lectores y 3 escritores con cero filas mientras la ingesta
        # real iba a `semantic_documents`.
        causa = (
            "el escritor existe y no se ejecuta nunca"
            if escritores
            else "no la llena nadie"
        )
        hallazgos.append(
            AliasFinding(
                signal="orphan_reader",
                kind="table",
                dead=tabla,
                live=pariente[0] if pariente[1] >= HINT_THRESHOLD else "",
                detail=(
                    f"`{tabla}` tiene {lectores} lector(es), {escritores} "
                    f"escritor(es) y 0 filas: {causa}, y quien la consulta recibe "
                    "siempre el caso vacío"
                ),
                evidence={
                    "readers": lectores,
                    "writers": escritores,
                    "rows": filas,
                    "closest_live_table": pariente[0],
                    "similarity": round(pariente[1], 2),
                },
            )
        )
    return hallazgos


def find_lexical_aliases(perfiles: dict[str, dict[str, Any]]) -> list[AliasFinding]:
    """Pares de nombres casi iguales donde uno vive y el otro no."""
    pesos = piece_weights(perfiles)
    # Una tabla muerta sólo se confunde con **una** viva. Emitir los ocho pares
    # posibles convertía un hallazgo en ocho líneas de la misma cosa, y un
    # informe que repite ahoga al que lo lee.
    mejor: dict[str, tuple[str, float]] = {}
    for muerta, perfil in perfiles.items():
        if perfil.get("rows") != 0:
            continue
        for viva, otro in perfiles.items():
            if viva == muerta or not isinstance(otro.get("rows"), int):
                continue
            if otro["rows"] <= 0:
                continue
            grado = similarity(muerta, viva, pesos)
            if (
                grado >= SIMILARITY_THRESHOLD
                and grado > mejor.get(muerta, ("", 0.0))[1]
            ):
                mejor[muerta] = (viva, grado)

    hallazgos: list[AliasFinding] = []
    for muerta, (viva, grado) in sorted(mejor.items()):
        hallazgos.append(
            AliasFinding(
                signal="lexical_alias",
                kind="table",
                dead=muerta,
                live=viva,
                detail=(
                    f"`{muerta}` y `{viva}` comparten {grado:.0%} de nombre "
                    f"distintivo; `{viva}` tiene filas y `{muerta}` está vacía"
                ),
                evidence={
                    "similarity": round(grado, 2),
                    "dead_rows": 0,
                    "live_rows": perfiles[viva].get("rows"),
                    "dead_readers": perfiles[muerta].get("readers"),
                    "dead_writers": perfiles[muerta].get("writers"),
                },
            )
        )
    return hallazgos


def _status_literals(root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Valores de estado comparados y escritos, con el fichero donde aparecen."""
    comparados: dict[str, set[str]] = {}
    escritos: dict[str, set[str]] = {}
    for path in iter_python_files(root):
        try:
            texto = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        relativo = path.relative_to(root).as_posix()
        for _columna, valor in _ASSIGNED_SQL.findall(texto):
            escritos.setdefault(valor, set()).add(relativo)
        for _columna, valor in _ASSIGNED_PY.findall(texto):
            escritos.setdefault(valor, set()).add(relativo)
        for valor in _RETURNED_PY.findall(texto):
            escritos.setdefault(valor, set()).add(relativo)
        for _columna, valor in _COMPARED.findall(texto):
            comparados.setdefault(valor, set()).add(relativo)
        for _columna, lista in _COMPARED_IN.findall(texto):
            for valor in _LITERAL_IN_LIST.findall(lista):
                comparados.setdefault(valor, set()).add(relativo)
    return comparados, escritos


def find_dead_status_values(root: Path) -> list[AliasFinding]:
    """Estados que el código consulta y que nadie escribe nunca.

    Es la forma exacta del corte terminal del aprendizaje:
    `_plan_memory_consolidation()` contaba `status = 'validated_in_runs'` y el
    pipeline hacía tiempo que terminaba en `evidence_verified`. La consulta era
    válida, la tabla existía, la columna existía — y el resultado era cero para
    siempre.
    """
    comparados, escritos = _status_literals(root)
    hallazgos: list[AliasFinding] = []
    for valor, ficheros in sorted(comparados.items()):
        if valor in escritos:
            continue
        pesos = piece_weights([*comparados, *escritos])
        pariente = max(
            ((otro, similarity(valor, otro, pesos)) for otro in escritos),
            key=lambda par: par[1],
            default=("", 0.0),
        )
        hallazgos.append(
            AliasFinding(
                signal="dead_status_value",
                kind="status",
                dead=valor,
                live=pariente[0] if pariente[1] >= SIMILARITY_THRESHOLD else "",
                detail=(
                    f"`{valor}` se compara en {len(ficheros)} fichero(s) y no lo "
                    "escribe nadie: la condición es cero para siempre"
                ),
                evidence={
                    "compared_in": sorted(ficheros)[:5],
                    "closest_written_value": pariente[0],
                    "similarity": round(pariente[1], 2),
                },
            )
        )
    return hallazgos


def profiles_from_artifact(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Perfiles de tabla a partir del `table_graph.json` ya generado.

    Reconstruir el grafo cuesta una relectura del AST completo. El artefacto lo
    escribe el generador y lo consume el panel de deuda, así que aquí se lee el
    mismo fichero en vez de repetir el escaneo: una sola medición, cuatro
    consumidores, como el resto de grafos.
    """
    if not payload:
        return {}
    return {
        str(nodo.get("label")): dict(nodo.get("metadata") or {})
        for nodo in payload.get("nodes") or []
        if str(nodo.get("node_id", "")).startswith("table:")
    }


def build_alias_debt(
    root: Path,
    index: ModuleIndex | None = None,
    db_path: Path | None = None,
    table_profiles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Informe completo de deuda de alias, con evidencia por hallazgo."""
    root = root.resolve()
    if table_profiles is not None:
        perfiles = table_profiles
    else:
        index = index or build_module_index(root)
        perfiles = _table_profiles(root, index, db_path)
    hallazgos = [
        *find_orphan_readers(perfiles),
        *find_lexical_aliases(perfiles),
        *find_dead_status_values(root),
    ]
    por_senal: dict[str, int] = {}
    for hallazgo in hallazgos:
        por_senal[hallazgo.signal] = por_senal.get(hallazgo.signal, 0) + 1
    return {
        "findings": [h.to_dict() for h in hallazgos],
        "total": len(hallazgos),
        "by_signal": por_senal,
        "tables_analysed": len(perfiles),
        "simulated": False,
    }
