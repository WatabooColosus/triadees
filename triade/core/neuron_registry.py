"""Registro persistente de neuronas · Tríade Ω 1.2C.

Usa las tablas existentes `neurons` y `neuron_training` para convertir
NeuronSpec y NeuronTrainingResult en estado persistente SQLite.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .neuron_creator import NeuronSpec
from .neuron_trainer import NeuronTrainingResult

# ── Propiedad de campos ───────────────────────────────────────────────────
# Quién manda sobre cada columna cuando se vuelve a registrar una neurona que
# ya existe. Documentado en docs/NEURON_FIELD_OWNERSHIP.md.
DECLARATIVE = "declarative"  # el spec es la fuente de verdad, siempre manda
PRESERVE_IF_SILENT = "preserve_if_silent"  # si el spec no declara nada, se conserva
NEVER_REDUCE = "never_reduce"  # unión: se añaden restricciones, nunca se quitan
KEEP_ORIGIN = "keep_origin"  # procedencia: inmutable tras la creación
NO_DOWNGRADE = "no_downgrade"  # un re-registro no puede bajar el estado

_FIELD_POLICY: dict[str, str] = {
    "mission": DECLARATIVE,
    "domain": DECLARATIVE,
    "rules": PRESERVE_IF_SILENT,
    "triggers": PRESERVE_IF_SILENT,
    "inputs_allowed": PRESERVE_IF_SILENT,
    "outputs_allowed": PRESERVE_IF_SILENT,
    "forbidden_actions": NEVER_REDUCE,
    "success_metrics": PRESERVE_IF_SILENT,
    "evidence_required": NEVER_REDUCE,
    "activation_policy": PRESERVE_IF_SILENT,
    "contract_json": PRESERVE_IF_SILENT,
    "status": NO_DOWNGRADE,
    "created_by": KEEP_ORIGIN,
}

# Orden de estados. Un re-registro sólo puede mantener o subir; bajar exige la
# ruta gobernada `update_status()`.
_STATUS_RANK: dict[str, int] = {
    "rejected": 0,
    "quarantined": 5,
    "candidate_detected": 10,
    "candidate": 15,
    "candidate_reviewable": 20,
    "needs_changes": 25,
    "experimental": 30,
    "trusted_worker": 40,
    "active_assistant": 45,
    "stable": 50,
}
_DEFAULT_STATUS_RANK = 10

CONFLICT_POLICIES = ("preserve_learned", "create_only", "replace_definition")


def _status_rank_sql(column: str) -> str:
    """CASE que traduce un estado almacenado a su rango numérico."""
    branches = " ".join(
        f"WHEN {name!r} THEN {rank}" for name, rank in _STATUS_RANK.items()
    )
    return f"(CASE {column} {branches} ELSE {_DEFAULT_STATUS_RANK} END)"


def _union_sql(column: str) -> str:
    """Unión de dos arrays JSON: nunca pierde elementos existentes."""
    return (
        "(SELECT json_group_array(v) FROM ("
        f"SELECT value AS v FROM json_each(COALESCE(neurons.{column}, '[]')) "
        f"UNION SELECT value FROM json_each(COALESCE(excluded.{column}, '[]'))"
        "))"
    )


class NeuronRegistry:
    """Persistencia y consulta de neuronas internas."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path("triade/memory/schemas.sql")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.schema_path.exists():
            raise FileNotFoundError(
                f"No existe el esquema de memoria: {self.schema_path}"
            )
        with self._connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            self._migrate_neurons_table(conn)

    def _migrate_neurons_table(self, conn: sqlite3.Connection) -> None:
        """Agrega columnas modernas de contrato a bases existentes."""
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(neurons)").fetchall()
        }
        additions = {
            "triggers": "TEXT",
            "inputs_allowed": "TEXT",
            "outputs_allowed": "TEXT",
            "forbidden_actions": "TEXT",
            "success_metrics": "TEXT",
            "evidence_required": "TEXT",
            "activation_policy": "TEXT",
            "contract_json": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE neurons ADD COLUMN {name} {ddl}")

    @staticmethod
    def _unique_list(values: list[Any]) -> list[str]:
        """Deduplica listas preservando orden y eliminando vacíos."""
        seen: set[str] = set()
        out: list[str] = []
        for value in values or []:
            item = str(value).strip()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    _LIST_FIELDS = (
        "rules",
        "triggers",
        "inputs_allowed",
        "outputs_allowed",
        "forbidden_actions",
        "success_metrics",
        "evidence_required",
    )

    def _spec_values(
        self, spec: NeuronSpec, contract_payload: dict[str, Any] | None
    ) -> tuple[dict[str, Any], set[str]]:
        """Traduce el spec a columnas y marca cuáles vienen "en silencio".

        Un campo silencioso es aquel sobre el que el llamante no expresó
        ninguna opinión. No es una orden de borrado.
        """
        activation_policy = (contract_payload or {}).get("activation_policy") or {}
        contract_json = contract_payload or (
            spec.to_dict() if hasattr(spec, "to_dict") else {}
        )

        values: dict[str, Any] = {"name": spec.name}
        silent: set[str] = set()

        values["mission"] = spec.mission
        values["domain"] = spec.domain
        for field in self._LIST_FIELDS:
            items = self._unique_list(getattr(spec, field, []))
            values[field] = json.dumps(items, ensure_ascii=False)
            if not items:
                silent.add(field)

        values["activation_policy"] = json.dumps(activation_policy, ensure_ascii=False)
        if not activation_policy:
            silent.add("activation_policy")

        values["contract_json"] = json.dumps(contract_json, ensure_ascii=False)
        # `spec.to_dict()` nunca es vacío, así que el silencio de contract_json
        # no se puede deducir del valor: lo marca la ausencia del payload.
        if contract_payload is None:
            silent.add("contract_json")

        values["status"] = spec.status
        values["created_by"] = spec.created_by
        return values, silent

    def _conflict_clause(
        self, silent: set[str], explicit_fields: set[str], status: str
    ) -> tuple[str, list[Any]]:
        """Construye el ON CONFLICT según la política de propiedad de campos."""
        assignments: list[str] = []
        changed: list[str] = []
        params: list[Any] = []

        for column, policy in _FIELD_POLICY.items():
            if policy is KEEP_ORIGIN:
                continue
            if policy is NO_DOWNGRADE:
                rank = _STATUS_RANK.get(status, _DEFAULT_STATUS_RANK)
                expression = (
                    f"CASE WHEN ? >= {_status_rank_sql('neurons.status')} "
                    f"THEN excluded.{column} ELSE neurons.{column} END"
                )
                params.append(rank)
                # El mismo parámetro se repite en la condición de updated_at.
                changed.append(f"(neurons.{column} IS NOT ({expression}))")
                params.append(rank)
                assignments.append(f"{column} = {expression}")
                continue
            if policy in (PRESERVE_IF_SILENT, NEVER_REDUCE):
                if column in silent and column not in explicit_fields:
                    continue  # sin opinión: la columna ni se toca
                expression = (
                    _union_sql(column)
                    if policy is NEVER_REDUCE and column not in explicit_fields
                    else f"excluded.{column}"
                )
            else:  # DECLARATIVE
                expression = f"excluded.{column}"
            assignments.append(f"{column} = {expression}")
            changed.append(f"(neurons.{column} IS NOT ({expression}))")

        if not assignments:
            return "DO NOTHING", []

        # `updated_at` sólo se mueve si algo cambió de verdad.
        assignments.append(
            "updated_at = CASE WHEN "
            + " OR ".join(changed)
            + " THEN CURRENT_TIMESTAMP ELSE neurons.updated_at END"
        )
        return "DO UPDATE SET " + ", ".join(assignments), params

    def register(
        self,
        spec: NeuronSpec,
        contract_payload: dict[str, Any] | None = None,
        *,
        conflict_policy: str = "preserve_learned",
        explicit_fields: set[str] | None = None,
    ) -> int:
        """Crea una neurona, o la reconcilia si ya existe.

        contract_payload permite persistir contrato extendido de pipelines
        modernos sin exigir que NeuronSpec tenga todos esos campos como
        atributos nativos.

        `conflict_policy` decide qué pasa cuando el nombre ya existe:

        - `preserve_learned` (por defecto): un campo que el spec no declara se
          conserva. Un `NeuronSpec` normaliza todo a `[]`, así que "no tengo
          opinión" y "quiero que esté vacío" se distinguen con
          `explicit_fields`, no con el valor.
        - `create_only`: si existe, no se toca nada.
        - `replace_definition`: sobrescritura declarativa deliberada.

        La procedencia (`created_by`, `created_at`) y el `id` nunca cambian, y
        el estado nunca baja por esta vía: para eso está `update_status()`.
        """
        if conflict_policy not in CONFLICT_POLICIES:
            raise ValueError(
                f"conflict_policy desconocida: {conflict_policy!r}; "
                f"esperada una de {CONFLICT_POLICIES}"
            )
        values, silent = self._spec_values(spec, contract_payload)
        explicit = set(explicit_fields or ())

        if conflict_policy == "create_only":
            clause, extra = "DO NOTHING", []
        elif conflict_policy == "replace_definition":
            clause, extra = self._conflict_clause(
                set(), explicit | set(_FIELD_POLICY), values["status"]
            )
        else:
            clause, extra = self._conflict_clause(silent, explicit, values["status"])

        columns = list(values)
        statement = (
            f"INSERT INTO neurons ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT(name) {clause}"
        )

        with self._connect() as conn:
            conn.execute(statement, [values[c] for c in columns] + extra)
            row = conn.execute(
                "SELECT id FROM neurons WHERE name = ?", (spec.name,)
            ).fetchone()
        return int(row["id"])

    def create_if_missing(
        self, spec: NeuronSpec, contract_payload: dict[str, Any] | None = None
    ) -> int:
        """Asegura que la neurona existe sin tocarla si ya existía.

        Es la operación que necesita un arranque: "asegurar que existe" no
        puede significar "devolver al estado de fábrica".
        """
        return self.register(spec, contract_payload, conflict_policy="create_only")

    def store_training(self, neuron_id: int, result: NeuronTrainingResult) -> int:
        """Guarda evaluación formativa de una neurona."""
        payload = {
            "strengths": result.strengths,
            "warnings": result.warnings,
            "recommendations": result.recommendations,
        }
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO neuron_training (neuron_id, training_data, evaluation_notes, score, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    neuron_id,
                    json.dumps(result.to_dict(), ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False),
                    result.score,
                    result.status,
                ),
            )
            conn.execute(
                """
                UPDATE neurons
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (result.status, neuron_id),
            )
            return int(cursor.lastrowid or -1)

    def update_status(self, name: str, status: str) -> dict[str, Any]:
        """Actualiza el estado de una neurona por nombre.

        Estados esperados: candidate, experimental, stable, rejected,
        needs_changes. La política de seguridad se aplica fuera de este método.
        """
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE neurons
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE name = ?
                """,
                (status, name),
            )
            row = conn.execute(
                """
                SELECT id, name, mission, domain, rules, triggers, inputs_allowed, outputs_allowed, forbidden_actions, success_metrics, evidence_required, activation_policy, contract_json, status, created_by, created_at, updated_at
                FROM neurons
                WHERE name = ?
                """,
                (name,),
            ).fetchone()

        if row is None:
            raise KeyError(f"No existe neurona registrada: {name}")
        return self._decode_neuron(dict(row))

    def list_neurons(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, mission, domain, rules, triggers, inputs_allowed, outputs_allowed, forbidden_actions, success_metrics, evidence_required, activation_policy, contract_json, status, created_by, created_at, updated_at
                FROM neurons
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._decode_neuron(dict(row)) for row in rows]

    def get_neuron(self, name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, mission, domain, rules, triggers, inputs_allowed, outputs_allowed, forbidden_actions, success_metrics, evidence_required, activation_policy, contract_json, status, created_by, created_at, updated_at
                FROM neurons
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
        return self._decode_neuron(dict(row)) if row else None

    def list_training(self, neuron_id: int, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, neuron_id, training_data, evaluation_notes, score, status, created_at
                FROM neuron_training
                WHERE neuron_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (neuron_id, limit),
            ).fetchall()
        return [self._decode_training(dict(row)) for row in rows]

    @staticmethod
    def _decode_neuron(row: dict[str, Any]) -> dict[str, Any]:
        list_fields = [
            "rules",
            "triggers",
            "inputs_allowed",
            "outputs_allowed",
            "forbidden_actions",
            "success_metrics",
            "evidence_required",
        ]
        dict_fields = [
            "activation_policy",
            "contract_json",
        ]

        for key in list_fields:
            try:
                row[key] = json.loads(row.get(key) or "[]")
            except json.JSONDecodeError:
                row[key] = []

        for key in dict_fields:
            try:
                row[key] = json.loads(row.get(key) or "{}")
            except json.JSONDecodeError:
                row[key] = {}

        return row

    @staticmethod
    def _decode_training(row: dict[str, Any]) -> dict[str, Any]:
        for key in ["training_data", "evaluation_notes"]:
            try:
                row[key] = json.loads(row.get(key) or "{}")
            except json.JSONDecodeError:
                row[key] = {}
        return row
