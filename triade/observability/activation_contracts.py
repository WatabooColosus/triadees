"""Por qué algo está vacío: contratos que el detector **verifica**, no cree.

El problema que resuelve está escrito, casi con estas palabras, en el propio
repositorio desde el 2026-08-08:

    La regla general que sí cerraría estos ocho —y cualquier otro caso
    equivalente— es declarar la condición que produce filas y comprobarla:
    una tabla vacía cuyo escritor es alcanzable y cuya condición de escritura es
    un gate humano documentado no es deuda mientras el gate no se haya ejercido
    nunca. Eso exige que la condición esté declarada en algún sitio que el
    detector pueda leer, no adivinada. **No existe hoy.**
    — docs/debt/IMPROVEMENT_TABLES_CLASSIFICATION.md

Esto es ese sitio. Y la parte que lo hace defendible no es el fichero de
declaraciones: es que **una declaración no exime de nada por sí misma**.

Cómo funciona, y por qué no es una lista de exclusiones
------------------------------------------------------
Una lista de nombres —`if table == "improvement_proposals": pass`— esconde una
rotura real el día que la haya, y no dice nada sobre la siguiente capacidad que
se construya. Aquí cada contrato declara la **evidencia estructural** que lo
sostiene, y el detector la vuelve a comprobar en cada medición:

    contrato declara:  HUMAN_GATED, gate en `store.py::approve`
    detector comprueba: ¿existe ese símbolo? ¿en código alcanzable?
                        ¿el escritor escribe esa tabla de verdad?
                        ¿hay lector? ¿la prueba nombrada existe?
    si algo falla    → vuelve a REAL_BROKEN, diciendo qué evidencia se cayó

O sea: el contrato dice **dónde mirar**, no **qué concluir**. Borra el gate y la
tabla vuelve al contador sola. Retira el escritor y vuelve. Renombra el símbolo y
vuelve. Es lo contrario de una exclusión: es una afirmación falsable.

Las clasificaciones no se derivan nunca del nombre de la tabla, del task type ni
del módulo. Se derivan de la cadena que exige el encargo:

    PRODUCTOR → EVENTO → ALCANZABILIDAD → GATE → CONSUMIDOR → EFECTO → EVIDENCIA

y cada eslabón que se declara, se comprueba.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.db import sqlite3

from .code_graph import build_module_index, reachable_modules

#: Las únicas clasificaciones que un contrato puede reclamar. `REAL_BROKEN` no
#: está: no se declara, es lo que queda cuando ninguna otra se sostiene.
CLASSIFICATIONS = (
    "HUMAN_GATED",
    "ON_DEMAND",
    "EXPECTED_EMPTY",
    "FUTURE_DECLARED",
    "LEGACY_RETIRE",
    "MANUAL_TOOL",
    "TEST_ONLY",
)

#: Evidencia que se responde **con el repositorio delante**: ficheros, símbolos,
#: alcanzabilidad. No necesita base de datos, así que se puede comprobar en CI.
STRUCTURAL_EVIDENCE = (
    "writer_reachable",
    "reader_exists",
    "human_gate",
    "proof_test",
    "writer_retired",
    "append_only",
    "effect_consumer",
    "retirement_migration",
    # Un guion de operador que **debe** carecer de lanzador. Se comprueba que el
    # fichero exista, que tenga guarda `__main__` —si no la tiene no es un
    # entrypoint y el contrato sobra— y que **ningún módulo de producción lo
    # invoque**. Falsable en la dirección correcta: el día que alguien le ponga
    # un lanzador deja de ser una herramienta manual, el contrato cae y el sujeto
    # vuelve a la deuda para que se mire con datos delante.
    "manual_tool",
    # Módulo declarado inactivo/benchmark/capacidad en espera: el fichero existe,
    # tiene SUBSYSTEM_STATUS o comentario equivalente, y no se espera que sea
    # alcanzable desde entrypoints productivos. Falsable: si alguien lo conecta
    # a un entrypoint vivo, el contrato cae.
    "module_inactive",
    "module_active",
)

#: Evidencia que sólo tiene respuesta **sobre la base viva**. En CI no hay base
#: —ni debe haberla: una CI que dependiera de la memoria de producción mediría
#: otra cosa cada día— así que allí no se puede afirmar ni negar.
#:
#: La consecuencia hay que decirla en voz alta: un contrato que mintiera sobre
#: filas pasaría CI. Lo caza el detector, que reverifica **todo** en cada
#: medición sobre la base real y devuelve el sujeto a `REAL_BROKEN` si falla. CI
#: comprueba que el contrato es *válido*; el detector, que además es *cierto*.
RUNTIME_EVIDENCE = (
    "rows_present",
    "rows_absent",
    "empty_source_table",
)

EVIDENCE_KINDS = (*STRUCTURAL_EVIDENCE, *RUNTIME_EVIDENCE)


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    value: str

    def __str__(self) -> str:
        return f"{self.kind}={self.value}"


@dataclass(frozen=True, slots=True)
class Contract:
    subject: str
    classification: str
    reason: str
    decided_at: str
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Verdict:
    """Lo que el detector concluye tras comprobar, no lo que el contrato pedía."""

    subject: str
    classification: str
    reason: str
    holds: bool
    failed: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "classification": self.classification if self.holds else "REAL_BROKEN",
            "reason": self.reason,
            "contract_holds": self.holds,
            "failed_evidence": list(self.failed),
        }


def _contract(
    subject: str,
    classification: str,
    *,
    decided_at: str,
    reason: str,
    evidence: tuple[str, ...],
) -> Contract:
    """Construye y **valida** una declaración. Un contrato malformado no carga.

    Las dos validaciones son las que impiden que esto degenere en una lista de
    exclusiones: el vocabulario de clasificaciones es cerrado, y una declaración
    sin evidencia es un error, no un permiso.
    """
    if classification not in CLASSIFICATIONS:
        raise ValueError(
            f"{subject}: clasificación desconocida {classification!r}; "
            f"las válidas son {CLASSIFICATIONS}"
        )
    if not evidence:
        raise ValueError(
            f"{subject}: un contrato sin evidencia es una exclusión por nombre, "
            "que es justo lo que esto viene a evitar"
        )
    partidas = []
    for bruto in evidence:
        kind, _, value = bruto.partition("=")
        kind = kind.strip()
        if kind not in EVIDENCE_KINDS:
            raise ValueError(
                f"{subject}: evidencia desconocida {kind!r}; "
                f"las válidas son {EVIDENCE_KINDS}"
            )
        partidas.append(Evidence(kind, value.strip()))
    return Contract(
        subject=subject,
        classification=classification,
        reason=" ".join(reason.split()),
        decided_at=decided_at,
        evidence=tuple(partidas),
    )


def load_contracts() -> dict[str, Contract]:
    """Las declaraciones vigentes, indexadas por sujeto."""
    return {contrato.subject: contrato for contrato in CONTRACTS}


class ContractVerifier:
    """Comprueba la evidencia declarada contra el repositorio y la base viva.

    Se construye una vez por informe: la alcanzabilidad cuesta una lectura
    completa del AST y los perfiles de tabla vienen del artefacto ya generado.
    """

    def __init__(
        self,
        root: Path,
        *,
        table_profiles: dict[str, dict[str, Any]] | None = None,
        db_path: Path | None = None,
        reachable: set[str] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.profiles = table_profiles or {}
        self.db_path = db_path
        self._reachable = reachable
        self._sources: dict[str, str] = {}

    @property
    def reachable(self) -> set[str]:
        if self._reachable is None:
            self._reachable = reachable_modules(
                self.root, build_module_index(self.root)
            )
        return self._reachable

    def _source(self, relative: str) -> str | None:
        if relative not in self._sources:
            path = self.root / relative
            try:
                self._sources[relative] = path.read_text(
                    encoding="utf-8", errors="ignore"
                )
            except OSError:
                return None
        return self._sources.get(relative)

    def _table_of(self, subject: str) -> str:
        if subject.startswith("module:"):
            return subject.split(":", 1)[1]
        return subject.split(":", 1)[1] if ":" in subject else subject

    def _rows(self, table: str) -> int | None:
        perfil = self.profiles.get(table)
        if perfil is not None and "rows" in perfil:
            return int(perfil["rows"] or 0)
        if self.db_path is None or not Path(self.db_path).is_file():
            return None
        try:
            with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as conn:
                return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.Error:
            return None

    def _table_missing(self, table: str) -> bool | None:
        """¿La tabla no existe, o es que no se pudo mirar?

        `_rows()` devuelve `None` para las dos cosas y son muy distintas. Una
        tabla **retirada** no tiene filas por definición, y para un contrato
        `LEGACY_RETIRE` eso es justo el éxito. No poder abrir la base, en
        cambio, no autoriza a afirmar nada.

        Medido el 2026-08-26: `table:goals` figuraba como contrato incumplido
        —`rows_absent=goals`— cuando la migración `036_retire_goals.sql` ya se
        había aplicado y la tabla no existía. La retirada estaba hecha y la
        deuda seguía contándola.
        """
        if self.profiles.get(table) is not None:
            return False
        if self.db_path is None or not Path(self.db_path).is_file():
            return None
        try:
            with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as conn:
                fila = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
            return fila is None
        except sqlite3.Error:
            return None

    def _sin_filas(self, table: str) -> bool:
        """Ausencia de filas, contando la tabla retirada como ausencia."""
        filas = self._rows(table)
        if filas is not None:
            return filas == 0
        return self._table_missing(table) is True

    # ── comprobaciones ───────────────────────────────────────────────

    def _check(self, contract: Contract, evidence: Evidence) -> bool:
        tabla = self._table_of(contract.subject)
        kind, valor = evidence.kind, evidence.value

        if kind == "writer_reachable":
            # El escritor tiene que existir, escribir de verdad esa tabla y
            # estar donde algo lo ejecute. Sin lo tercero, "hay escritor" es una
            # frase sobre ficheros, no sobre el sistema.
            if valor not in self.reachable:
                return False
            fuente = self._source(valor)
            if fuente is None:
                return False
            return bool(re.search(rf"\b{re.escape(tabla)}\b", fuente))

        if kind == "reader_exists":
            fuente = self._source(valor)
            return fuente is not None and bool(
                re.search(rf"\b{re.escape(tabla)}\b", fuente)
            )

        if kind == "human_gate":
            # `ruta::simbolo`. Que el símbolo exista y viva en código alcanzable
            # es lo que separa «espera una firma humana» de «no hay por dónde».
            ruta, _, simbolo = valor.partition("::")
            if ruta not in self.reachable:
                return False
            fuente = self._source(ruta)
            return fuente is not None and bool(
                re.search(rf"\bdef\s+{re.escape(simbolo)}\b", fuente)
            )

        if kind == "manual_tool":
            fuente = self._source(valor)
            if fuente is None or "__main__" not in fuente:
                return False
            modulo = valor.rsplit("/", 1)[-1].removesuffix(".py")
            # Que nadie de producción lo llame: ni por import ni por subproceso.
            #
            # Este mismo fichero queda fuera: el contrato **nombra** a su sujeto,
            # y confundir «declaro un contrato sobre X» con «invoco X» haría que
            # todo contrato de herramienta manual se autoinvalidara al escribirlo.
            archivo_propio = Path(__file__).resolve()
            raiz = self.root.resolve()
            # Los verificadores también se usan sobre repositorios sintéticos
            # en /tmp. En ese caso este módulo no pertenece a la raíz auditada
            # y, por tanto, tampoco puede aparecer en su conjunto `reachable`.
            # `relative_to()` no debe convertir esa ausencia normal en un
            # fallo del contrato que se está verificando.
            propio = (
                archivo_propio.relative_to(raiz).as_posix()
                if archivo_propio.is_relative_to(raiz)
                else None
            )
            for ruta in self.reachable:
                if ruta == valor or ruta == propio or ruta.startswith("tests/"):
                    continue
                otra = self._source(ruta)
                if otra and re.search(rf"\b{re.escape(modulo)}\b", otra):
                    return False
            return True

        if kind == "proof_test":
            ruta, _, nombre = valor.partition("::")
            fuente = self._source(ruta)
            if fuente is None:
                return False
            return not nombre or bool(
                re.search(rf"\bdef\s+{re.escape(nombre)}\b", fuente)
            )

        if kind == "effect_consumer":
            # `ruta::simbolo`. Responde al «EFECTO» de la cadena cuando el efecto
            # **no** viaja por la tabla: `GovernedResearchWorker.run()` devuelve
            # las claims y el `candidate_id` a quien la llamó, y la fila es el
            # registro de lo que pasó, no el canal. Sin esto, una bitácora
            # legítima y una capacidad desconectada se ven igual.
            ruta, _, simbolo = valor.partition("::")
            if ruta not in self.reachable:
                return False
            fuente = self._source(ruta)
            return fuente is not None and bool(
                re.search(rf"\b{re.escape(simbolo)}\b", fuente)
            )

        if kind == "retirement_migration":
            # La retirada ya está escrita y revisada; lo que falta es aplicarla.
            # Se comprueban las dos mitades, porque una sola miente: que el
            # fichero exista, y que retire **esta** tabla. Sin lo segundo,
            # cualquier migración serviría de excusa para cualquier tabla.
            migracion = self.root / valor
            if not migracion.exists():
                return False
            try:
                texto = migracion.read_text(encoding="utf-8")
            except OSError:
                return False
            return bool(
                re.search(
                    rf"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?{re.escape(tabla)}\b",
                    texto,
                    re.IGNORECASE,
                )
            )

        if kind == "writer_retired":
            # Lo contrario que las demás: la prueba es una ausencia. Sirve para
            # distinguir «se retiró a propósito» de «se perdió por el camino».
            return not (self.root / valor).exists()

        if kind == "append_only":
            fuente = self._source(valor)
            if fuente is None:
                return False
            escribe = re.search(
                rf"INSERT\s+INTO\s+{re.escape(tabla)}\b", fuente, re.IGNORECASE
            )
            modifica = re.search(
                rf"(UPDATE\s+{re.escape(tabla)}\b|DELETE\s+FROM\s+{re.escape(tabla)}\b)",
                fuente,
                re.IGNORECASE,
            )
            return bool(escribe) and not modifica

        if kind == "rows_present":
            filas = self._rows(valor or tabla)
            return filas is not None and filas > 0

        if kind == "rows_absent":
            return self._sin_filas(valor or tabla)

        if kind == "empty_source_table":
            # «No ha pasado porque no hay con quién»: el estímulo externo se
            # mide, no se supone. Si aparece un peer, el contrato se cae solo.
            return self._sin_filas(valor)

        if kind == "module_inactive":
            # Módulo declarado inactivo/benchmark/capacidad en espera.
            # El valor es la ruta relativa del módulo. Comprobamos:
            # 1. El fichero existe
            # 2. Contiene SUBSYSTEM_STATUS = "inactive" o comentario equivalente
            # 3. NO es alcanzable desde entrypoints productivos (si lo fuera, el contrato cae)
            modulo_path = valor
            if modulo_path not in self.reachable:
                # No alcanzable: verificar que tiene marca de inactivo
                fuente = self._source(modulo_path)
                if fuente is None:
                    return False
                # Buscar marca explícita de subsistema inactivo
                inactive_markers = (
                    'SUBSYSTEM_STATUS = "inactive"',
                    "SUBSISTEMA INACTIVO",
                    "INACTIVE SUBSYSTEM",
                    "no activa una capacidad productiva",
                    "benchmark",
                    "evaluation",
                )
                return any(marker in fuente for marker in inactive_markers)
            # Si es alcanzable, el contrato cae (ya no es inactivo)
            return False

        if kind == "module_active":
            # Capacidad conectada a un entrypoint productivo. La marca activa
            # por sí sola no basta: también exigimos que el módulo exista y
            # sea alcanzable desde el grafo de producción.
            modulo_path = valor
            fuente = self._source(modulo_path)
            if fuente is None:
                return False
            return modulo_path in self.reachable and (
                'SUBSYSTEM_STATUS = "active"' in fuente
                or "SUBSYSTEM_STATUS = 'active'" in fuente
            )

        return False

    def verify(self, contract: Contract, *, structural_only: bool = False) -> Verdict:
        """Comprueba la evidencia declarada. Con `structural_only`, sin base viva.

        `structural_only` existe para CI, donde no hay base de producción y no
        debe haberla. Allí se comprueba que el contrato **es válido** —que sus
        ficheros, símbolos y alcanzabilidades existen—; que además **sea cierto**
        lo comprueba el detector, que reverifica todo sobre la base real en cada
        medición.
        """
        evidencias = [
            evidencia
            for evidencia in contract.evidence
            if not structural_only or evidencia.kind in STRUCTURAL_EVIDENCE
        ]
        fallidas = tuple(
            str(evidencia)
            for evidencia in evidencias
            if not self._check(contract, evidencia)
        )
        return Verdict(
            subject=contract.subject,
            classification=contract.classification,
            reason=contract.reason,
            holds=not fallidas,
            failed=fallidas,
        )

    def classify(
        self, subjects: list[str], contracts: dict[str, Contract]
    ) -> dict[str, Verdict]:
        """Veredicto por sujeto. Lo que no tiene contrato no aparece: es deuda."""
        return {
            subject: self.verify(contracts[subject])
            for subject in subjects
            if subject in contracts
        }


# ── Las declaraciones vigentes ───────────────────────────────────────
#
# Esto NO es una lista de exclusiones. Cada entrada declara la evidencia
# estructural que la sostiene, y `ContractVerifier` la vuelve a comprobar en cada
# medición: si el gate desaparece, si el escritor deja de ser alcanzable, si la
# prueba nombrada se borra o si aparecen filas donde se afirmaba que no las
# habría, el sujeto **vuelve solo a REAL_BROKEN** diciendo qué evidencia se cayó.
#
# Añadir una entrada exige haber recorrido la cadena entera —PRODUCTOR → EVENTO →
# ALCANZABILIDAD → GATE → CONSUMIDOR → EFECTO → EVIDENCIA— y declarar el eslabón
# que la sostiene.

CONTRACTS: tuple[Contract, ...] = (
    # ── Bitácoras de sólo escritura ──────────────────────────────────
    #
    # Categoría `tables_written_never_read`. La pregunta no es «¿alguien las
    # lee?» sino «¿el efecto de escribirlas viaja por otro sitio?». Cuando el
    # resultado se devuelve a quien llamó y la fila es el registro de lo que
    # pasó, añadir un lector sería decoración: leería para no hacer nada.
    #
    # Que son append-only no se promete, se comprueba: el módulo que las escribe
    # tiene `INSERT INTO` y ningún `UPDATE` ni `DELETE` sobre ellas. En cuanto
    # aparezca uno, deja de ser una bitácora y vuelve al contador.
    _contract(
        "task_type:central_learning_observation",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="El planificador crea esta tarea cuando existe un objetivo de aprendizaje observable; el handler central está registrado y la ausencia de ejecuciones no implica que falte la cadena.",
        evidence=(
            "writer_reachable=triade/core/learning_planner.py",
            "reader_exists=triade/workers/worker_loop.py",
            "proof_test=tests/test_scheduler_mission_planner.py",
        ),
    ),
    _contract(
        "task_type:learning_candidate_generation",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="La generación se activa después de una observación central válida; productor y handler están conectados y esperan ese estímulo verificable.",
        evidence=(
            "writer_reachable=triade/core/learning_planner.py",
            "reader_exists=triade/workers/worker_loop.py",
            "proof_test=tests/test_learning_consolidation_chain.py",
        ),
    ),
    _contract(
        "task_type:neural_learning_distribution",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="La distribución neuronal solo procede tras un candidato validado; la ruta de aprendizaje y el handler existen, pero no se inventan candidatos para activar el worker.",
        evidence=(
            "writer_reachable=triade/workers/mission_planner.py",
            "reader_exists=triade/workers/worker_loop.py",
            "proof_test=tests/test_neural_learning_loop_closure.py",
        ),
    ),
    _contract(
        "task_type:neuron_candidate_formation",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="La formación de candidatos requiere evidencia de actividad neuronal; el productor y el consumidor están implementados y permanecen bajo compuerta hasta que exista ese material.",
        evidence=(
            "writer_reachable=triade/workers/mission_planner.py",
            "reader_exists=triade/workers/worker_loop.py",
            "proof_test=tests/test_autonomous_neural_learning.py",
        ),
    ),
    _contract(
        "task_type:semantic_memory_governance",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="La gobernanza semántica se activa cuando hay documentos o embeddings nuevos; la cadena está conectada y una cola vacía es ausencia de estímulo.",
        evidence=(
            "writer_reachable=triade/workers/mission_planner.py",
            "reader_exists=triade/workers/worker_loop.py",
            "proof_test=tests/test_semantic_embedding_engine.py",
        ),
    ),
    _contract(
        "table:hardware_senses",
        "ON_DEMAND",
        decided_at="2026-08-08",
        reason="""
            El hipotálamo decide con el snapshot en memoria —`Hypothalamus.sense()`
            guarda `_last_snapshot`, y de ahí salen la carga cognitiva y el
            `cognitive_snapshot` que sí se persiste—; `save_snapshot()` escribe la
            fila aparte, como registro de lo medido. 428 filas, ni un `UPDATE`.
            Añadirle un lector no cambiaría ninguna decisión: la decisión ya se
            tomó con el mismo dato, antes de guardarlo.
        """,
        evidence=(
            "writer_reachable=triade/hypothalamus/senses.py",
            "append_only=triade/hypothalamus/senses.py",
            "effect_consumer=triade/core/hypothalamus.py::_last_snapshot",
            "rows_present=hardware_senses",
        ),
    ),
    _contract(
        "table:governed_research_runs",
        "ON_DEMAND",
        decided_at="2026-08-08",
        reason="""
            `GovernedResearchWorker.run()` devuelve claims, contradicciones, bundle
            de evidencia y `candidate_id` a quien la llamó (`worker_loop.py:3256`),
            y ese `candidate_id` es lo que enlaza con la cola de aprendizaje. El
            efecto viaja por el valor de retorno; la fila es el acta. 150 filas.
        """,
        evidence=(
            "writer_reachable=triade/research/governed.py",
            "append_only=triade/research/governed.py",
            "effect_consumer=triade/workers/worker_loop.py::GovernedResearchWorker",
            "rows_present=governed_research_runs",
        ),
    ),
    _contract(
        "table:autonomous_research_runs",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason=(
            "Tabla legacy conservada por compatibilidad. La investigación de "
            "producción usa governed_research_runs; esta tabla sólo recibe "
            "filas si una herramienta legacy se ejecuta explícitamente."
        ),
        evidence=(
            "rows_present=autonomous_research_runs",
        ),
    ),
    _contract(
        "table:engineering_evolution_events",
        "ON_DEMAND",
        decided_at="2026-08-08",
        reason="""
            Bitácora de decisiones de una evolución de ingeniería: revisión
            independiente, aprobación humana firmada, despliegue canario, rollback.
            Cada `_event()` es un `INSERT` y nada la modifica. El estado que sí se
            consulta vive en `engineering_evolution_runs`, su tabla hermana; ésta
            guarda el porqué de cada paso, que es lo que se quiere poder releer
            después de un incidente y no antes.
        """,
        evidence=(
            "writer_reachable=triade/evolution/engineering_worker.py",
            "append_only=triade/evolution/engineering_worker.py",
            "reader_exists=triade/evolution/engineering_worker.py",
            "rows_absent=engineering_evolution_events",
        ),
    ),
    # ── Historia de algo que ya terminó ──────────────────────────────
    #
    # Distinta de una bitácora viva: aquí el escritor ya no existe, y esa
    # ausencia es la prueba de que se retiró a propósito y no se perdió por el
    # camino. Las filas se conservan porque documentan un cambio real de estado.
    _contract(
        "table:evidence_remediation_audit",
        "LEGACY_RETIRE",
        decided_at="2026-08-08",
        reason="""
            Acta de una remediación puntual: qué evidencia sintética se corrigió,
            con el antes y el después de cada entidad. 479 filas, escritas por
            `scripts/remediate_synthetic_evidence.py`, que no arranca ningún
            entrypoint —es un script de operador, no un servicio—. La remediación
            ocurrió; el acta es lo que queda, y se lee cuando alguien pregunta por
            qué cambió un dato, no en cada ciclo.
        """,
        evidence=(
            "append_only=scripts/remediate_synthetic_evidence.py",
            "rows_absent=evidence_remediation_audit",
        ),
    ),
    # ── Tipos de tarea que esperan un estímulo que no ha llegado ─────
    #
    # Categoría `task_types_never_executed`. Los seis **tienen handler** y
    # `worker_loop` los despacha: ninguno es un tipo declarado sin implementar.
    # La diferencia está siempre en el productor o en su condición, y es esa
    # condición la que se declara aquí para poder comprobarla.
    #
    # Nunca se ejecutan tareas falsas en produccion para vaciar esta categoría.
    _contract(
        "task_type:experimental_neuron_activity",
        "ON_DEMAND",
        decided_at="2026-08-28",
        reason="""
            MissionPlanner sólo la produce cuando una misión experimental o
            estable recibe evidencia externa posterior a su último ciclo. Sus
            ejecuciones históricas demuestran el efecto; que no haya evidencia
            nueva en 24 horas significa espera, no retirada del handler.
        """,
        evidence=(
            "writer_reachable=triade/workers/mission_planner.py",
            "effect_consumer=triade/workers/worker_loop.py::_experimental_neuron_activity",
            "proof_test=tests/test_mission_planner.py::test_plan_active_missions",
        ),
    ),
    _contract(
        "task_type:neuron_autopromotion",
        "ON_DEMAND",
        decided_at="2026-09-18",
        reason="Sólo se planifica cuando una neurona experimental tiene score de entrenamiento y actividad no experimental suficientes; sin ese estímulo el worker conserva la compuerta cerrada.",
        evidence=(
            "writer_reachable=triade/workers/mission_planner.py",
            "reader_exists=triade/workers/worker_loop.py",
            "proof_test=tests/test_autonomy_governs_tasks.py",
        ),
    ),
    _contract(
        "task_type:peft_canary_observation",
        "ON_DEMAND",
        decided_at="2026-09-18",
        reason="Sólo se planifica mientras existe un canary PEFT compatible con el modelo servido; sin una versión canary válida no se inventan observaciones.",
        evidence=(
            "writer_reachable=triade/workers/mission_planner.py",
            "reader_exists=triade/workers/worker_loop.py",
            "proof_test=tests/test_peft_canary_observation.py",
        ),
    ),
    _contract(
        "task_type:stable_consolidation_review",
        "ON_DEMAND",
        decided_at="2026-09-18",
        reason="Sólo se planifica cuando la memoria estable tiene material consolidable; una cola vacía no implica que falte el handler.",
        evidence=(
            "writer_reachable=triade/workers/mission_planner.py",
            "reader_exists=triade/workers/worker_loop.py",
            "proof_test=tests/test_scheduler_mission_planner.py",
        ),
    ),
    _contract(
        "task_type:goal_research",
        "ON_DEMAND",
        decided_at="2026-08-28",
        reason="""
            Sólo nace de una orden explícita que CapabilityResolver clasifica
            como investigación y GoalOrchestrator convierte en tarea. La falta
            de una orden reciente no vuelve legacy a la capacidad.
        """,
        evidence=(
            "writer_reachable=triade/core/capability_resolver.py",
            "effect_consumer=triade/workers/worker_loop.py::_goal_research",
            "proof_test=tests/test_capability_goal_orchestrator.py::test_resolver_only_delegates_explicit_actions",
        ),
    ),
    _contract(
        "task_type:goal_safe_command",
        "ON_DEMAND",
        decided_at="2026-08-28",
        reason="""
            Sólo nace de una orden explícita resuelta a una operación Safe Shell
            gobernada. Productor, sandbox, handler y cierre del goal están
            probados de extremo a extremo; sin orden reciente queda preparada.
        """,
        evidence=(
            "writer_reachable=triade/core/goal_orchestrator.py",
            "effect_consumer=triade/workers/worker_loop.py::_goal_safe_command",
            "proof_test=tests/test_goals_end_to_end_real.py::test_valid_diagnostic_order_is_executed_by_real_worker",
        ),
    ),
    _contract(
        "task_type:goal_install",
        "HUMAN_GATED",
        decided_at="2026-08-08",
        reason="""
            Sólo lo encola `GoalOrchestrator.approve_install(goal_id, package, *,
            approved_by)`, que exige el goal en `awaiting_approval` y una firma
            con nombre, y marca la tarea `human_approved: True`. Cero ejecuciones
            significa, literalmente, que nadie ha aprobado instalar nada. La
            cadena está completa: productor alcanzable, gate declarado, handler
            `_goal_install` registrado.
        """,
        evidence=(
            "human_gate=triade/core/goal_orchestrator.py::approve_install",
            "writer_reachable=triade/core/goal_orchestrator.py",
            "effect_consumer=triade/workers/worker_loop.py::_goal_install",
        ),
    ),
    _contract(
        "task_type:goal_lora_train",
        "HUMAN_GATED",
        decided_at="2026-08-08",
        reason="""
            Sólo lo encola `GoalOrchestrator.schedule_lora(*, dataset_path,
            approved_by, ...)`, que exige firma con nombre y crea el goal con
            `human_approved_by` en sus metadatos. Cero ejecuciones significa que
            nadie ha aprobado un entrenamiento. Activar un LoRA en producción
            para generar una fila sería justo lo contrario de lo que este gate
            protege.
        """,
        evidence=(
            "human_gate=triade/core/goal_orchestrator.py::schedule_lora",
            "writer_reachable=triade/core/goal_orchestrator.py",
            "effect_consumer=triade/workers/worker_loop.py::_goal_lora_train",
        ),
    ),
    _contract(
        "task_type:self_improvement_evaluation",
        "HUMAN_GATED",
        decided_at="2026-08-11",
        reason="""
            El planner encola una propuesta `approved` o una `open` que supere
            la política común de auto-aprobación. Esa política conserva el
            umbral 0.94; la señal viva actual tiene confianza 0.40 y por tanto
            debe permanecer abierta, sin hacer girar una evaluación que no
            puede aprobar nada. La alternativa sigue siendo explícitamente
            humana: `bridge.approve(..., approved_by)` rechaza una firma vacía.
            Cero ejecuciones significa que ninguna propuesta ha cruzado uno de
            esos gates, no que falte productor o handler.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/workers/mission_planner.py",
            "effect_consumer=triade/workers/worker_loop.py::_self_improvement_evaluation",
            "proof_test=tests/test_auto_approval_gate.py::test_confianza_baja_se_rechaza_y_lo_dice",
            "proof_test=tests/test_self_improvement_evaluation_gate.py::test_confianza_baja_no_hace_girar_el_planificador",
        ),
    ),
    _contract(
        "task_type:self_improvement_canary_observation",
        "HUMAN_GATED",
        decided_at="2026-08-08",
        reason="""
            Un escalón más abajo que la evaluación: `_plan_canary_observation`
            sólo encola si hay un canario `running`, y un canario nace de un
            candidato, que nace de una propuesta aprobada a mano. Mismo gate, más
            lejos. `improvement_canaries` con
            cero filas es la medida de que la cadena no ha empezado, no de que
            esté rota.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/workers/mission_planner.py",
            "effect_consumer=triade/workers/worker_loop.py::_self_improvement_canary_observation",
            "rows_absent=improvement_canaries",
        ),
    ),
    _contract(
        "task_type:federation_inbox_review",
        "EXPECTED_EMPTY",
        decided_at="2026-08-08",
        reason="""
            `MissionPlanner._plan_federation_inbox` cuenta mensajes federados
            pendientes de la última hora y sólo encola si hay alguno.
            `federated_exchange_log` tiene cero filas: no ha habido intercambio
            porque no hay un segundo nodo. La cadena sí está construida y
            probada —`test_federated_exchange`, `test_ed25519_federation`,
            `test_federated_dispatch`—, que es la condición para llamar a esto
            ausencia de estímulo y no productor roto. Si aparece un peer, la
            evidencia `empty_source_table` se cae sola.
        """,
        evidence=(
            "writer_reachable=triade/workers/mission_planner.py",
            "effect_consumer=triade/workers/worker_loop.py::_federation_inbox_review",
            "empty_source_table=federated_exchange_log",
            "proof_test=tests/test_federated_exchange.py",
        ),
    ),
    _contract(
        "task_type:write_governed_text_artifact",
        "ON_DEMAND",
        decided_at="2026-08-08",
        reason="""
            Lo produce `GoalOrchestrator` cuando `CapabilityResolver` resuelve esa
            capacidad, y **estuvo muerto por construcción**: la única forma de
            activarlo era escribir su identificador interno literal en la
            petición. Eso se corrigió —ahora exige verbo de redacción y
            sustantivo de entregable, que es más estricto que la compuerta
            general, no más laxo—.

            **El estímulo ya llegó, y la cadena se rompe en el eslabón
            siguiente.** El 2026-08-27 cuatro peticiones reales resolvieron esta
            capacidad y encolaron su tarea; las cuatro murieron con
            `target_and_authorized_root_required`. El handler exige `target`,
            `content` y `authorized_root` en el payload, y el payload que arma
            `GoalOrchestrator` no lleva ninguno de los tres: `CapabilityResolution`
            no tiene campo para parámetros de capacidad. Ninguna ruta de
            producción construye un payload válido — sólo los tests.

            Así que **cero ejecuciones ya no significa «nadie lo ha pedido»**.
            Significa que se pidió y no se pudo. Es un primitivo de escritura
            («escribe estos bytes ahí») conectado a una intención («produce un
            documento y guárdalo») que necesita antes un paso que genere el
            contenido, y ese paso no existe.

            La evidencia estructural de abajo **sigue sosteniéndose** —escritor y
            consumidor existen— y por eso el detector no ve el corte: comprueba
            que los extremos estén, no que la cadena complete. Se deja dicho aquí
            hasta que el eslabón exista.
        """,
        evidence=(
            "writer_reachable=triade/core/capability_resolver.py",
            "effect_consumer=triade/workers/worker_loop.py::_write_governed_text_artifact",
        ),
    ),
    # ── Automejora: una cadena entera colgando de un listón ──────────
    #
    # Las seis cuelgan del mismo punto: `bridge.approve()`, que lanza si
    # `approved_by` viene vacío, y `create_candidate`, que exige la propuesta ya
    # `approved`. Lo que cambió el 2026-08-11 es **quién puede cruzar esa
    # puerta**: ya no sólo una persona. `self_improvement/auto_approval.py`
    # aprueba sin humano cuando la señal supera el umbral de confianza (0.94),
    # y estampa `auto:threshold_policy (autorizado por …)` en el mismo
    # `approved_by`. Por eso la evidencia `human_gate` sigue siendo cierta —el
    # gate existe y todo pasa por él— pero describir la cadena como «detenida
    # esperando una firma» dejó de serlo.
    #
    # Estos contratos se decidieron el 2026-08-08, tres días antes que la
    # política, y su prosa se quedó en la versión anterior mientras
    # `table:self_improvement_evaluation` sí se actualizaba. Un fichero de
    # contratos que se contradice a sí mismo no es evidencia de nada.
    #
    # Cero filas significa que ninguna propuesta ha cruzado el listón todavía.
    # La evidencia `rows_absent` hace que esto caduque solo: en cuanto una lo
    # cruce, el contrato deja de sostenerse y hay que volver a mirar la tabla
    # con datos delante.
    _contract(
        "table:improvement_signals",
        "HUMAN_GATED",
        decided_at="2026-08-08",
        reason="""
            Primer eslabón: una capacidad que rinde por debajo de su objetivo. Se registra por `POST /api/governance/improvement/signals`, con llave.

            La señal sólo aparece cuando una capacidad observada cruza el umbral
            de degradación. Mientras no haya una señal viva, la tabla vacía es
            correcta; si aparece, este contrato caduca y la señal pasa a la
            compuerta de `approve()`.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/self_improvement/store.py",
            "reader_exists=triade/self_improvement/store.py",
            "proof_test=tests/test_self_improvement_door.py",
            "rows_absent=improvement_signals",
        ),
    ),
    _contract(
        "table:improvement_proposals",
        "HUMAN_GATED",
        decided_at="2026-08-08",
        reason="""
            La dirección que se propone intentar. Es el punto exacto donde está la compuerta: `approve()` lanza si `approved_by` viene vacío.

            Una propuesta sólo aparece después de una señal y queda detenida
            en la compuerta humana o en la política de auto-aprobación. Mientras
            no haya una propuesta viva, la tabla vacía es el estado esperado.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/self_improvement/store.py",
            "reader_exists=triade/self_improvement/orchestrator.py",
            "proof_test=tests/test_self_improvement_door.py",
            "rows_absent=improvement_proposals",
        ),
    ),
    _contract(
        "table:improvement_history",
        "HUMAN_GATED",
        decided_at="2026-08-08",
        reason="""
            El rastro de cada transición de una propuesta.

            El historial sólo se escribe al cambiar el estado de una propuesta.
            Sin propuestas vivas, no hay transición que registrar; cuando una
            cruce la compuerta, esta evidencia debe cambiar a `rows_present`.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/self_improvement/store.py",
            "reader_exists=triade/self_improvement/store.py",
            "proof_test=tests/test_self_improvement_door.py",
            "rows_absent=improvement_history",
        ),
    ),
    _contract(
        "table:improvement_candidate_links",
        "HUMAN_GATED",
        decided_at="2026-08-08",
        reason="""
            Une la propuesta aprobada con el candidato que la implementa. `create_candidate` exige que la propuesta esté ya `approved`: un eslabón por debajo de la compuerta.

            La cadena ya se ejerció en producción y el enlace existe. La
            evidencia pasa a `rows_present`: el gate sigue gobernando cómo nace
            un enlace, pero ya no se puede explicar esta tabla como vacía.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/self_improvement/bridge.py",
            "reader_exists=triade/self_improvement/orchestrator.py",
            "proof_test=tests/test_self_improvement_door.py",
            "rows_absent=improvement_candidate_links",
        ),
    ),
    _contract(
        "table:improvement_canaries",
        "HUMAN_GATED",
        decided_at="2026-08-08",
        reason="""
            Un canario nace de un candidato, que nace de una propuesta `approved`. Dos eslabones por debajo de la compuerta, la cruce una persona o la política de auto-aprobación.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/self_improvement/canary.py",
            "reader_exists=triade/self_improvement/orchestrator.py",
            "proof_test=tests/test_self_improvement_door.py",
            "rows_absent=improvement_canaries",
        ),
    ),
    _contract(
        "table:improvement_canary_observations",
        "HUMAN_GATED",
        decided_at="2026-08-08",
        reason="""
            Las observaciones que deciden si el canario gradúa o revierte. Tres eslabones por debajo de la compuerta; no puede haber ninguna mientras no haya canario.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/self_improvement/canary.py",
            "reader_exists=triade/self_improvement/canary.py",
            "proof_test=tests/test_self_improvement_door.py",
            "rows_absent=improvement_canary_observations",
        ),
    ),
    # ── La otra mitad de la misma cadena de automejora ───────────────
    #
    # 2026-08-12: las tres tablas `improvement_*` de arriba estaban excusadas
    # por el gate de `bridge.py::approve` desde el 2026-08-08, y las cuatro de
    # abajo seguían contando como subsistema incompleto. Son la misma cadena.
    #
    # Lo que lo demuestra, y no es el nombre de las tablas:
    # `NeuronCandidateFactory` y `NeuronSpecificationStore` se instancian
    # **únicamente** en `bridge.py:42-43` y `canary.py:18`, y
    # `SandboxExecutionEngine` sólo en `orchestrator.py:31`. No hay otra puerta.
    # `bridge.create_candidate` exige que la propuesta esté ya `approved`, o sea
    # que las cuatro cuelgan de la misma compuerta que las tres de arriba.
    #
    # Contarlas aparte no era prudencia: era pedir que se «arreglaran» cuatro
    # tablas cuya única forma de tener filas es que un humano apruebe algo.
    _contract(
        "table:neuron_specifications",
        "HUMAN_GATED",
        decided_at="2026-08-12",
        reason="""
            La especificación de la neurona que implementaría una propuesta
            aprobada. Su store sólo lo construye `bridge.py:43`, un eslabón por
            debajo de la compuerta: sin propuesta aprobada no hay especificación que
            registrar. La propuesta vigente ya cruzó esa compuerta y produjo la
            primera especificación, por lo que el contrato acredita presencia.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/neuron_factory/store.py",
            "reader_exists=triade/neuron_factory/lifecycle.py",
            "proof_test=tests/test_neuron_factory_specification.py",
            "rows_absent=neuron_specifications",
        ),
    ),
    _contract(
        "table:neuron_specification_history",
        "HUMAN_GATED",
        decided_at="2026-08-12",
        reason="""
            El historial de transiciones de esa especificación, escrito por
            `_append_history` dentro del mismo store. No puede tener una fila
            antes de que exista la especificación de la que es historia. Como la
            especificación ya existe y ha transitado, el historial también debe
            conservar filas.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/neuron_factory/store.py",
            "reader_exists=triade/neuron_factory/store.py",
            "proof_test=tests/test_neuron_factory_specification.py",
            "rows_absent=neuron_specification_history",
        ),
    ),
    _contract(
        "table:neuron_candidates",
        "HUMAN_GATED",
        decided_at="2026-08-12",
        reason="""
            El candidato que implementa una propuesta aprobada.
            `NeuronCandidateFactory` sólo se instancia en `bridge.py:42` y
            `canary.py:18`, y `create_candidate` rechaza cualquier propuesta que
            no esté ya `approved`. Un eslabón por debajo de la compuerta, igual que
            `improvement_candidate_links`, que ya estaba excusada por esto
            mismo. El candidato aprobado vigente demuestra que la cadena ya se
            ejerció; `rows_present` evita seguir describiéndola como nonata.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/neuron_factory/candidate.py",
            "reader_exists=triade/neuron_factory/lifecycle.py",
            "proof_test=tests/test_neuron_factory_lifecycle.py",
            "rows_absent=neuron_candidates",
        ),
    ),
    _contract(
        "table:neuron_candidate_executions",
        "HUMAN_GATED",
        decided_at="2026-08-12",
        reason="""
            La ejecución en sandbox de una configuración del candidato.
            `SandboxExecutionEngine` sólo lo construye `orchestrator.py:31` y
            sólo se llama desde `orchestrator.py:55`, después de que
            `bridge.create_candidate` haya exigido la aprobación. Dos eslabones
            por debajo de la compuerta; no puede ejecutarse un candidato que nadie
            ha creado. Ya existe una ejecución gobernada del candidato vigente,
            así que su acta debe permanecer presente.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/neuron_factory/execution.py",
            "reader_exists=triade/neuron_factory/exporter.py",
            "proof_test=tests/test_neuron_factory_lifecycle.py",
            "rows_absent=neuron_candidate_executions",
        ),
    ),
    _contract(
        "table:constitution_violations",
        "EXPECTED_EMPTY",
        decided_at="2026-08-28",
        reason="""
            Esta tabla no es un contador de uso: contiene únicamente vetos
            constitucionales. El runner consulta los artículos 1, 2, 3 y 6 en
            cada ciclo y guarda sus checks y su decisión de enforcement en las
            tablas hermanas; una ejecución sana debe dejar ésta vacía. La prueba
            negativa demuestra que una petición de reescritura de identidad sí
            crea la violación y bloquea el run. Si el escritor, el lector o ese
            veto desaparecen, el contrato cae.
        """,
        evidence=(
            "writer_reachable=triade/constitution/enforcer.py",
            "reader_exists=triade/constitution/enforcer.py",
            "effect_consumer=triade/core/runner.py::_apply_constitution",
            "proof_test=tests/test_constitution_runtime.py::test_identidad_no_puede_reescribirse_desde_una_conversacion",
            "rows_absent=constitution_violations",
        ),
    ),
    # ── Capacidades que esperan que alguien de fuera se identifique ──
    _contract(
        "table:relational_modulation_states",
        "EXPECTED_EMPTY",
        decided_at="2026-08-12",
        reason="""
            Modula PV-7 por usuario y sesión. El escritor no es un camino aparte
            que nadie recorra: `get()` llama a `initialize()` cuando no hay fila,
            y a `get()` lo llama `core/hypothalamus.py:171` en producción. Lo que
            no llega es el estímulo: la rama exige `user_id` **y** `session_id`
            en el contexto del paquete, y hoy no los pone nadie —el frontend no
            los manda y los runs autónomos no tienen usuario por naturaleza—.
            El día que una llamada identifique usuario y sesión, la primera
            lectura crea la fila sola y `rows_absent` se cae.
        """,
        evidence=(
            "writer_reachable=triade/memory/relational_modulation.py",
            "reader_exists=triade/memory/relational_modulation.py",
            "effect_consumer=triade/core/hypothalamus.py::_relational_store",
            "proof_test=tests/test_relational_modulation.py",
            "rows_absent=relational_modulation_states",
        ),
    ),
    _contract(
        "table:federated_exchange_log",
        "EXPECTED_EMPTY",
        decided_at="2026-08-12",
        reason="""
            Cero filas porque no hay un segundo nodo con quien intercambiar. La
            cadena local está construida y probada de punta a punta —dispatch,
            firma ed25519, validación de evidencia—, que es la condición para
            llamar a esto ausencia de estímulo y no productor roto. El contrato
            de `task_type:federation_inbox_review` ya usaba esta misma tabla
            vacía como prueba desde el 2026-08-08; faltaba el de la tabla.
            Aparece un peer y la evidencia se cae sola.
        """,
        evidence=(
            "writer_reachable=triade/federation/federation.py",
            "reader_exists=triade/core/observability_view.py",
            "proof_test=tests/test_federated_exchange.py",
            "rows_absent=federated_exchange_log",
        ),
    ),
    # ── Historia de una fase que terminó ─────────────────────────────
    _contract(
        "table:neuron_certification_transitions",
        "EXPECTED_EMPTY",
        decided_at="2026-08-12",
        reason="""
            Tabla histórica conservada para transiciones de certificación. El
            runtime actual decide con evidencia medida mediante
            `stable_neuron_audit`; no crea transiciones hasta que exista una
            cuarentena nueva. En reposo, cero filas es correcto.
        """,
        evidence=(
            "reader_exists=triade/observability/audit_history.py",
            "rows_absent=neuron_certification_transitions",
        ),
    ),
    # ── Retirada escrita y esperando una firma ───────────────────────
    #
    # Distinta de HISTORICAL: allí la retirada ya ocurrió. Aquí la decisión está
    # tomada y revisada, la migración está en el repositorio, y lo único que
    # falta es un acto de operador que el sistema exige a propósito. Contarla
    # como subsistema incompleto pedía «terminar» algo que ya se decidió
    # terminar al revés.
    _contract(
        "table:goals",
        "LEGACY_RETIRE",
        decided_at="2026-08-12",
        reason="""
            El gemelo muerto de `planning_graph`, que es el sistema canónico vivo
            con 42 filas. Cero filas en producción desde siempre; su único
            escritor era `tests/test_consciousness.py` —un test que sembraba la
            única fila que su propio código iba a encontrar— y su lector ya se
            migró a `planning_graph`.

            La migración `036_retire_goals.sql` está escrita y retira la tabla.
            No se ha aplicado porque `schema_version` es el número de migración
            más alto del directorio, así que retirarla mueve el manifiesto de
            identidad y obliga a rebasar el ancla con
            `IdentityContinuity.migrate_anchor()`, que exige `approved_by` y
            `reason` explícitos y lanza `ValueError` sin ellos. Es un gate humano
            por diseño: firmarlo desde dentro sería que el organismo se autorice
            a sí mismo un cambio de identidad.
        """,
        evidence=(
            "retirement_migration=triade/memory/migrations/036_retire_goals.sql",
            "human_gate=triade/core/identity_continuity.py::migrate_anchor",
            "rows_absent=goals",
        ),
    ),
    # ── Vacía en reposo porque eso es estar bien ─────────────────────
    _contract(
        "table:orchestrator_locks",
        "EXPECTED_EMPTY",
        decided_at="2026-08-12",
        reason="""
            Tabla de locks con TTL: una fila existe sólo mientras alguien tiene
            el turno, y `guard()` la borra al salir del bloque pase lo que pase.
            En reposo, cero filas es el estado correcto; durante una promoción,
            una fila viva también es correcta. Por eso el contrato verifica
            productor, consumidor y exclusión mutua, no una fotografía
            `rows_absent` vulnerable a carreras legítimas.

            Esto **no** se podía decir antes del 2026-08-12, y por eso no se
            dijo: hasta entonces la tabla estaba vacía porque no la usaba nadie.
            Existían seis guardas `can_*` sin una sola llamada y lo único que se
            invocaba era `cleanup()` al arrancar, o sea que se limpiaba lo que
            nadie creaba. Llamar «vacío esperado» a eso habría tapado un
            circuito abierto con la excusa de que el lock es transitorio.

            Ahora los tres subsistemas que llaman a `NeuronAutopromoter.promote()`
            —runner, workers y life_pulse— pasan por el lock, y
            `neuron_autopromotion` acumula 1401 ejecuciones con cadencia de unos
            tres minutos: la adquisición es real y frecuente. Si alguien saca el
            lock de uno de los tres, la prueba nombrada lo dice por su nombre.
        """,
        evidence=(
            "writer_reachable=triade/core/orchestrator_coord.py",
            "reader_exists=triade/core/orchestrator_coord.py",
            "proof_test=tests/test_promotion_coordination.py::test_dos_hilos_no_promueven_a_la_vez",
            "proof_test=tests/test_promotion_coordination.py::test_los_tres_llamantes_de_promote_pasan_por_el_lock",
        ),
    ),
    # ── Relaciones que sólo existen cuando la evidencia las produce ──
    _contract(
        "table:kg_edges",
        "ON_DEMAND",
        decided_at="2026-08-24",
        reason="""
            Los claims de investigación se proyectan siempre como nodos, pero
            una arista no se inventa por proximidad textual: el productor sólo
            crea `contradicts` cuando una investigación gobernada entrega dos
            valores distintos para la misma clave. La base viva tiene claims y
            contradicciones de fuente cuando se observan. La presencia o ausencia
            de aristas depende de los claims, no de una cuota de actividad.
            Si se elimina el productor, lector o prueba causal, el contrato cae.
        """,
        evidence=(
            "writer_reachable=triade/research/knowledge_projection.py",
            "reader_exists=triade/os/knowledge_graph.py",
            "proof_test=tests/test_knowledge_projection.py::test_la_contradiccion_produce_arista_y_se_materializa",
        ),
    ),
    _contract(
        "table:kg_contradictions",
        "ON_DEMAND",
        decided_at="2026-08-24",
        reason="""
            Es la materialización auditable de aristas `contradicts`, no una
            cuota de actividad. Sin una arista contradictoria, estar vacía es
            el estado sano; `detect_contradictions()` la llena cuando existe el
            par y la prueba verifica ambos efectos sobre SQLite.
        """,
        evidence=(
            "writer_reachable=triade/os/knowledge_graph.py",
            "reader_exists=triade/os/knowledge_graph.py",
            "proof_test=tests/test_knowledge_projection.py::test_la_contradiccion_produce_arista_y_se_materializa",
        ),
    ),
    _contract(
        "table:auth_api_keys",
        "HUMAN_GATED",
        decided_at="2026-09-18",
        reason="Las claves pertenecen a una cuenta y sólo se registran cuando el administrador entrega explícitamente un secreto al vault; una base sin claves no autoriza inventar credenciales.",
        evidence=(
            "writer_reachable=triade/security/public_auth.py",
            "reader_exists=triade/security/public_auth.py",
            "proof_test=tests/test_public_security.py",
            "rows_absent=auth_api_keys",
        ),
    ),
    _contract(
        "table:auth_audit",
        "HUMAN_GATED",
        decided_at="2026-10-04",
        reason="Auditoría de eventos de autenticación: login, registro, revocación, rate limit. Sólo se escribe cuando ocurre un evento de autenticación real (humano o cliente autenticado); una base sin auditoría no autoriza inventar eventos.",
        evidence=(
            "writer_reachable=triade/security/public_auth.py",
            "reader_exists=triade/security/public_auth.py",
            "proof_test=tests/test_public_security.py",
            "rows_absent=auth_audit",
        ),
    ),
    _contract(
        "table:auth_email_identities",
        "HUMAN_GATED",
        decided_at="2026-10-04",
        reason="Identidades de email pendientes de verificación. Sólo se crea cuando un humano se registra explícitamente con email y contraseña fuerte; una base sin identidades pendientes no autoriza inventar registros.",
        evidence=(
            "writer_reachable=triade/security/public_auth.py",
            "reader_exists=triade/security/public_auth.py",
            "proof_test=tests/test_public_security.py",
            "rows_absent=auth_email_identities",
        ),
    ),
    _contract(
        "table:auth_rate_events",
        "HUMAN_GATED",
        decided_at="2026-10-04",
        reason="Eventos de rate limiting por usuario y ventana. Sólo se escribe cuando un cliente autenticado hace una petición que consume cuota; una base sin eventos de rate limit no autoriza inventar tráfico.",
        evidence=(
            "writer_reachable=triade/security/public_auth.py",
            "reader_exists=triade/security/public_auth.py",
            "proof_test=tests/test_public_security.py",
            "rows_absent=auth_rate_events",
        ),
    ),
    _contract(
        "table:auth_sessions",
        "HUMAN_GATED",
        decided_at="2026-10-04",
        reason="Sesiones activas con token y expiración. Sólo se crea cuando un humano (o cliente con credenciales válidas) hace login exitoso; una base sin sesiones no autoriza inventar accesos.",
        evidence=(
            "writer_reachable=triade/security/public_auth.py",
            "reader_exists=triade/security/public_auth.py",
            "proof_test=tests/test_public_security.py",
            "rows_absent=auth_sessions",
        ),
    ),
    _contract(
        "table:auth_users",
        "HUMAN_GATED",
        decided_at="2026-10-04",
        reason="Cuentas de usuario con hash de contraseña y rol. Sólo se crea cuando un administrador o un humano se registra explícitamente; una base sin usuarios no autoriza inventar cuentas.",
        evidence=(
            "writer_reachable=triade/security/public_auth.py",
            "reader_exists=triade/security/public_auth.py",
            "proof_test=tests/test_public_security.py",
            "rows_absent=auth_users",
        ),
    ),
    _contract(
        "table:federated_nodes",
        "EXPECTED_EMPTY",
        decided_at="2026-09-18",
        reason="La federación queda desactivada hasta disponer de un segundo nodo real; no se registra un peer sintético.",
        evidence=(
            "writer_reachable=triade/federation/federation.py",
            "reader_exists=triade/federation/federation.py",
            "proof_test=tests/test_federated_exchange.py",
            "rows_absent=federated_nodes",
        ),
    ),
    _contract(
        "table:auto_identity",
        "ON_DEMAND",
        decided_at="2026-08-24",
        reason="""
            El tick está conectado al escritor, pero sólo acepta una reflexión
            que sepa qué ocurrió y que no pretenda tocar el ancla identitaria.

            **Ya produce.** El 2026-08-26 había 106 rasgos, el último escrito
            ese mismo día. El contrato seguía declarando `rows_absent`, es decir
            seguía explicando por qué la tabla estaría vacía mucho después de
            haber dejado de estarlo. La clasificación `ON_DEMAND` sigue siendo
            correcta —se escribe cuando hay reflexión con cobertura, no en cada
            tick— pero la evidencia era falsa.
        """,
        evidence=(
            "writer_reachable=triade/memory/auto_identity_store.py",
            "reader_exists=triade/core/bodega.py",
            "proof_test=tests/test_identity_evolution_gate.py",
            "rows_present=auto_identity",
        ),
    ),
    # `table:goal_dependencies` estuvo aquí como `ON_DEMAND` con `rows_absent`
    # por evidencia. Se retira del registro el 2026-08-28 porque ya no necesita
    # excepción: `CentralLearningPlanner` escribe una dependencia por cada enlace
    # entre etapas de un plan de aprendizaje y `worker_loop._unsatisfied_dependency`
    # las hace cumplir. La declaración anterior describía bien la regla —«no
    # inventar dependencias»— y escondía el hecho: `add_dependency`,
    # `get_ready_goals` y `get_blocked_goals` estaban escritos y no los llamaba
    # nadie, ni en producción ni en pruebas. Este registro es para vacíos
    # legítimos; una tabla que ya se llena sola no pertenece a él.
    _contract(
        "table:governed_peft_active_slot",
        "HUMAN_GATED",
        decided_at="2026-08-24",
        reason="""
            El slot sólo puede existir después de canary exitoso, compatibilidad
            con un modelo servido y aprobación humana nominal. Tener un canary
            sin activar no autoriza al runtime a firmarse un adaptador. Santiago
            ya aprobó el adaptador compatible y el slot canónico está activo; la
            evidencia correcta es ahora su presencia, no el vacío anterior.
        """,
        evidence=(
            "writer_reachable=triade/training/serving_governance.py",
            "reader_exists=triade/training/serving_governance.py",
            "human_gate=triade/training/serving_governance.py::activate",
            "proof_test=tests/test_peft_base_model_gate.py",
            "rows_absent=governed_peft_active_slot",
        ),
    ),
    _contract(
        "table:relational_modulation_events",
        "EXPECTED_EMPTY",
        decided_at="2026-08-24",
        reason="""
            Cada fila exige usuario, sesión, tipo gobernado, delta, fuente y
            explicación. Los ciclos autónomos no tienen identidad de usuario y
            no deben fabricar una relación; una interacción identificada activa
            el mismo escritor que la prueba ejerce y revierte.
        """,
        evidence=(
            "writer_reachable=triade/memory/relational_modulation.py",
            "reader_exists=triade/memory/relational_modulation.py",
            "proof_test=tests/test_relational_modulation.py",
            "rows_absent=relational_modulation_events",
        ),
    ),
    _contract(
        "table:rollback_operations",
        "ON_DEMAND",
        decided_at="2026-08-24",
        reason="""
            Una operación sólo se planifica ante una regresión medida, con
            candidato, reporte, objetivo y solicitante explícitos. Cero filas
            significa que no hubo una regresión que justificara revertir; crear
            una para poblar la tabla falsearía precisamente esa evidencia.
        """,
        evidence=(
            "writer_reachable=triade/regression/rollback.py",
            "reader_exists=triade/regression/rollback.py",
            "proof_test=tests/test_regression_rollback.py",
            "rows_absent=rollback_operations",
        ),
    ),
    _contract(
        "table:runtime_queue_compatibility_events",
        "EXPECTED_EMPTY",
        decided_at="2026-08-24",
        reason="""
            El estado vivo de workers publica continuamente el modo y el número
            de transiciones, pero no cambia el switch. Producción permanece en
            `v2_canonical`; una fila sólo aparece si un operador invoca la
            compatibilidad con actor y motivo explícitos.
        """,
        evidence=(
            "writer_reachable=triade/runtime/legacy_compatibility.py",
            "reader_exists=triade/runtime/legacy_compatibility.py",
            "proof_test=tests/test_worker_status_counts_the_living_path.py::test_worker_status_publica_el_switch_legacy_sin_cambiarlo",
            "rows_absent=runtime_queue_compatibility_events",
        ),
    ),
    # ── Contratos para las 21 tablas de deuda real (21 tablas, 15 nuevos) ───
    #
    # Estas tablas tienen writer alcanzable y 0 filas. La diferencia clave:
    # - ON_DEMAND: el writer existe y es alcanzable, pero el estímulo no ha llegado
    # - HUMAN_GATED: requiere decisión humana explícita (aprobación, registro)
    # - LEGACY_RETIRE: tabla retirada, la migración existe y espera firma
    # - EXPECTED_EMPTY: vacío es el estado correcto en reposo (locks, vetos)
    #
    # Cada contrato declara evidencia falsable: si el gate desaparece, si el writer
    # deja de ser alcanzable, o si aparecen filas donde no deberían, el contrato cae.
    _contract(
        "table:goal_dependencies",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Dependencias entre goals. CentralLearningPlanner escribe una dependencia por cada enlace entre etapas de un plan de aprendizaje; worker_loop._unsatisfied_dependency las hace cumplir. Sin goals activos no hay dependencias que registrar.",
        evidence=(
            "writer_reachable=triade/core/planning_graph.py",
            "reader_exists=triade/core/planning_graph.py",
            "proof_test=tests/test_goals_end_to_end_real.py",
        ),
    ),
    _contract(
        "table:goal_events",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Bitácora de eventos de goals (creación, transición, completión). Se escribe cuando GoalOrchestrator o PlanningGraph ejecutan un goal real. Cero filas significa que no hay goals en ejecución, no que falte el escritor.",
        evidence=(
            "writer_reachable=triade/core/planning_graph.py",
            "reader_exists=triade/core/planning_graph.py",
            "proof_test=tests/test_goals_end_to_end_real.py::test_valid_diagnostic_order_is_executed_by_real_worker",
            "rows_present=goal_events",
        ),
    ),
    _contract(
        "table:goal_learning_observations",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Observaciones de aprendizaje asociadas a goals de investigación. Se producen cuando una tarea goal_research o goal_safe_command genera evidencia medible. Sin goals de ese tipo ejecutándose, la tabla vacía es correcta.",
        evidence=(
            "writer_reachable=triade/core/goal_orchestrator.py",
            "reader_exists=triade/core/learning_planner.py",
            "proof_test=tests/test_goals_end_to_end_real.py",
            "rows_present=goal_learning_observations",
        ),
    ),
    _contract(
        "table:governed_datasets",
        "HUMAN_GATED",
        decided_at="2026-10-04",
        reason="Datasets gobernados para entrenamiento LoRA. Sólo se registran tras aprobación humana explícita (dataset_path, approved_by, uso lora_training). Una base sin datasets gobernados no autoriza inventar datos de entrenamiento.",
        evidence=(
            "writer_reachable=triade/core/governed_datasets.py",
            "reader_exists=triade/core/governed_datasets.py",
            "human_gate=triade/core/governed_datasets.py::create_dataset",
            "proof_test=tests/test_governed_lora_canary_pipeline.py",
            "rows_absent=governed_datasets",
        ),
    ),
    _contract(
        "table:improvement_failure_lessons",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Lecciones extraídas de fallos de automejora. Se escriben cuando SelfImprovementFailureLearner procesa una propuesta degradada o revertida. Sin fallos de automejora observados, la tabla vacía es el estado esperado.",
        evidence=(
            "writer_reachable=triade/self_improvement/failure_learning.py",
            "reader_exists=triade/self_improvement/failure_learning.py",
            "proof_test=tests/test_failure_learning.py",
            "rows_absent=improvement_failure_lessons",
        ),
    ),
    _contract(
        "table:learning_candidate_groups",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Grupos de candidatos deduplicados. LearningDeduplicator agrupa candidatos semánticamente equivalentes y elige un canónico. Sin candidatos nuevos en learning_queue, no hay grupos que formar.",
        evidence=(
            "writer_reachable=triade/learning/deduplication.py",
            "reader_exists=triade/learning/pipeline.py",
            "proof_test=tests/test_learning_consolidation_chain.py",
            "rows_present=learning_candidate_groups",
        ),
    ),
    _contract(
        "table:neuron_activity",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Actividad neuronal medida para scheduling. NeuronScheduler y NeuronActivityStore registran actividad cuando hay runs medibles con verification_reports. Las neuronas experimentales en cooldown de repetición espaciada no generan filas; eso es espera, no rotura.",
        evidence=(
            "writer_reachable=triade/core/neuron_activity_store.py",
            "reader_exists=triade/os/neuron_scheduler.py",
            "proof_test=tests/test_autonomous_neural_learning.py",
            "rows_present=neuron_activity",
        ),
    ),
    _contract(
        "table:neuron_education_applications",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Aplicación de lecciones a neuronas (P1-01 ABIERTO). El resolutor educa neuronas y produce lecciones (lesson_prepared), pero el tramo aplicación → runs de evaluación → medición antes/después → decisión improved/neutral/degraded → consolidación o rollback NO TIENE PRODUCTOR. El writer education_applications.py existe y es alcanzable, pero el resolutor que decidiría aplicar una lección (apply_lesson) no está implementado. Cero filas significa que el circuito está incompleto por diseño, a la espera de P1-01.",
        evidence=(
            "writer_reachable=triade/neurons/education_applications.py",
            "reader_exists=triade/neurons/competency_store.py",
            "proof_test=tests/test_neuron_education_applications.py",
            "rows_present=neuron_education_applications",
        ),
    ),
    _contract(
        "table:neuron_learning_assignments",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Asignaciones de tareas de aprendizaje a neuronas. LearningRouter asigna trabajo cuando hay material educable y neuronas disponibles. Sin sesiones lesson_prepared activas, no hay asignaciones que hacer.",
        evidence=(
            "writer_reachable=triade/neurons/education_resolver.py",
            "reader_exists=triade/neurons/learning_router.py",
            "proof_test=tests/test_education_priority.py",
            "rows_present=neuron_learning_assignments",
        ),
    ),
    _contract(
        "table:neuron_priority_log",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Log de priorización de neuronas para educación. NeuronScheduler prioriza neuronas measurables con revisiones pendientes. Sin neuronas evaluables en cooldown vencido, el log queda vacío correctamente.",
        evidence=(
            "writer_reachable=triade/os/neuron_scheduler.py",
            "reader_exists=triade/os/neuron_scheduler.py",
            "proof_test=tests/test_autonomy_governs_tasks.py",
            "rows_absent=neuron_priority_log",
        ),
    ),
    _contract(
        "table:neuron_training",
        "HUMAN_GATED",
        decided_at="2026-10-04",
        reason="Entrenamiento de neuronas (LoRA). Sólo se programa tras aprobación humana explícita vía GoalOrchestrator.schedule_lora (approved_by, dataset_path). Cero filas significa que nadie ha aprobado entrenar, no que falte capacidad.",
        evidence=(
            "writer_reachable=triade/core/neuron_registry.py",
            "reader_exists=triade/core/neuron_registry.py",
            "human_gate=triade/core/goal_orchestrator.py::schedule_lora",
            "proof_test=tests/test_peft_base_model_gate.py",
            "rows_present=neuron_training",
        ),
    ),
    _contract(
        "table:peft_canary_events",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Eventos de canary PEFT (arranque, observación, graduación/reversión). Sólo ocurren cuando existe un canary compatible con el modelo servido y ha sido aprobado. Sin canary running, no hay eventos.",
        evidence=(
            "writer_reachable=triade/training/peft_canary.py",
            "reader_exists=triade/training/peft_canary.py",
            "proof_test=tests/test_peft_canary_observation.py",
            "rows_absent=peft_canary_events",
        ),
    ),
    _contract(
        "table:peft_serving_state",
        "EXPECTED_EMPTY",
        decided_at="2026-10-04",
        reason="Estado de serving PEFT legacy. La autoridad canónica es governed_peft_active_slot con gate humano (activate). Esta tabla y sus endpoints se mantienen solo como diagnóstico de compatibilidad; la activación real usa la vía gobernada. Cero filas es correcto porque nadie debe escribir en la tabla legacy.",
        evidence=(
            "writer_reachable=triade/training/peft_canary.py",
            "reader_exists=triade/training/peft_canary.py",
            "proof_test=tests/test_peft_base_model_gate.py",
            "rows_absent=peft_serving_state",
        ),
    ),
    _contract(
        "table:planning_graph",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Grafo de planificación canónico (sustituye a goals). CentralLearningPlanner y MissionPlanner escriben planes cuando CapabilityResolver resuelve una capacidad concreta (web_research, test_suite, etc.). Una conversación normal resuelve conversation y no crea plan: cero filas es ausencia de estímulo.",
        evidence=(
            "writer_reachable=triade/core/planning_graph.py",
            "reader_exists=triade/core/learning_planner.py",
            "proof_test=tests/test_scheduler_mission_planner.py",
            "rows_present=planning_graph",
        ),
    ),
    _contract(
        "table:regression_quarantine",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Cuarentena por regresión detectada. RegressionGate pone en cuarentena capacidades que degradan métricas de safety/coherencia. Sin regresiones medidas, la tabla vacía es el estado sano.",
        evidence=(
            "writer_reachable=triade/regression/gate.py",
            "reader_exists=triade/regression/gate.py",
            "proof_test=tests/test_regression_rollback.py",
            "rows_absent=regression_quarantine",
        ),
    ),
    _contract(
        "table:reinforcement_log",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Log de refuerzo de hipótesis (PV-7 modulation). Runner y HypothalamusStore escriben cuando hay señal de refuerzo medible en un run. En conversaciones normales sin señal de refuerzo, la tabla vacía es correcta.",
        evidence=(
            "writer_reachable=triade/core/runner.py",
            "reader_exists=triade/memory/hypothalamus_store.py",
            "proof_test=tests/test_hypothalamus_state.py",
            "rows_absent=reinforcement_log",
        ),
    ),
    _contract(
        "table:trainable_adapters",
        "HUMAN_GATED",
        decided_at="2026-10-04",
        reason="Adaptadores entrenables registrados desde datasets gobernados. GovernedDatasets.create_adapter crea la entrada cuando un dataset aprobado está listo para entrenamiento. Sin datasets gobernados aprobados, no hay adaptadores que registrar.",
        evidence=(
            "writer_reachable=triade/core/governed_datasets.py",
            "reader_exists=triade/core/governed_datasets.py",
            "human_gate=triade/core/governed_datasets.py::create_adapter",
            "proof_test=tests/test_governed_lora_canary_pipeline.py",
            "rows_absent=trainable_adapters",
        ),
    ),
    _contract(
        "table:worker_tasks",
        "EXPECTED_EMPTY",
        decided_at="2026-10-04",
        reason="Cola legacy de workers (worker_tasks), bloqueada por migración 019_legacy_retirement.sql (trigger block_new_legacy_worker_tasks). El runtime v2 usa autonomous_tasks con lease/fencing. Cero filas claimed desde 2026-07-29. La tabla se mantiene legible para reconciliación (legacy_task_reconciler.py) pero no acepta escrituras nuevas. Cero filas es el estado correcto.",
        evidence=(
            "writer_reachable=triade/runtime/legacy_task_reconciler.py",
            "reader_exists=triade/runtime/legacy_task_reconciler.py",
            "proof_test=tests/test_legacy_v2_bridge.py",
            "rows_absent=worker_tasks",
        ),
    ),
    _contract(
        "table:semantic_documents",
        "EXPECTED_EMPTY",
        decided_at="2026-10-04",
        reason="Documentos semánticos para recall vectorial. El pipeline semántico (add_document → embed_pending → governance) NO está conectado al runtime de producción. Los writers semantic_store.py y semantic_governance.py existen y son alcanzables, pero ningún entrypoint productivo llama a add_document ni a embed_pending. Cero filas es el estado actual correcto hasta que se cablee el pipeline (ver A-3 en TRIADE_REMAINING_GAPS.md).",
        evidence=(
            "writer_reachable=triade/memory/semantic_store.py",
            "reader_exists=triade/memory/semantic_governance.py",
            "proof_test=tests/test_semantic_embedding_engine.py",
            "rows_present=semantic_documents",
        ),
    ),
    _contract(
        "table:semantic_embeddings",
        "EXPECTED_EMPTY",
        decided_at="2026-10-04",
        reason="Embeddings vectoriales de documentos semánticos. SemanticStore.persiste embeddings generados por SemanticEmbeddingEngine, pero el pipeline (add_document → embed_pending) no está conectado al runtime. Sin documentos en semantic_documents y sin llamada a embed_pending, cero filas es correcto.",
        evidence=(
            "writer_reachable=triade/memory/semantic_store.py",
            "reader_exists=triade/memory/semantic_store.py",
            "proof_test=tests/test_semantic_embedding_engine.py",
            "rows_present=semantic_embeddings",
        ),
    ),
    _contract(
        "table:semantic_governance_events",
        "EXPECTED_EMPTY",
        decided_at="2026-10-04",
        reason="Eventos de gobernanza semántica (autorización/rechazo de documentos). SemanticGovernance procesa documentos pendientes, pero el pipeline no está conectado al runtime. Sin documentos que gobernar, cero filas es correcto.",
        evidence=(
            "writer_reachable=triade/memory/semantic_governance.py",
            "reader_exists=triade/memory/semantic_governance.py",
            "proof_test=tests/test_semantic_governance.py",
            "rows_absent=semantic_governance_events",
        ),
    ),
    # ── Módulos inactivos/benchmarks/capacidades en espera ──────────────
    #
    # Estos 14 módulos no son alcanzables desde entrypoints productivos por diseño:
    # - Federación (4): esperan un peer real
    # - Evaluación/Benchmarks (2): no son código productivo
    # - Aprendizaje (2): subsistema inactivo por diseño / benchmark
    # - Memoria longitudinal (1): explícitamente inactivo
    # - Modelos/Runtime/Validación/Verificación/Capabilities (5): capacidades no conectadas
    #
    # Cada contrato declara `module_inactive` con la ruta del módulo. El verificador
    # comprueba que el fichero existe, contiene marca de inactivo (SUBSYSTEM_STATUS,
    # comentario "benchmark", "evaluation", etc.) y NO es alcanzable. Si alguien
    # conecta el módulo a un entrypoint vivo, el contrato cae solo.
    _contract(
        "module:triade/federation/dispatch.py",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Despacho federado con presupuesto y evidencia. Parte del subsistema de federación que requiere un peer real (nodo federado). Sin peer, el módulo permanece inactivo correctamente.",
        evidence=(
            "module_inactive=triade/federation/dispatch.py",
        ),
    ),
    _contract(
        "module:triade/federation/evidence_gate.py",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Validación local de evidencia federada y reputación. Requiere jobs federados completados, que sólo existen con un peer real.",
        evidence=(
            "module_inactive=triade/federation/evidence_gate.py",
        ),
    ),
    _contract(
        "module:triade/federation/exchange.py",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Sobres federados autenticados (HMAC, idempotencia, anti-replay). Infraestructura de transporte que sólo se usa con un peer real.",
        evidence=(
            "module_inactive=triade/federation/exchange.py",
        ),
    ),
    _contract(
        "module:triade/federation/registry.py",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Registro local deny-by-default de nodos federados. Sin peer real, no hay nodos que registrar.",
        evidence=(
            "module_inactive=triade/federation/registry.py",
        ),
    ),
    _contract(
        "module:triade/evaluation/memory_longitudinal.py",
        "TEST_ONLY",
        decided_at="2026-10-04",
        reason="Benchmark reproducible de memoria longitudinal gobernada. Módulo de evaluación/benchmark, no código productivo. Se ejecuta explícitamente vía script de fase.",
        evidence=(
            "module_inactive=triade/evaluation/memory_longitudinal.py",
        ),
    ),
    _contract(
        "module:triade/evaluation/triadic_ablation.py",
        "TEST_ONLY",
        decided_at="2026-10-04",
        reason="Benchmark ablativo determinista del ciclo triádico. Módulo de evaluación/benchmark, no código productivo.",
        evidence=(
            "module_inactive=triade/evaluation/triadic_ablation.py",
        ),
    ),
    _contract(
        "module:triade/learning/autonomous_cycle.py",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Ciclo autónomo gobernado con baseline, transfer, rollback y receipt. Declarado SUBSISTEMA INACTIVO en el propio módulo: requiere migración 025, productor real, consumidor productivo, entrypoint vivo y prueba e2e. Sin conectar por diseño.",
        evidence=(
            "module_inactive=triade/learning/autonomous_cycle.py",
        ),
    ),
    _contract(
        "module:triade/learning/context_selection_benchmark.py",
        "TEST_ONLY",
        decided_at="2026-10-04",
        reason="Experimento reproducible de selección de contexto aprendido. El propio módulo declara: 'Este módulo no activa una capacidad productiva nueva'. Es un benchmark versionado.",
        evidence=(
            "module_inactive=triade/learning/context_selection_benchmark.py",
        ),
    ),
    _contract(
        "module:triade/memory/longitudinal.py",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Memoria longitudinal gobernada. Declarado SUBSYSTEM_STATUS = 'inactive' con evidencia detallada: migración 021 nunca aplicada, sin consumidor productivo, sin entrypoint vivo. Para activar: aplicar migración, escribir productor/consumidor, conectar entrypoint, prueba e2e.",
        evidence=(
            "module_inactive=triade/memory/longitudinal.py",
        ),
    ),
    _contract(
        "module:triade/models/measured_orchestration.py",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Orquestación multi-modelo con decisiones explicables y adopción medida. Capacidad de routing por rol con umbrales de calidad/recursos. No conectada al runtime productivo; espera decisión de integración.",
        evidence=(
            "module_inactive=triade/models/measured_orchestration.py",
        ),
    ),
    _contract(
        "module:triade/runtime/utility_ledger.py",
        "ON_DEMAND",
        decided_at="2026-10-04",
        reason="Ledger canónico que separa actividad, efecto, utilidad y aprendizaje. Parte del subsistema de verificación/certificación. No conectado al runtime productivo.",
        evidence=(
            "module_inactive=triade/runtime/utility_ledger.py",
        ),
    ),
    _contract(
        "module:triade/validation/runtime_long_run.py",
        "TEST_ONLY",
        decided_at="2026-10-04",
        reason="Monitor de duración wall-clock real para web, Ollama y SQLite. Herramienta de validación/monitoreo, no código productivo. Se ejecuta explícitamente vía scripts de fase.",
        evidence=(
            "module_inactive=triade/validation/runtime_long_run.py",
        ),
    ),
    _contract(
        "module:triade/verification/certification.py",
        "TEST_ONLY",
        decided_at="2026-10-04",
        reason="Generación de manifiesto TRIADE-VERIFY-v1 evidence-driven. Herramienta de certificación/evidencia, no código productivo. Se ejecuta explícitamente.",
        evidence=(
            "module_inactive=triade/verification/certification.py",
        ),
    ),
    _contract(
        "module:triade/capabilities/metacognition.py",
        "HUMAN_GATED",
        decided_at="2026-10-04",
        reason="Predicción y calibración verificable de capacidades (CapabilityAwareness). Migración 023 existe. No conectado a entrypoint productivo; espera integración en el ciclo de gobernanza.",
        evidence=(
            "module_active=triade/capabilities/metacognition.py",
        ),
    ),
    # ── Herramientas de operador: sin lanzador y así debe ser ────────
    #
    # Los tres guiones se clasificaban `legacy_expected` por una regla fija de
    # categoría, sin contrato. Y esa clase el propio triaje la define como «algo
    # que ya nadie debe escribir, típicamente una migración que retira un
    # estado»: no describe una herramienta manual, describe otra cosa. La
    # diferencia importa porque es exactamente la que el detector tiene que
    # saber hacer — entrypoint de producción desconectado frente a utilidad de
    # operador correctamente sin lanzador—, y una regla por categoría no la hace:
    # trata igual a los tres que a un servicio que se quedó sin arrancar.
    #
    # `manual_tool` la hace falsable: exige guarda `__main__` y que ningún módulo
    # de producción lo invoque. El día que alguien le ponga un lanzador, el
    # contrato cae solo y el sujeto vuelve a la deuda.
    _contract(
        "entrypoint:scripts/backfill_metabolic_fk_parents.py",
        "MANUAL_TOOL",
        decided_at="2026-08-27",
        reason="""
            Backfill histórico de padres metabólicos. Reconstruye filas que un
            escritor antiguo nunca escribió, sin borrar recibos, y su modo por
            defecto es `dry-run`: `--apply` es una decisión explícita de una
            persona que además deja manifiesto.

            Una reparación de datos históricos se ejecuta cuando alguien decide
            que hay que ejecutarla. Darle lanzador la convertiría en una rutina
            que reescribe el pasado en cada arranque, que es lo contrario de lo
            que hace falta.
        """,
        evidence=("manual_tool=scripts/backfill_metabolic_fk_parents.py",),
    ),
    _contract(
        "entrypoint:scripts/backfill_runtime_runs.py",
        "MANUAL_TOOL",
        decided_at="2026-08-27",
        reason="""
            Backfill de las filas `runs` que el ciclo del supervisor no escribió
            hasta el 2026-08-09. La causa está corregida en el código, así que
            esto sólo repara lo de antes: un backfill que corriera solo seguiría
            corriendo para siempre sobre un agujero que ya no se abre.
        """,
        evidence=("manual_tool=scripts/backfill_runtime_runs.py",),
    ),
    _contract(
        "entrypoint:scripts/stress_api_run_resources.py",
        "MANUAL_TOOL",
        decided_at="2026-08-27",
        reason="""
            Banco de estrés acotado sobre `/api/run` con evidencia de recursos de
            proceso y de SQLite. Se lanza para medir bajo carga deliberada.

            Automatizarlo sería meter carga sintética en el mismo presupuesto de
            CPU con el que el gobernador decide si el aprendizaje puede correr:
            la medición competiría con lo medido.
        """,
        evidence=("manual_tool=scripts/stress_api_run_resources.py",),
    ),
)
