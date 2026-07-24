"""CognitiveLoad — Carga cognitiva real con persistencia SQLite.

Estados reales (no simulados):
- curiosity: basada en novedad/estimulos nuevos
- uncertainty: basada en evidencia e inconsistencias
- fatigue: basada en operacion prolongada
- resource_pressure: cpu/gpu/ram
- cognitive_risk: tareas criticas activas
- accumulated_error_rate: errores recientes

Se integra con SystemSenses para valores reales.
Se persiste y restaura entre runs.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import utc_now

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cognitive_load (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    curiosity       REAL NOT NULL DEFAULT 0.0,
    uncertainty     REAL NOT NULL DEFAULT 0.0,
    fatigue         REAL NOT NULL DEFAULT 0.0,
    resource_pressure REAL NOT NULL DEFAULT 0.0,
    cognitive_risk  REAL NOT NULL DEFAULT 0.0,
    accumulated_error_rate REAL NOT NULL DEFAULT 0.0,
    dimensions_json TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cl_run ON cognitive_load(run_id);
"""


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class CognitiveLoad:
    """Carga cognitiva real con persistencia, no valores simulados."""

    curiosity: float = 0.0
    uncertainty: float = 0.0
    fatigue: float = 0.0
    resource_pressure: float = 0.0
    cognitive_risk: float = 0.0
    accumulated_error_rate: float = 0.0
    _dimensions: dict[str, float] = field(default_factory=dict)
    _conn: sqlite3.Connection | None = field(default=None, repr=False)
    _created_at: str = ""
    _run_id: str = ""

    def __post_init__(self):
        if not self._dimensions:
            self._dimensions = {
                "curiosity": self.curiosity,
                "uncertainty": self.uncertainty,
                "fatigue": self.fatigue,
                "resource_pressure": self.resource_pressure,
                "cognitive_risk": self.cognitive_risk,
                "accumulated_error_rate": self.accumulated_error_rate,
            }

    def update_from_sensors(self, sensor_data: dict[str, Any]) -> None:
        """Update cognitive load from real sensor data."""
        cpu = float(sensor_data.get("cpu_percent", 0.0))
        ram = float(sensor_data.get("ram_percent", 0.0))
        gpu = float(sensor_data.get("gpu_percent", 0.0))
        vram = float(sensor_data.get("vram_percent", 0.0))
        error_rate = float(sensor_data.get("error_rate", 0.0))
        task_criticality = float(sensor_data.get("task_criticality", 0.0))
        novelty = float(sensor_data.get("novelty", 0.0))
        evidence_gaps = float(sensor_data.get("evidence_gaps", 0.0))

        self.curiosity = _clamp(novelty * 0.8 + (1.0 - error_rate) * 0.2)
        self.uncertainty = _clamp(evidence_gaps * 0.7 + error_rate * 0.3)
        self.fatigue = _clamp((cpu + ram + gpu + vram) / 400.0)
        self.resource_pressure = _clamp(max(cpu, ram, gpu, vram) / 100.0)
        self.cognitive_risk = _clamp(task_criticality * 0.6 + error_rate * 0.4)
        self.accumulated_error_rate = _clamp(error_rate * 0.9 + self.accumulated_error_rate * 0.1)

        self._dimensions = {
            "curiosity": self.curiosity,
            "uncertainty": self.uncertainty,
            "fatigue": self.fatigue,
            "resource_pressure": self.resource_pressure,
            "cognitive_risk": self.cognitive_risk,
            "accumulated_error_rate": self.accumulated_error_rate,
        }

    @property
    def overall(self) -> float:
        vals = [self.curiosity, self.uncertainty, self.fatigue,
                self.resource_pressure, self.cognitive_risk, self.accumulated_error_rate]
        return round(sum(vals) / max(len(vals), 1), 4)

    @property
    def is_overloaded(self) -> bool:
        return self.overall > 0.8 or self.fatigue > 0.9 or self.resource_pressure > 0.9

    @property
    def should_suspend_non_critical(self) -> bool:
        return self.fatigue > 0.7 or self.resource_pressure > 0.8

    @property
    def should_reduce_concurrency(self) -> bool:
        return self.fatigue > 0.6 or self.resource_pressure > 0.7

    @property
    def should_investigate(self) -> bool:
        return self.uncertainty > 0.7 or self.accumulated_error_rate > 0.5

    @property
    def should_circuit_break(self) -> bool:
        return self.accumulated_error_rate > 0.8 or self.cognitive_risk > 0.9

    def to_dict(self) -> dict[str, Any]:
        return {
            "curiosity": self.curiosity,
            "uncertainty": self.uncertainty,
            "fatigue": self.fatigue,
            "resource_pressure": self.resource_pressure,
            "cognitive_risk": self.cognitive_risk,
            "accumulated_error_rate": self.accumulated_error_rate,
            "overall": self.overall,
            "is_overloaded": self.is_overloaded,
            "should_suspend_non_critical": self.should_suspend_non_critical,
            "should_reduce_concurrency": self.should_reduce_concurrency,
            "should_investigate": self.should_investigate,
            "should_circuit_break": self.should_circuit_break,
        }

    def save(self, run_id: str = "") -> None:
        if not self._conn:
            return
        self._run_id = run_id or self._run_id
        self._created_at = utc_now()
        self._conn.execute(
            """INSERT INTO cognitive_load
               (run_id, curiosity, uncertainty, fatigue, resource_pressure,
                cognitive_risk, accumulated_error_rate, dimensions_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (self._run_id, self.curiosity, self.uncertainty, self.fatigue,
             self.resource_pressure, self.cognitive_risk, self.accumulated_error_rate,
             json.dumps(self._dimensions, default=str), self._created_at),
        )
        self._conn.commit()

    @classmethod
    def load(cls, run_id: str, conn: sqlite3.Connection) -> CognitiveLoad | None:
        row = conn.execute(
            "SELECT * FROM cognitive_load WHERE run_id=? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        return cls(
            curiosity=row["curiosity"],
            uncertainty=row["uncertainty"],
            fatigue=row["fatigue"],
            resource_pressure=row["resource_pressure"],
            cognitive_risk=row["cognitive_risk"],
            accumulated_error_rate=row["accumulated_error_rate"],
            _run_id=row["run_id"],
            _created_at=row["created_at"],
            _conn=conn,
        )

    def init_db(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def __getitem__(self, key: str) -> float:
        return self._dimensions.get(key, 0.0)

    def __setitem__(self, key: str, value: float) -> None:
        if key in self._dimensions:
            self._dimensions[key] = _clamp(value)
            setattr(self, key, _clamp(value))

    def __contains__(self, key: str) -> bool:
        return key in self._dimensions

    def get(self, key: str, default: float = 0.0) -> float:
        return self._dimensions.get(key, default)

    @classmethod
    def compute_with_context(
        cls,
        snapshot: Any,
        *,
        query_novelty: float = 0.5,
        recent_confidence: float = 0.7,
    ) -> CognitiveSnapshot:
        cpu = getattr(snapshot, "cpu_load", 0.0) or 0.0
        ram = getattr(snapshot, "ram_usage", 0.0) or 0.0
        gpu = getattr(snapshot, "gpu_utilization", 0.0) or 0.0
        err = getattr(snapshot, "error_rate_hour", 0.0) or 0.0
        cpu_p = round(_clamp(cpu), 4)
        ram_p = round(_clamp(ram), 4)
        gpu_p = round(_clamp(gpu), 4)
        curiosity = round(_clamp(query_novelty * 0.8 + (1.0 - err) * 0.2), 4)
        uncertainty = round(_clamp((1.0 - recent_confidence) * 0.7 + err * 0.3), 4)
        fatigue = round(_clamp((cpu_p + ram_p + gpu_p) / 3.0), 4)
        overall = round(_clamp((cpu_p + ram_p + gpu_p + curiosity + uncertainty + fatigue) / 6.0), 4)
        return CognitiveSnapshot(
            cpu_pressure=cpu_p, ram_pressure=ram_p, gpu_pressure=gpu_p,
            curiosity=curiosity, uncertainty=uncertainty, fatigue=fatigue,
            overall_load=overall,
        )


@dataclass
class CognitiveSnapshot:
    cpu_pressure: float = 0.0
    ram_pressure: float = 0.0
    gpu_pressure: float = 0.0
    curiosity: float = 0.0
    uncertainty: float = 0.0
    fatigue: float = 0.0
    overall_load: float = 0.0
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_pressure": self.cpu_pressure,
            "ram_pressure": self.ram_pressure,
            "gpu_pressure": self.gpu_pressure,
            "curiosity": self.curiosity,
            "uncertainty": self.uncertainty,
            "fatigue": self.fatigue,
            "overall_load": self.overall_load,
            "created_at": self.created_at,
        }
