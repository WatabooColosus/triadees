"""T-007 — Métricas de calidad del output de una neurona: mide completitud,
correctitud, rendimiento, seguridad y adherencia a contratos."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    import hashlib
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class QualityMetrics:
    """Evalúa la calidad del output de una neurona según múltiples dimensiones:
    completitud, correctitud, rendimiento, adherencia a contratos, seguridad."""

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS neuron_quality_metrics (
        metric_id       TEXT PRIMARY KEY,
        neuron_name     TEXT NOT NULL,
        execution_id    TEXT,
        dimensions_json TEXT DEFAULT '{}',
        overall_score   REAL DEFAULT 0.0,
        passed          INTEGER DEFAULT 0,
        failed          INTEGER DEFAULT 0,
        details_json    TEXT DEFAULT '{}',
        created_at      TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_qm_neuron ON neuron_quality_metrics(neuron_name);
    """

    WEIGHTS = {
        "completeness": 0.25,
        "correctness": 0.30,
        "contract_adherence": 0.20,
        "performance": 0.15,
        "security": 0.10,
    }

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.SCHEMA_SQL)

    def evaluate(
        self,
        neuron_name: str,
        execution_output: dict[str, Any],
        expected_output: dict[str, Any] | None = None,
        input_contract: dict | None = None,
        output_contract: dict | None = None,
        duration_ms: float = 0.0,
        memory_bytes: int = 0,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        """Evalúa todas las dimensiones y retorna score compuesto."""
        now = utc_now()
        metric_id = _gen_id("qmetric")

        dims = {}
        dims["completeness"] = _completeness(execution_output, expected_output)
        dims["correctness"] = _correctness(execution_output, expected_output)
        dims["contract_adherence"] = _contract_check(execution_output, output_contract)
        dims["performance"] = _performance_score(duration_ms, memory_bytes)
        dims["security"] = _security_score(execution_output)

        overall = sum(dims[k] * self.WEIGHTS[k] for k in self.WEIGHTS)
        overall = round(_clamp(overall), 4)

        passed = sum(1 for v in dims.values() if v >= 0.7)
        failed = sum(1 for v in dims.values() if v < 0.7)

        self._conn.execute(
            """INSERT INTO neuron_quality_metrics
               (metric_id, neuron_name, execution_id, dimensions_json,
                overall_score, passed, failed, details_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                metric_id,
                neuron_name,
                execution_id,
                json.dumps(dims, default=str),
                overall,
                passed,
                failed,
                json.dumps({"duration_ms": duration_ms, "memory_bytes": memory_bytes}, default=str),
                now,
            ),
        )
        self._conn.commit()

        return {
            "metric_id": metric_id,
            "neuron_name": neuron_name,
            "dimensions": dims,
            "overall_score": overall,
            "passed": passed,
            "failed": failed,
            "quality_ok": overall >= 0.7,
            "created_at": now,
        }

    def get(self, metric_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM neuron_quality_metrics WHERE metric_id=?", (metric_id,)
        ).fetchone()
        return dict(row) if row else None

    def avg_score(self, neuron_name: str) -> float:
        rows = self._conn.execute(
            "SELECT overall_score FROM neuron_quality_metrics WHERE neuron_name=?",
            (neuron_name,),
        ).fetchall()
        if not rows:
            return 0.0
        return round(sum(r["overall_score"] for r in rows) / len(rows), 4)

    def list_for_neuron(self, neuron_name: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM neuron_quality_metrics WHERE neuron_name=? ORDER BY created_at DESC",
            (neuron_name,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- dimension scorers ----------

def _completeness(output: dict, expected: dict | None) -> float:
    if not expected:
        if output:
            return 0.8
        return 0.0
    if not output:
        return 0.0
    expected_keys = set(expected.keys())
    actual_keys = set(output.keys())
    if not expected_keys:
        return 1.0
    matched = len(expected_keys & actual_keys)
    return round(_clamp(matched / len(expected_keys)), 4)


def _correctness(output: dict, expected: dict | None) -> float:
    if not expected:
        return 0.7
    if not output:
        return 0.0
    matches = 0
    total = 0
    for k in expected:
        if k in output:
            total += 1
            if output[k] == expected[k]:
                matches += 1
    if total == 0:
        return 1.0
    return round(_clamp(matches / total), 4)


def _contract_check(output: dict, contract: dict | None) -> float:
    if not contract:
        return 1.0
    if not output:
        return 0.0
    required = contract.get("required_fields", [])
    if not required:
        return 1.0
    present = sum(1 for f in required if f in output)
    return round(_clamp(present / len(required)), 4)


def _performance_score(duration_ms: float, memory_bytes: int) -> float:
    time_score = 1.0 if duration_ms < 100 else (0.8 if duration_ms < 500 else (0.5 if duration_ms < 2000 else 0.2))
    mem_score = 1.0 if memory_bytes < 10_000_000 else (0.7 if memory_bytes < 100_000_000 else 0.3)
    return round(0.6 * time_score + 0.4 * mem_score, 4)


def _security_score(output: dict) -> float:
    score = 1.0
    for k, v in output.items():
        vs = str(v).lower()
        if any(w in vs for w in ("password", "secret", "api_key", "token")):
            score *= 0.5
        if any(w in vs for w in ("rm -rf", "drop table", "delete from")):
            score *= 0.3
    return round(_clamp(score), 4)
