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
    si algo falla    → vuelve a DEUDA_REAL, diciendo qué evidencia se cayó

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

#: Las únicas clasificaciones que un contrato puede reclamar. `DEUDA_REAL` no
#: está: no se declara, es lo que queda cuando ninguna otra se sostiene.
CLASSIFICATIONS = (
    "HUMAN_GATED",
    "ON_DEMAND",
    "NO_EXTERNAL_STIMULUS",
    "EXPECTED_EMPTY",
    "AUDIT_LEDGER",
    "HISTORICAL",
    "EXPERIMENTAL",
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
)

#: Evidencia que sólo tiene respuesta **sobre la base viva**. En CI no hay base
#: —ni debe haberla: una CI que dependiera de la memoria de producción mediría
#: otra cosa cada día— así que allí no se puede afirmar ni negar.
#:
#: La consecuencia hay que decirla en voz alta: un contrato que mintiera sobre
#: filas pasaría CI. Lo caza el detector, que reverifica **todo** en cada
#: medición sobre la base real y devuelve el sujeto a `DEUDA_REAL` si falla. CI
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
            "classification": self.classification if self.holds else "DEUDA_REAL",
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
            filas = self._rows(valor or tabla)
            return filas == 0

        if kind == "empty_source_table":
            # «No ha pasado porque no hay con quién»: el estímulo externo se
            # mide, no se supone. Si aparece un peer, el contrato se cae solo.
            filas = self._rows(valor)
            return filas == 0

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
# habría, el sujeto **vuelve solo a DEUDA_REAL** diciendo qué evidencia se cayó.
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
        "table:hardware_senses",
        "AUDIT_LEDGER",
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
        "AUDIT_LEDGER",
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
        "table:engineering_evolution_events",
        "AUDIT_LEDGER",
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
            "rows_present=engineering_evolution_events",
        ),
    ),
    # ── Historia de algo que ya terminó ──────────────────────────────
    #
    # Distinta de una bitácora viva: aquí el escritor ya no existe, y esa
    # ausencia es la prueba de que se retiró a propósito y no se perdió por el
    # camino. Las filas se conservan porque documentan un cambio real de estado.
    _contract(
        "table:evidence_remediation_audit",
        "HISTORICAL",
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
            "rows_present=evidence_remediation_audit",
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
        decided_at="2026-08-08",
        reason="""
            `MissionPlanner._plan_self_improvement` sólo encola si hay propuestas
            ya `approved`, y nunca crea ni aprueba ninguna —lo dice su docstring:
            así el bucle no gira en vacío ni se auto-alimenta—. Aprobar exige
            `bridge.approve(proposal_id, *, approved_by)`, que lanza si la firma
            viene vacía. El handler lo dice en su
            propio docstring: un humano decide qué dirección se intenta, la
            máquina hace la verificación rigurosa. Cero ejecuciones significa que
            nadie ha propuesto todavía una mejora.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/workers/mission_planner.py",
            "effect_consumer=triade/workers/worker_loop.py::_self_improvement_evaluation",
            "rows_absent=improvement_proposals",
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
        "NO_EXTERNAL_STIMULUS",
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
            petición. Eso ya se corrigió —ahora exige verbo de redacción y
            sustantivo de entregable, que es más estricto que la compuerta
            general, no más laxo—. Queda a la espera de que alguien pida por
            escrito un entregable de texto: estímulo conversacional, no gate.
        """,
        evidence=(
            "writer_reachable=triade/core/capability_resolver.py",
            "effect_consumer=triade/workers/worker_loop.py::_write_governed_text_artifact",
        ),
    ),
    # ── Automejora: una cadena entera colgando de una firma ──────────
    #
    # Las seis cuelgan del mismo punto y por diseño: una propuesta que un humano
    # aprueba. `bridge.approve()` lanza si la firma viene vacía y
    # `create_candidate` exige que la propuesta esté ya `approved`. La separación
    # es deliberada —el humano elige qué se intenta, la máquina hace la
    # verificación rigurosa— y ahora, además, es **ejercitable**: las rutas
    # `/api/governance/improvement/{signals,proposals,proposals/{id}/approve}`
    # existen y están probadas de punta a punta.
    #
    # Cero filas significa, literalmente, que nadie ha propuesto todavía una
    # mejora. La evidencia `rows_absent` es la que hace que esto caduque solo: en
    # cuanto alguien ejerza el gate, el contrato deja de sostenerse y hay que
    # volver a mirar la tabla con datos delante.
    _contract(
        "table:improvement_signals",
        "HUMAN_GATED",
        decided_at="2026-08-08",
        reason="""
            Primer eslabón: una capacidad que rinde por debajo de su objetivo. Se registra por `POST /api/governance/improvement/signals`, con llave. Sin señal no hay propuesta, y sin propuesta no hay nada más abajo.
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
            La dirección que se propone intentar. Es el punto exacto donde entra la firma humana: `approve()` lanza si `approved_by` viene vacío.
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
            El rastro de cada transición de una propuesta. Vacía porque no hay propuestas, no porque no se escriba.
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
            Une la propuesta aprobada con el candidato que la implementa. `create_candidate` exige que la propuesta esté ya `approved`: un eslabón por debajo de la firma.
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
            Un canario nace de un candidato, que nace de una propuesta aprobada a mano. Dos eslabones por debajo de la firma.
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
            Las observaciones que deciden si el canario gradúa o revierte. Tres eslabones por debajo de la firma; no puede haber ninguna mientras no haya canario.
        """,
        evidence=(
            "human_gate=triade/self_improvement/bridge.py::approve",
            "writer_reachable=triade/self_improvement/canary.py",
            "reader_exists=triade/self_improvement/canary.py",
            "proof_test=tests/test_self_improvement_door.py",
            "rows_absent=improvement_canary_observations",
        ),
    ),
)
