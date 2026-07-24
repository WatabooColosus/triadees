"""Pulso jerárquico y adaptativo de Tríade Ω.

Extiende LifePulseEngine con:
- Pulso jerárquico (_global → neuronas → workers)
- Pulso adaptativo (frecuencia según carga)
- Interocepción computacional (auto-diagnóstico)
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now

PulseLevel = Literal["global", "neuron", "worker"]
PulseHealth = Literal["healthy", "degraded", "critical", "flatline"]


@dataclass(frozen=True, slots=True)
class PulseReading:
    level: PulseLevel
    component: str
    health: PulseHealth
    latency_ms: float
    last_beat_at: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HierarchicalPulse:
    global_pulse: PulseReading
    neuron_pulses: tuple[PulseReading, ...]
    worker_pulses: tuple[PulseReading, ...]
    overall_health: PulseHealth
    interoception_score: float
    adaptive_interval_ms: float
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "global": self.global_pulse.to_dict(),
            "neurons": [p.to_dict() for p in self.neuron_pulses],
            "workers": [p.to_dict() for p in self.worker_pulses],
            "overall_health": self.overall_health,
            "interoception_score": self.interoception_score,
            "adaptive_interval_ms": self.adaptive_interval_ms,
            "timestamp": self.timestamp,
        }


class HierarchicalPulseEngine:
    """Motor de pulso jerárquico con adaptación dinámica."""

    BASE_INTERVAL_MS = 5000.0
    MIN_INTERVAL_MS = 1000.0
    MAX_INTERVAL_MS = 30000.0

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._last_readings: dict[str, PulseReading] = {}
        self._error_counts: dict[str, int] = {}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS pulse_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    component TEXT NOT NULL,
                    health TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    recorded_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pulse_component ON pulse_log(component, recorded_at)"
            )

    def read_global(self, *, latency_ms: float = 0.0) -> PulseReading:
        health: PulseHealth = "healthy"
        if latency_ms > 5000:
            health = "critical"
        elif latency_ms > 2000:
            health = "degraded"
        reading = PulseReading(
            level="global",
            component="life_pulse",
            health=health,
            latency_ms=latency_ms,
            last_beat_at=utc_now(),
        )
        self._last_readings["global"] = reading
        self._log(reading)
        return reading

    def read_neuron(self, neuron_id: str, *, latency_ms: float = 0.0, details: dict[str, Any] | None = None) -> PulseReading:
        health: PulseHealth = "healthy"
        errors = self._error_counts.get(neuron_id, 0)
        if errors > 5:
            health = "critical"
        elif errors > 2:
            health = "degraded"
        elif latency_ms > 3000:
            health = "degraded"
        reading = PulseReading(
            level="neuron",
            component=neuron_id,
            health=health,
            latency_ms=latency_ms,
            last_beat_at=utc_now(),
            details=details or {},
        )
        self._last_readings[f"neuron:{neuron_id}"] = reading
        self._log(reading)
        return reading

    def read_worker(self, worker_id: str, *, latency_ms: float = 0.0, details: dict[str, Any] | None = None) -> PulseReading:
        health: PulseHealth = "healthy"
        if latency_ms > 10000:
            health = "flatline"
        elif latency_ms > 5000:
            health = "critical"
        reading = PulseReading(
            level="worker",
            component=worker_id,
            health=health,
            latency_ms=latency_ms,
            last_beat_at=utc_now(),
            details=details or {},
        )
        self._last_readings[f"worker:{worker_id}"] = reading
        self._log(reading)
        return reading

    def compute_interoception(self) -> float:
        if not self._last_readings:
            return 0.5
        scores: list[float] = []
        health_map = {"healthy": 1.0, "degraded": 0.6, "critical": 0.2, "flatline": 0.0}
        for reading in self._last_readings.values():
            base = health_map.get(reading.health, 0.5)
            latency_penalty = min(0.3, reading.latency_ms / 10000)
            scores.append(max(0.0, base - latency_penalty))
        return round(sum(scores) / len(scores), 3)

    def adaptive_interval(self) -> float:
        interoception = self.compute_interoception()
        if interoception < 0.3:
            interval = self.MIN_INTERVAL_MS
        elif interoception < 0.6:
            interval = self.BASE_INTERVAL_MS * 0.7
        elif interoception > 0.9:
            interval = self.BASE_INTERVAL_MS * 1.5
        else:
            interval = self.BASE_INTERVAL_MS
        return min(self.MAX_INTERVAL_MS, max(self.MIN_INTERVAL_MS, interval))

    def hierarchical_reading(self) -> HierarchicalPulse:
        global_p = self._last_readings.get("global")
        if global_p is None:
            global_p = self.read_global()
        neurons = tuple(
            v for k, v in self._last_readings.items() if k.startswith("neuron:")
        )
        workers = tuple(
            v for k, v in self._last_readings.items() if k.startswith("worker:")
        )
        all_readings = [global_p] + list(neurons) + list(workers)
        health_counts: dict[str, int] = {}
        for r in all_readings:
            health_counts[r.health] = health_counts.get(r.health, 0) + 1
        if health_counts.get("flatline", 0) > 0:
            overall: PulseHealth = "flatline"
        elif health_counts.get("critical", 0) > 0:
            overall = "critical"
        elif health_counts.get("degraded", 0) > 0:
            overall = "degraded"
        else:
            overall = "healthy"
        return HierarchicalPulse(
            global_pulse=global_p,
            neuron_pulses=neurons,
            worker_pulses=workers,
            overall_health=overall,
            interoception_score=self.compute_interoception(),
            adaptive_interval_ms=self.adaptive_interval(),
            timestamp=utc_now(),
        )

    def record_error(self, component: str) -> None:
        self._error_counts[component] = self._error_counts.get(component, 0) + 1

    def clear_errors(self, component: str) -> None:
        self._error_counts.pop(component, None)

    def _log(self, reading: PulseReading) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO pulse_log(level, component, health, latency_ms, details_json, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (reading.level, reading.component, reading.health, reading.latency_ms,
                     json.dumps(reading.details, ensure_ascii=False), reading.last_beat_at),
                )
        except sqlite3.OperationalError:
            pass

    def recent_readings(self, component: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pulse_log WHERE component = ? ORDER BY id DESC LIMIT ?",
                (component, limit),
            ).fetchall()
        return [dict(row) for row in rows]
