"""T-007 — Diseño de neurona: genera plan de diseño estructurado con
componentes, interfaces, contratos, dependencias y criterios de éxito antes
de la creación."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class DesignEngine:
    """Genera un plan de diseño estructurado para una neurona antes de su
    creación. Define componentes, interfaces, contratos I/O, dependencias
    y criterios de éxito verificables."""

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS neuron_designs (
        design_id          TEXT PRIMARY KEY,
        research_id        TEXT,
        comparison_id      TEXT,
        neuron_name        TEXT NOT NULL,
        mission            TEXT NOT NULL,
        domain             TEXT NOT NULL,
        components_json    TEXT DEFAULT '[]',
        interfaces_json    TEXT DEFAULT '[]',
        input_contract_json  TEXT DEFAULT '{}',
        output_contract_json TEXT DEFAULT '{}',
        dependencies_json  TEXT DEFAULT '[]',
        success_criteria_json TEXT DEFAULT '[]',
        complexity_score   REAL DEFAULT 0.0,
        design_hash        TEXT DEFAULT '',
        status             TEXT DEFAULT 'draft',
        created_at         TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_design_domain ON neuron_designs(domain);
    """

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.SCHEMA_SQL)

    def design(
        self,
        neuron_name: str,
        mission: str,
        domain: str,
        research_id: str | None = None,
        comparison_id: str | None = None,
        input_schema: dict | None = None,
        output_schema: dict | None = None,
        required_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        """Genera plan de diseño completo."""
        now = utc_now()
        design_id = _gen_id("design")

        input_contract = _build_contract(input_schema or {"type": "object"}, "input")
        output_contract = _build_contract(output_schema or {"type": "object"}, "output")
        components = _infer_components(mission, domain, required_capabilities or [])
        interfaces = _infer_interfaces(components, input_contract, output_contract)
        deps = _infer_dependencies(required_capabilities or [], components)
        criteria = _success_criteria(mission, components)
        complexity = _complexity_score(components, interfaces, deps)

        design_content = {
            "neuron_name": neuron_name,
            "mission": mission,
            "domain": domain,
            "components": components,
            "interfaces": interfaces,
            "input_contract": input_contract,
            "output_contract": output_contract,
            "dependencies": deps,
            "success_criteria": criteria,
        }
        design_hash = hashlib.sha256(
            json.dumps(design_content, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        payload = {
            "design_id": design_id,
            "research_id": research_id,
            "comparison_id": comparison_id,
            "neuron_name": neuron_name,
            "mission": mission,
            "domain": domain,
            "components": components,
            "interfaces": interfaces,
            "input_contract": input_contract,
            "output_contract": output_contract,
            "dependencies": deps,
            "success_criteria": criteria,
            "complexity_score": complexity,
            "design_hash": design_hash,
            "status": "draft",
            "created_at": now,
        }

        self._conn.execute(
            """INSERT INTO neuron_designs
               (design_id, research_id, comparison_id, neuron_name, mission,
                domain, components_json, interfaces_json,
                input_contract_json, output_contract_json,
                dependencies_json, success_criteria_json,
                complexity_score, design_hash, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                design_id,
                research_id,
                comparison_id,
                neuron_name,
                mission,
                domain,
                json.dumps(components, default=str),
                json.dumps(interfaces, default=str),
                json.dumps(input_contract, default=str),
                json.dumps(output_contract, default=str),
                json.dumps(deps, default=str),
                json.dumps(criteria, default=str),
                complexity,
                design_hash,
                "draft",
                now,
            ),
        )
        self._conn.commit()
        return payload

    def approve(self, design_id: str) -> dict:
        self._conn.execute(
            "UPDATE neuron_designs SET status='approved' WHERE design_id=?",
            (design_id,),
        )
        self._conn.commit()
        return {"design_id": design_id, "status": "approved"}

    def get(self, design_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM neuron_designs WHERE design_id=?", (design_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_by_domain(self, domain: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM neuron_designs WHERE domain=? ORDER BY created_at DESC",
            (domain,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- helpers ----------

def _build_contract(schema: dict, kind: str) -> dict:
    return {
        "kind": kind,
        "schema": schema,
        "required_fields": list(schema.get("properties", {}).keys()),
        "nullable_fields": [k for k, v in schema.get("properties", {}).items() if v.get("nullable")],
    }


def _infer_components(mission: str, domain: str, caps: list[str]) -> list[dict]:
    components = [{"name": "core", "role": "primary", "responsibility": mission}]
    for i, cap in enumerate(caps):
        components.append({"name": f"cap_{cap}", "role": "capability", "responsibility": f"Provee {cap}"})
    if len(caps) > 3:
        components.append({"name": "orchestrator", "role": "coordinator", "responsibility": "Coordina capacidades"})
    return components


def _infer_interfaces(components: list[dict], input_c: dict, output_c: dict) -> list[dict]:
    interfaces = []
    for comp in components:
        interfaces.append({
            "component": comp["name"],
            "input_fields": input_c.get("required_fields", []),
            "output_fields": output_c.get("required_fields", []),
            "type": "function",
        })
    return interfaces


def _infer_dependencies(caps: list[str], components: list[dict]) -> list[dict]:
    deps = []
    for cap in caps:
        deps.append({"name": cap, "kind": "capability", "optional": False})
    return deps


def _success_criteria(mission: str, components: list[dict]) -> list[dict]:
    criteria = [
        {"criterion": "all_components_instantiable", "type": "structural"},
        {"criterion": "input_output_contracts_respected", "type": "contractual"},
        {"criterion": f"mission_coverage_above_0.8", "type": "functional"},
    ]
    if len(components) > 3:
        criteria.append({"criterion": "orchestrator_coordinates_successfully", "type": "integration"})
    return criteria


def _complexity_score(components: list[dict], interfaces: list[dict], deps: list[dict]) -> float:
    c_score = min(len(components) / 6.0, 1.0) * 0.4
    i_score = min(len(interfaces) / 6.0, 1.0) * 0.3
    d_score = min(len(deps) / 5.0, 1.0) * 0.3
    return round(c_score + i_score + d_score, 3)
