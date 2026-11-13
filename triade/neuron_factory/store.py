"""Persistencia e historial de especificaciones de neuronas."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from triade.db import sqlite3

from .specification import NeuronSpecification, ResourceBudget, validate_transition


class NeuronSpecificationStore:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS neuron_specifications (
                    neuron_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (neuron_id, version)
                );
                CREATE TABLE IF NOT EXISTS neuron_specification_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    neuron_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_neuron_spec_history
                    ON neuron_specification_history(neuron_id, version, id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def register(self, specification: NeuronSpecification) -> dict[str, Any]:
        specification.validate()
        payload_json = json.dumps(specification.to_dict(), sort_keys=True)
        payload = json.loads(payload_json)
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO neuron_specifications
                    (neuron_id, version, state, payload_json)
                    VALUES (?, ?, ?, ?)""",
                    (
                        specification.neuron_id,
                        specification.version,
                        specification.state,
                        payload_json,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("especificación ya registrada") from exc
            self._append_history(
                conn,
                specification.neuron_id,
                specification.version,
                "registered",
                payload,
            )
        return payload

    def register_for_existing_neuron(
        self,
        neuron_id: str,
        *,
        version: str,
        component: str,
        provides_capabilities: tuple[str, ...],
        resource_budget: ResourceBudget,
        owner: str,
        requires_capabilities: tuple[str, ...] = (),
        evaluation_suites: tuple[str, ...] = (),
        rollback_policy: str | None = None,
        critical: bool = False,
    ) -> dict[str, Any]:
        """Registra la especificación de una neurona que **ya existe**.

        `register()` sólo lo llamaban los tests: seis módulos de la fábrica leen
        `neuron_specifications` y ningún camino de producción la escribía. La
        consecuencia se ve al final de la cadena de auto-mejora, que muere en
        `especificación no registrada: 1@1.0.0` con las 37 neuronas de la base
        viva sin una sola fila.

        Lo descriptivo **se deriva de la neurona registrada** —nombre, misión,
        dominio y sus contratos de entrada y salida—: inventarlo aquí crearía una
        segunda descripción de la misma neurona, y dos descripciones divergen.
        Lo que no se puede derivar se pide, porque es decisión y no dato:

        - `provides_capabilities`, que la fábrica usa para comprobar que la
          mejora pedida la aporta de verdad esta neurona;
        - `resource_budget`, que limita lo que una candidata puede consumir;
        - `component` y `version`, que dicen qué código la implementa y cuál de
          sus versiones se está contratando.

        Declarar esto es un acto de gobernanza, no una migración automática: por
        eso lo expone una ruta con firma y no un worker.
        """
        with self._connect() as conn:
            fila = conn.execute(
                "SELECT name, mission, domain, inputs_allowed, outputs_allowed,"
                " created_by FROM neurons WHERE id = ?",
                (neuron_id,),
            ).fetchone()
        if fila is None:
            raise KeyError(f"neurona no registrada: {neuron_id}")

        def _contrato(crudo: Any, etiqueta: str) -> dict[str, Any]:
            try:
                valor = json.loads(crudo) if crudo else []
            except (TypeError, ValueError):
                valor = []
            if not valor:
                # Sin contrato declarado no se inventa uno vacío: `validate()`
                # lo rechazaría igual y con un mensaje peor.
                raise ValueError(f"la neurona no declara {etiqueta}")
            return {"allowed": list(valor)}

        especificacion = NeuronSpecification(
            neuron_id=str(neuron_id),
            name=str(fila["name"] or ""),
            mission=str(fila["mission"] or ""),
            domain=str(fila["domain"] or "general"),
            version=version,
            owner=owner or str(fila["created_by"] or ""),
            component=component,
            input_contract=_contrato(fila["inputs_allowed"], "inputs_allowed"),
            output_contract=_contrato(fila["outputs_allowed"], "outputs_allowed"),
            provides_capabilities=tuple(provides_capabilities),
            requires_capabilities=tuple(requires_capabilities),
            evaluation_suites=tuple(evaluation_suites),
            rollback_policy=rollback_policy,
            critical=critical,
            resource_budget=resource_budget,
        )
        registrada = self.register(especificacion)
        # `draft → specified` es la única transición del ciclo de vida sin un
        # solo llamador en todo el repositorio: `candidate.py` mueve a
        # `training`, `evaluation.py` a `promoted` o `quarantined`, y
        # `lifecycle.py` a `quarantined`. Nadie declaraba una especificación
        # como revisada, así que una recién registrada se quedaba en `draft`
        # para siempre y la fábrica la rechazaba con «la especificación debe
        # estar en estado specified».
        #
        # Se hace aquí porque esta llamada **es** la revisión: la firma con
        # nombre que la autoriza. Pedir un segundo acto firmado a la misma
        # persona no añade una comprobación, añade un trámite — y un trámite que
        # se firma sin mirar es peor que no tenerlo.
        return {
            **registrada,
            **self.transition(especificacion.neuron_id, version, "specified"),
        }

    def get(self, neuron_id: str, version: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT payload_json FROM neuron_specifications WHERE neuron_id = ?"
        params: list[Any] = [neuron_id]
        if version:
            sql += " AND version = ?"
            params.append(version)
        sql += " ORDER BY created_at DESC, version DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def transition(self, neuron_id: str, version: str, target: str) -> dict[str, Any]:
        payload = self.get(neuron_id, version)
        if payload is None:
            raise KeyError(f"especificación no registrada: {neuron_id}@{version}")
        current = str(payload["state"])
        validate_transition(current, target)
        payload["state"] = target
        with self._connect() as conn:
            conn.execute(
                """UPDATE neuron_specifications
                SET state = ?, payload_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE neuron_id = ? AND version = ?""",
                (target, json.dumps(payload, sort_keys=True), neuron_id, version),
            )
            self._append_history(
                conn,
                neuron_id,
                version,
                "state_changed",
                {"from": current, "to": target, "snapshot": payload},
            )
        return payload

    def history(
        self, neuron_id: str, version: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT action, payload_json, created_at FROM neuron_specification_history WHERE neuron_id = ?"
        params: list[Any] = [neuron_id]
        if version:
            sql += " AND version = ?"
            params.append(version)
        sql += " ORDER BY id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "action": row["action"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def export(self, neuron_id: str, version: str | None = None) -> dict[str, Any]:
        payload = self.get(neuron_id, version)
        if payload is None:
            raise KeyError(f"especificación no registrada: {neuron_id}")
        resolved_version = str(payload["version"])
        document = {
            "schema_version": "1.0.0",
            "specification": payload,
            "history": self.history(neuron_id, resolved_version),
        }
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
        document["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return document

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> NeuronSpecification:
        data = dict(payload)
        budget = data.get("resource_budget")
        data["resource_budget"] = ResourceBudget(**budget) if budget else None
        for field in (
            "provides_capabilities",
            "requires_capabilities",
            "evaluation_suites",
        ):
            data[field] = tuple(data.get(field) or ())
        return NeuronSpecification(**data)

    @staticmethod
    def _append_history(
        conn: sqlite3.Connection,
        neuron_id: str,
        version: str,
        action: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            """INSERT INTO neuron_specification_history
            (neuron_id, version, action, payload_json)
            VALUES (?, ?, ?, ?)""",
            (neuron_id, version, action, json.dumps(payload, sort_keys=True)),
        )
