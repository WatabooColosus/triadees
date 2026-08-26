"""Libro contable central y política de degradación por presupuesto diario."""

from __future__ import annotations

import resource
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.db import sqlite3

DEFAULT_BUDGET = {
    "cpu_minutes_daily": 600.0,
    "gpu_minutes_daily": 360.0,
    "network_mb_daily": 1500.0,
    "new_storage_mb_daily": 500.0,
    "research_tasks_daily": 40.0,
    "deep_evaluations_daily": 12.0,
    "model_installs_daily": 1.0,
}

#: Recursos físicos compartidos: los gasta cualquier tarea y su escasez es
#: real, así que gobiernan la escalera de degradación global.
PRESSURE_LINES: tuple[str, ...] = (
    "cpu_minutes_daily",
    "gpu_minutes_daily",
    "network_mb_daily",
    "new_storage_mb_daily",
)

#: Cupos por clase: no son un recurso escaso sino un permiso contado. Cada uno
#: limita **su** clase y ninguna otra.
#:
#: Estaban en el mismo `max()` que los recursos compartidos, y esa mezcla tenía
#: tres consecuencias medidas, ninguna querida:
#:
#: 1. Auto-inanición. Al 70 % de su propia línea la clase se prohibía a sí
#:    misma, así que el límite declarado era inalcanzable por construcción:
#:    `deep_evaluations_daily=12` rendía 9. En la base hay tres días seguidos
#:    —2026-08-08, 09 y 10— con exactamente 9 `stable_consolidation_review`,
#:    todas entre las 00:00 y las 00:41 UTC, y ninguna después.
#: 2. Contaminación cruzada. 32 investigaciones de 40 (0.80) apagaban la
#:    evaluación profunda, que iba por 0.75 y tenía sitio. Un candidato con
#:    evidencia `improved` y tres usos causales nacido a las 01:29 no podía ser
#:    revisado hasta el día siguiente, aunque su propio cupo tuviera hueco.
#: 3. Suicidio por instalación. `model_installs_daily=1`: gastar el único
#:    permiso presupuestado ponía la razón en 1.0 y con ella el organismo entero
#:    en `observe_only` hasta medianoche.
#:
#: Los umbrales de la escalera (0.70/0.85/0.95/1.0) y los límites declarados no
#: se tocan: lo que cambia es que un cupo se agota en su límite, no antes, y que
#: no arrastra a las demás clases al agotarse.
QUOTA_LINES: dict[str, str] = {
    "research_tasks_daily": "research",
    "deep_evaluations_daily": "deep_evaluation",
    "model_installs_daily": "model_install",
}


def load_runtime_budget(yml_path: str | Path = "triade.yml") -> dict[str, float]:
    """Presupuesto declarado en `triade.yml`, con los defaults como respaldo.

    `runtime_budget` llevaba declarado en `triade.yml` desde siempre y no lo
    leía nadie: los tres constructores de `ResourceLedger` se quedaban con
    `DEFAULT_BUDGET`. Hoy los dos juegos de cifras coinciden, así que el error
    no se veía; el día que alguien editase el YAML habría cambiado un número
    que el organismo no mira. Se lee aquí para que el fichero sea la fuente y
    no la decoración.
    """
    presupuesto = dict(DEFAULT_BUDGET)
    try:
        from triade.core.config import load_config

        declarado = (load_config(yml_path) or {}).get("runtime_budget") or {}
        for key in DEFAULT_BUDGET:
            if key in declarado:
                presupuesto[key] = float(declarado[key])
    except (OSError, ImportError, RuntimeError, ValueError, TypeError, KeyError):
        # Sin YAML legible se sigue con los defaults: el libro contable no es
        # sitio para caerse, y el respaldo es exactamente lo que había antes.
        pass
    return presupuesto


@dataclass(frozen=True, slots=True)
class ResourceMeasurement:
    resource_name: str
    value: float | None
    unit: str
    measurement_type: str
    source: str
    started_at: str
    finished_at: str

    def __post_init__(self) -> None:
        if self.measurement_type not in {"measured", "estimated", "unavailable"}:
            raise ValueError("invalid_measurement_type")
        if self.measurement_type == "unavailable" and self.value is not None:
            raise ValueError("unavailable_measurement_cannot_have_value")
        if self.measurement_type == "measured" and not self.source:
            raise ValueError("measured_resource_requires_source")


@dataclass(frozen=True, slots=True)
class ResourceUsageReceipt:
    measurements: tuple[ResourceMeasurement, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"measurements": [asdict(item) for item in self.measurements]}

    def value(self, name: str) -> float:
        item = next((m for m in self.measurements if m.resource_name == name), None)
        return float(item.value or 0) if item else 0.0


#: `RUSAGE_SELF` cuenta **todo el proceso**, no el hilo que mide.
#:
#: Los Living Workers corren en hilos dentro de un único proceso, así que la
#: ventana de medición de una tarea se quedaba también con la CPU que gastaban
#: las demás a la vez. Medido el 2026-08-26 sobre `resource_ledger`: **5.912 de
#: 6.484 entradas del día declaraban más CPU que duración** —media de 1,65
#: núcleos aparentes, pico de 4,7—, cosa imposible para un handler de un hilo.
#:
#: No es contabilidad decorativa: `cpu_minutes_daily` es una de las cuatro
#: `PRESSURE_LINES`, y al inflarse hasta 713 min sobre un presupuesto de 600
#: `policy()` ponía el organismo en `observe_only`, que excluye la clase `light`
#: —dedup, destilación y evidencia, o sea la cadena de aprendizaje entera—. El
#: gobernador frenaba de verdad por una cifra que no era real.
#:
#: `RUSAGE_THREAD` es Linux y conserva el desglose user/system. Donde no exista
#: se cae a `RUSAGE_SELF`, que es lo que había: sobreestimar es preferible a no
#: medir, pero se registra en `cpu_scope` para que la cifra sea interpretable.
_RUSAGE_THREAD = getattr(resource, "RUSAGE_THREAD", None)


def _cpu_propio() -> tuple[float, float, str]:
    """CPU del hilo que llama, o del proceso si la plataforma no distingue."""
    if _RUSAGE_THREAD is not None:
        try:
            uso = resource.getrusage(_RUSAGE_THREAD)
            return uso.ru_utime, uso.ru_stime, "thread"
        except (OSError, ValueError):
            pass
    uso = resource.getrusage(resource.RUSAGE_SELF)
    return uso.ru_utime, uso.ru_stime, "process"


class ResourceMeasurementCollector:
    def __init__(self) -> None:
        self.started_at = datetime.now(UTC).isoformat()
        self.started_wall = time.monotonic()
        self.self_utime_before, self.self_stime_before, self.cpu_scope = _cpu_propio()
        # Los hijos siguen siendo del proceso: `RUSAGE_CHILDREN` no se desglosa
        # por hilo. Un subproceso lanzado por otra tarea a la vez sigue cayendo
        # aquí, pero son raros y acotados frente a la CPU propia.
        self.children_before = resource.getrusage(resource.RUSAGE_CHILDREN)

    def finish(self) -> ResourceUsageReceipt:
        finished_at = datetime.now(UTC).isoformat()
        self_utime_after, self_stime_after, _ = _cpu_propio()
        children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        # `ru_maxrss` es el pico de residente **del proceso** por definición: no
        # existe una versión por hilo, porque la memoria no se reparte por hilo.
        # Se lee aparte para que el cambio de ámbito de la CPU no lo arrastre.
        self_after = resource.getrusage(resource.RUSAGE_SELF)
        measured = {
            "wall_time": (
                time.monotonic() - self.started_wall,
                "seconds",
                "time.monotonic",
            ),
            "cpu_user": (
                self_utime_after
                - self.self_utime_before
                + children_after.ru_utime
                - self.children_before.ru_utime,
                "seconds",
                f"resource.getrusage[{self.cpu_scope}]",
            ),
            "cpu_system": (
                self_stime_after
                - self.self_stime_before
                + children_after.ru_stime
                - self.children_before.ru_stime,
                "seconds",
                f"resource.getrusage[{self.cpu_scope}]",
            ),
            "peak_rss": (
                float(max(self_after.ru_maxrss, children_after.ru_maxrss)) / 1024,
                "MiB",
                "resource.getrusage",
            ),
        }
        items = [
            ResourceMeasurement(
                name,
                max(0.0, value),
                unit,
                "measured",
                source,
                self.started_at,
                finished_at,
            )
            for name, (value, unit, source) in measured.items()
        ]
        for name, unit in (
            ("disk_bytes_read", "bytes"),
            ("disk_bytes_written", "bytes"),
            ("network_sent", "bytes"),
            ("network_received", "bytes"),
            ("gpu_memory_peak", "MiB"),
            ("gpu_utilization", "percent"),
            ("input_tokens", "tokens"),
            ("output_tokens", "tokens"),
        ):
            items.append(
                ResourceMeasurement(
                    name,
                    None,
                    unit,
                    "unavailable",
                    "not_instrumented",
                    self.started_at,
                    finished_at,
                )
            )
        return ResourceUsageReceipt(tuple(items))


class ResourceLedger:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        budget: dict[str, float] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.budget = {**load_runtime_budget(), **(budget or {})}
        migration = (
            Path(__file__).resolve().parents[1]
            / "memory/migrations/009_runtime_resilience.sql"
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))
            measurements = (
                Path(__file__).resolve().parents[1]
                / "memory/migrations/018_resource_measurements.sql"
            )
            conn.executescript(measurements.read_text(encoding="utf-8"))

    def record_usage(
        self,
        *,
        task_id: str | None,
        worker_id: str | None,
        usage: ResourceUsageReceipt,
        success: bool,
        neuron_id: str | None = None,
        model: str | None = None,
        task_class: str = "general",
    ) -> int:
        entry_id = self.record(
            task_id=task_id,
            worker_id=worker_id,
            neuron_id=neuron_id,
            cpu_seconds=usage.value("cpu_user") + usage.value("cpu_system"),
            ram_peak_mb=usage.value("peak_rss"),
            duration_seconds=usage.value("wall_time"),
            model=model,
            success=success,
            task_class=task_class,
            _persist_caller_measurements=False,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """INSERT INTO resource_measurements
                (ledger_entry_id,resource_name,value,unit,measurement_type,source,started_at,finished_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                [(entry_id, *asdict(item).values()) for item in usage.measurements],
            )
        return entry_id

    def record(
        self,
        *,
        task_id: str | None,
        worker_id: str | None,
        neuron_id: str | None = None,
        cpu_seconds: float | None = None,
        gpu_seconds: float | None = None,
        ram_peak_mb: float | None = None,
        vram_peak_mb: float | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        network_bytes: int | None = None,
        disk_bytes_read: int | None = None,
        disk_bytes_written: int | None = None,
        duration_seconds: float | None = None,
        model: str | None = None,
        estimated_energy_wh: float | None = None,
        temperature_peak_c: float | None = None,
        success: bool,
        task_class: str = "general",
        _persist_caller_measurements: bool = True,
    ) -> int:
        now = datetime.now(UTC)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO resource_ledger(task_id,worker_id,neuron_id,recorded_day,cpu_seconds,gpu_seconds,
                ram_peak_mb,vram_peak_mb,tokens_input,tokens_output,network_bytes,disk_bytes_read,disk_bytes_written,
                duration_seconds,model,estimated_energy_wh,temperature_peak_c,success,task_class,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    worker_id,
                    neuron_id,
                    now.date().isoformat(),
                    max(0, cpu_seconds or 0),
                    max(0, gpu_seconds or 0),
                    max(0, ram_peak_mb or 0),
                    max(0, vram_peak_mb or 0),
                    max(0, tokens_input or 0),
                    max(0, tokens_output or 0),
                    max(0, network_bytes or 0),
                    max(0, disk_bytes_read or 0),
                    max(0, disk_bytes_written or 0),
                    max(0, duration_seconds or 0),
                    model,
                    max(0, estimated_energy_wh or 0),
                    temperature_peak_c,
                    int(success),
                    task_class,
                    now.isoformat(),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("resource_ledger_insert_missing_id")
            entry_id = int(cursor.lastrowid or -1)
            if _persist_caller_measurements:
                caller_values = {
                    "cpu_seconds": (cpu_seconds, "seconds"),
                    "gpu_seconds": (gpu_seconds, "seconds"),
                    "ram_peak": (ram_peak_mb, "MiB"),
                    "vram_peak": (vram_peak_mb, "MiB"),
                    "input_tokens": (tokens_input, "tokens"),
                    "output_tokens": (tokens_output, "tokens"),
                    "network_bytes": (network_bytes, "bytes"),
                    "disk_bytes_read": (disk_bytes_read, "bytes"),
                    "disk_bytes_written": (disk_bytes_written, "bytes"),
                    "wall_time": (duration_seconds, "seconds"),
                    "estimated_energy": (estimated_energy_wh, "Wh"),
                    "temperature_peak": (temperature_peak_c, "celsius"),
                }
                conn.executemany(
                    """INSERT INTO resource_measurements
                    (ledger_entry_id,resource_name,value,unit,measurement_type,source,started_at,finished_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    [
                        (
                            entry_id,
                            name,
                            float(value),
                            unit,
                            "estimated",
                            "caller_reported",
                            now.isoformat(),
                            now.isoformat(),
                        )
                        for name, (value, unit) in caller_values.items()
                        if value is not None
                    ],
                )
            return entry_id

    def daily_usage(self, day: str | None = None) -> dict[str, float]:
        day = day or datetime.now(UTC).date().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(cpu_seconds),0),COALESCE(SUM(gpu_seconds),0),
                COALESCE(SUM(network_bytes),0),COALESCE(SUM(disk_bytes_written),0),
                COALESCE(SUM(task_class='research'),0),COALESCE(SUM(task_class='deep_evaluation'),0),
                COALESCE(SUM(task_class='model_install'),0) FROM resource_ledger WHERE recorded_day=?""",
                (day,),
            ).fetchone()
        assert row is not None
        return {
            "cpu_minutes_daily": row[0] / 60,
            "gpu_minutes_daily": row[1] / 60,
            "network_mb_daily": row[2] / 1024**2,
            "new_storage_mb_daily": row[3] / 1024**2,
            "research_tasks_daily": float(row[4]),
            "deep_evaluations_daily": float(row[5]),
            "model_installs_daily": float(row[6]),
        }

    def quotas(self, usage: dict[str, float] | None = None) -> dict[str, Any]:
        """Estado de cada cupo por clase: gastado, límite y si queda sitio.

        Se expone además de consumirse internamente porque «esta clase está
        parada» y «esta clase agotó su cupo» son dos hechos distintos, y sin el
        segundo la observabilidad no puede decir cuál de los dos ocurre.
        """
        usage = usage if usage is not None else self.daily_usage()
        estado: dict[str, Any] = {}
        for key, task_class in QUOTA_LINES.items():
            limit = float(self.budget.get(key, 0.0))
            used = float(usage.get(key, 0.0))
            estado[task_class] = {
                "line": key,
                "used": used,
                "limit": limit,
                "remaining": max(0.0, limit - used),
                "ratio": (used / limit) if limit > 0 else 1.0,
                "exhausted": used >= limit if limit > 0 else True,
            }
        return estado

    def policy(self) -> dict[str, Any]:
        usage = self.daily_usage()
        ratios = {
            key: usage[key] / limit if limit > 0 else 1.0
            for key, limit in self.budget.items()
            if key in PRESSURE_LINES
        }
        cupos = self.quotas(usage)
        peak = max(ratios.values(), default=0.0)
        if peak >= 1:
            mode, allowed = "observe_only", {"heartbeat", "safety", "maintenance"}
        elif peak >= 0.95:
            mode, allowed = (
                "critical_maintenance",
                {"heartbeat", "safety", "maintenance"},
            )
        elif peak >= 0.85:
            mode, allowed = (
                "research_suspended",
                {"heartbeat", "safety", "maintenance", "light"},
            )
        elif peak >= 0.70:
            mode, allowed = (
                "cost_reduced",
                {"heartbeat", "safety", "maintenance", "light", "research"},
            )
        else:
            mode, allowed = (
                "normal",
                {
                    "heartbeat",
                    "safety",
                    "maintenance",
                    "light",
                    "research",
                    "deep_evaluation",
                    "model_install",
                },
            )
        # La escalera dice qué clases tolera la presión física; el cupo dice
        # cuáles ya gastaron su permiso del día. Una clase corre si pasa ambas.
        agotadas = {name for name, q in cupos.items() if q["exhausted"]}
        return {
            "mode": mode,
            "peak_ratio": peak,
            "pressure_ratios": ratios,
            "usage": usage,
            "budget": self.budget,
            "quotas": cupos,
            "exhausted_quotas": sorted(agotadas),
            "allowed_classes": sorted(allowed - agotadas),
        }

    def allows(self, task_class: str) -> bool:
        return task_class in self.policy()["allowed_classes"]
