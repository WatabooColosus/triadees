"""T-007 — Generador automático de tests para neuronas: crea tests unitarios,
de contrato, de integración y de regresión a partir de la especificación y
diseño de una neurona."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


class NeuronTestGenerator:
    """Genera tests estructurados a partir de la especificación, diseño y
    contratos de una neurona. Los tests son declarativos (JSON) y se ejecutan
    por el sandbox execution engine."""

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS neuron_test_suites (
        suite_id       TEXT PRIMARY KEY,
        neuron_name    TEXT NOT NULL,
        design_id      TEXT,
        tests_json     TEXT DEFAULT '[]',
        test_count     INTEGER DEFAULT 0,
        coverage_json  TEXT DEFAULT '{}',
        created_at     TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS neuron_test_results (
        result_id      TEXT PRIMARY KEY,
        suite_id       TEXT NOT NULL,
        test_name      TEXT NOT NULL,
        test_type      TEXT NOT NULL,
        status         TEXT DEFAULT 'pending',
        details_json   TEXT DEFAULT '{}',
        duration_ms    REAL DEFAULT 0.0,
        created_at     TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_test_suite ON neuron_test_results(suite_id);
    """

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.SCHEMA_SQL)

    def generate(
        self,
        neuron_name: str,
        design: dict[str, Any],
        spec: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Genera suite de tests completa a partir del diseño y spec."""
        now = utc_now()
        suite_id = _gen_id("tsuite")
        design_id = design.get("design_id", "")

        tests = []
        tests.extend(_contract_tests(design))
        tests.extend(_component_tests(design))
        tests.extend(_integration_tests(design))
        tests.extend(_boundary_tests(design))
        if spec and spec.get("critical"):
            tests.extend(_critical_neuron_tests(design))

        coverage = {
            "total": len(tests),
            "by_type": {},
        }
        for t in tests:
            tt = t["type"]
            coverage["by_type"][tt] = coverage["by_type"].get(tt, 0) + 1

        payload = {
            "suite_id": suite_id,
            "neuron_name": neuron_name,
            "design_id": design_id,
            "tests": tests,
            "test_count": len(tests),
            "coverage": coverage,
            "created_at": now,
        }

        self._conn.execute(
            """INSERT INTO neuron_test_suites
               (suite_id, neuron_name, design_id, tests_json,
                test_count, coverage_json, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (suite_id, neuron_name, design_id, json.dumps(tests, default=str),
             len(tests), json.dumps(coverage, default=str), now),
        )
        self._conn.commit()
        return payload

    def record_result(
        self, suite_id: str, test_name: str, test_type: str,
        status: str, details: dict | None = None, duration_ms: float = 0.0,
    ) -> dict:
        result_id = _gen_id("tresult")
        self._conn.execute(
            """INSERT INTO neuron_test_results
               (result_id, suite_id, test_name, test_type,
                status, details_json, duration_ms, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (result_id, suite_id, test_name, test_type,
             status, json.dumps(details or {}, default=str),
             duration_ms, utc_now()),
        )
        self._conn.commit()
        return {"result_id": result_id, "status": status}

    def suite_results(self, suite_id: str) -> dict:
        rows = self._conn.execute(
            "SELECT * FROM neuron_test_results WHERE suite_id=? ORDER BY created_at",
            (suite_id,),
        ).fetchall()
        results = [dict(r) for r in rows]
        passed = sum(1 for r in results if r["status"] == "pass")
        failed = sum(1 for r in results if r["status"] == "fail")
        return {
            "suite_id": suite_id,
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "all_pass": failed == 0 and len(results) > 0,
            "results": results,
        }

    def get(self, suite_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM neuron_test_suites WHERE suite_id=?", (suite_id,)
        ).fetchone()
        return dict(row) if row else None


# ---------- test generators ----------

def _contract_tests(design: dict) -> list[dict]:
    tests = []
    input_c = design.get("input_contract", {})
    for field in input_c.get("required_fields", []):
        tests.append({
            "name": f"contract_input_has_{field}",
            "type": "contract",
            "description": f"Input debe incluir campo '{field}'",
            "assertion": "input_has_field",
            "params": {"field": field},
        })
    output_c = design.get("output_contract", {})
    for field in output_c.get("required_fields", []):
        tests.append({
            "name": f"contract_output_has_{field}",
            "type": "contract",
            "description": f"Output debe incluir campo '{field}'",
            "assertion": "output_has_field",
            "params": {"field": field},
        })
    return tests


def _component_tests(design: dict) -> list[dict]:
    tests = []
    for comp in design.get("components", []):
        tests.append({
            "name": f"component_{comp['name']}_instantiable",
            "type": "unit",
            "description": f"Componente '{comp['name']}' se puede instanciar",
            "assertion": "component_exists",
            "params": {"component_name": comp["name"]},
        })
    return tests


def _integration_tests(design: dict) -> list[dict]:
    tests = []
    components = design.get("components", [])
    if len(components) > 1:
        tests.append({
            "name": "integration_all_components_connected",
            "type": "integration",
            "description": "Todos los componentes se conectan correctamente",
            "assertion": "components_connected",
            "params": {"count": len(components)},
        })
    deps = design.get("dependencies", [])
    for dep in deps:
        tests.append({
            "name": f"integration_dependency_{dep['name']}_available",
            "type": "integration",
            "description": f"Dependencia '{dep['name']}' está disponible",
            "assertion": "dependency_available",
            "params": {"dependency_name": dep["name"]},
        })
    return tests


def _boundary_tests(design: dict) -> list[dict]:
    return [
        {
            "name": "boundary_empty_input",
            "type": "boundary",
            "description": "Maneja input vacío sin crash",
            "assertion": "no_crash_on_empty",
            "params": {},
        },
        {
            "name": "boundary_max_size_input",
            "type": "boundary",
            "description": "Maneja input de tamaño máximo",
            "assertion": "handles_max_size",
            "params": {"max_bytes": 1048576},
        },
        {
            "name": "boundary_null_fields",
            "type": "boundary",
            "description": "Maneja campos nulos en input",
            "assertion": "handles_null_fields",
            "params": {},
        },
    ]


def _critical_neuron_tests(design: dict) -> list[dict]:
    return [
        {
            "name": "critical_rollback_on_failure",
            "type": "critical",
            "description": "Neurona crítica ejecuta rollback en fallo",
            "assertion": "rollback_executed",
            "params": {},
        },
        {
            "name": "critical_audit_trail_complete",
            "type": "critical",
            "description": "Trail de auditoría completo para neurona crítica",
            "assertion": "audit_complete",
            "params": {},
        },
        {
            "name": "critical_no_identity_mutation",
            "type": "critical",
            "description": "Neurona crítica no muta identity_core",
            "assertion": "no_identity_mutation",
            "params": {},
        },
    ]
