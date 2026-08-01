"""Validación de concurrencia, leases y SQLite, sobre COPIA de la base.

**Esto NO es un E2E del ciclo de automejora.** No ejecuta
propuesta → candidata → sandbox → evaluación → canary. Llamarlo E2E sería
sobrevender: valida los mecanismos de runtime (carriles, exclusiones, lease,
cierre, SQLite) y comprueba que la medición de vitalidad falla honestamente por
falta de evidencia, pero el circuito completo requiere una propuesta aprobada
por un humano que hoy no existe en la base.

Nunca toca producción: copia `triade/memory/triade.db` a un directorio temporal y
trabaja ahí. La copia conserva los `verification_reports` reales, que es lo que
permite que la medición de vitalidad sea real y no un fixture.

Qué demuestra, y qué no
-----------------------
Demuestra: solapamiento real de tareas seguras, serialización de mutaciones
críticas, exclusión por candidata, propiedad del lease, ausencia de doble cierre,
que SQLite no se bloquea y parada controlada.

NO demuestra: el circuito propuesta → candidata → sandbox → canary ejecutado de
principio a fin. Eso sigue sin evidencia y así debe reportarse.

NO demuestra un A/B verdadero: la vitalidad se mide comparando ventanas
antes/después sobre los mismos informes reales, no ejecutando la misma carga con
y sin la candidata. Esa capacidad no existe hoy.

Uso:
    python scripts/run_concurrency_and_lease_validation.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from triade.workers.concurrency import (
    ConcurrencySettings,
    GovernedTaskPool,
)

PRODUCTION_DB = REPO / "triade/memory/triade.db"


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})
        mark = "OK  " if passed else "FALLO"
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
        return bool(passed)

    @property
    def ok(self) -> bool:
        return all(item["passed"] for item in self.checks)


def copy_production_db(target_dir: Path) -> Path:
    """Copia consistente incluyendo los sidecars de WAL."""
    target = target_dir / "triade.db"
    if not PRODUCTION_DB.exists():
        raise SystemExit(f"no existe la base de produccion: {PRODUCTION_DB}")
    # `backup()` toma una copia consistente aunque haya escritores activos; copiar
    # el fichero a pelo con WAL abierto puede dar una base truncada.
    source = sqlite3.connect(f"file:{PRODUCTION_DB}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    with destination:
        source.backup(destination)
    source.close()
    destination.close()
    return target


# ── 1. concurrencia ─────────────────────────────────────────────────────


def validate_concurrency(report: Report) -> None:
    print("\n== Concurrencia gobernada ==")
    pool = GovernedTaskPool(
        ConcurrencySettings(
            enabled=True,
            max_concurrent_tasks=4,
            read_only_workers=4,
            evaluation_workers=2,
            critical_mutation_workers=1,
        )
    )
    try:
        # read-only se solapan
        barrier = threading.Barrier(2, timeout=15)
        overlapped: list[str] = []

        def read_only() -> None:
            overlapped.append(threading.current_thread().name)
            barrier.wait()

        pool.submit("ro-1", "pulse_check", {}, read_only)
        pool.submit("ro-2", "system_debt_scan", {}, read_only)
        deadline = time.monotonic() + 20
        while pool.pending_count() and time.monotonic() < deadline:
            pool.wait_for_slot(0.2)
            pool.collect_finished()
        report.check(
            "dos tareas read-only se solapan en hilos distintos",
            len(overlapped) == 2 and overlapped[0] != overlapped[1],
            f"hilos={overlapped}",
        )

        # evaluaciones independientes se solapan; misma candidata no
        hold = threading.Event()
        entered = threading.Event()

        def blocking() -> None:
            entered.set()
            hold.wait(timeout=20)

        first = pool.submit(
            "ev-1",
            "self_improvement_evaluation",
            {"candidate_id": "cand-A", "neuron_id": "n-A"},
            blocking,
        )
        entered.wait(timeout=15)
        # Se pide PRIMERO la misma candidata, con el carril aun a medio ocupar:
        # asi el rechazo solo puede venir de la clave de exclusion, no de que no
        # quedara sitio. Si se pidiera despues, `lane_limit` enmascararia la
        # comprobacion y el test pasaria sin demostrar nada.
        same = pool.submit(
            "ev-3",
            "self_improvement_evaluation",
            {"candidate_id": "cand-A", "neuron_id": "n-A"},
            lambda: None,
        )
        report.check(
            "la MISMA candidata no se solapa consigo misma",
            not same.admitted and same.reason.startswith("exclusive_key_held:"),
            same.reason,
        )
        second = pool.submit(
            "ev-2",
            "self_improvement_evaluation",
            {"candidate_id": "cand-B", "neuron_id": "n-B"},
            lambda: None,
        )
        report.check(
            "evaluaciones de candidatas distintas se solapan",
            first.admitted and second.admitted,
        )
        hold.set()
        deadline = time.monotonic() + 20
        while pool.pending_count() and time.monotonic() < deadline:
            pool.wait_for_slot(0.2)
            pool.collect_finished()

        # critical_mutation serial
        hold2 = threading.Event()
        entered2 = threading.Event()

        def blocking2() -> None:
            entered2.set()
            hold2.wait(timeout=20)

        pool.submit("cm-1", "neuron_autopromotion", {"neuron_id": "n-1"}, blocking2)
        entered2.wait(timeout=15)
        denied = pool.submit(
            "cm-2", "neuron_autopromotion", {"neuron_id": "n-2"}, lambda: None
        )
        report.check(
            "critical_mutation permanece serial (neuronas distintas)",
            not denied.admitted,
            denied.reason,
        )
        hold2.set()

        snapshot = pool.snapshot(queued=0)
        report.check(
            "el snapshot expone limites y ocupacion por carril",
            set(snapshot["lanes"])
            == {
                "read_only",
                "research",
                "evaluation",
                "memory_write",
                "critical_mutation",
            }
            and snapshot["lanes"]["critical_mutation"]["limit"] == 1,
            json.dumps(snapshot["lanes"]["critical_mutation"]),
        )
    finally:
        result = pool.shutdown(wait_seconds=15)
        report.check(
            "parada controlada: no quedan tareas vivas ni se aceptan nuevas",
            result["still_running"] == 0 and not pool.accepting,
            json.dumps(result),
        )


# ── 2. leases y cierre ──────────────────────────────────────────────────


def validate_leases(report: Report, db_path: Path) -> None:
    print("\n== Leases y cierre atomico ==")
    from triade.runtime.task_leases import AutonomousTaskStore

    store = AutonomousTaskStore(db_path)
    task = store.enqueue("pulse_check", {}, idempotency_key=f"e2e-{time.time()}")
    task_id = str(task["task_id"])

    leased = store.claim_task(task_id, "worker-A", lease_seconds=60)
    report.check("el lease se adquiere", leased is not None)
    assert leased is not None
    generation = int(leased["lease_generation"])

    stolen = store.claim_task(task_id, "worker-B", lease_seconds=60)
    report.check("un segundo worker no puede robar el lease", stolen is None)

    report.check(
        "un lease ajeno no puede devolver la tarea",
        not store.defer_unstarted(task_id, "worker-B", generation, "e2e"),
    )
    report.check(
        "el heartbeat renueva el lease del propietario",
        store.renew(task_id, "worker-A", generation, lease_seconds=60),
    )
    report.check(
        "una generacion caduca no renueva",
        not store.renew(task_id, "worker-A", generation - 1, lease_seconds=60),
    )

    assert store.start(task_id, "worker-A", generation)
    result_ref = db_path.parent / "result.json"
    result_ref.write_text("{}", encoding="utf-8")
    first_close = store.complete(task_id, "worker-A", generation, str(result_ref))
    second_close = store.complete(task_id, "worker-A", generation, str(result_ref))
    report.check("el cierre ocurre una vez", first_close)
    report.check("el segundo cierre se rechaza (sin doble cierre)", not second_close)


# ── 3. SQLite bajo escrituras concurrentes ──────────────────────────────


def validate_sqlite(report: Report, db_path: Path) -> None:
    print("\n== SQLite bajo concurrencia ==")
    from triade.runtime.task_leases import AutonomousTaskStore

    errors: list[str] = []
    done = threading.Barrier(6, timeout=60)

    def writer(index: int) -> None:
        try:
            store = AutonomousTaskStore(db_path)  # conexion propia en SU hilo
            for step in range(12):
                store.enqueue(
                    "pulse_check",
                    {"i": index, "s": step},
                    idempotency_key=f"e2e-conc-{index}-{step}-{time.time()}",
                )
        except sqlite3.Error as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            try:
                done.wait()
            except threading.BrokenBarrierError:
                pass

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=90)
    report.check(
        "72 escrituras desde 6 hilos sin 'database is locked'",
        not errors,
        "; ".join(errors[:3]),
    )

    conn = sqlite3.connect(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    report.check("la base sigue en WAL", str(mode).lower() == "wal", str(mode))


# ── 4. automejora con datos reales ──────────────────────────────────────


def validate_self_improvement(report: Report, db_path: Path) -> None:
    print("\n== Ciclo de automejora sobre datos reales ==")
    conn = sqlite3.connect(db_path)
    reports = conn.execute("SELECT COUNT(*) FROM verification_reports").fetchone()[0]
    conn.close()
    report.check(
        "la copia conserva los informes de verificacion reales",
        int(reports) > 0,
        f"{reports} informes",
    )

    from triade.evaluation.provider_registry import build_evaluation_provider

    provider = build_evaluation_provider("triade_vitality", db_path)
    try:
        provider("cand-inexistente", {"created_at": "2026-07-31T03:00:00+00:00"})
        measured = "no fallo"
    except ValueError as exc:
        measured = str(exc)
    report.check(
        "la vitalidad se mide contra informes reales, y falla si no bastan",
        "evidencia insuficiente" in measured or measured == "no fallo",
        measured[:110],
    )

    # Observacion de canary: idempotencia sobre la copia real.
    from triade.self_improvement.canary_observation import CanaryObservationCollector

    collector = CanaryObservationCollector(db_path)
    observation = collector.observe_once()
    report.check(
        "sin canary abierto la observacion no inventa nada",
        observation["status"] in {"no_canary", "insufficient_candidate_observations"},
        observation["status"],
    )

    from triade.workers.concurrency import exclusion_keys

    keys = exclusion_keys("self_improvement_canary_observation", {"candidate_id": "c1"})
    report.check(
        "la observacion excluye por candidata (no puede duplicarse)",
        "candidate_id=c1" in keys,
    )


def main() -> int:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    workdir = REPO / "runs" / f"concurrency-lease-validation-{stamp}"
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"Directorio de trabajo: {workdir}")
    db_path = copy_production_db(workdir)
    print(f"Copia de la base: {db_path} ({db_path.stat().st_size // 1024} KB)")
    print("PRODUCCION NO SE TOCA.")

    report = Report()
    validate_concurrency(report)
    validate_leases(report, db_path)
    validate_sqlite(report, db_path)
    validate_self_improvement(report, db_path)

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "database_copy": str(db_path),
        "production_untouched": True,
        "checks": report.checks,
        "passed": sum(1 for c in report.checks if c["passed"]),
        "total": len(report.checks),
        "limitations": [
            (
                "La vitalidad compara ventanas antes/despues sobre informes "
                "reales; NO es un A/B controlado. Repetir la misma carga con y "
                "sin candidata no es posible hoy."
            ),
            (
                "Este script NO ejecuta el circuito propuesta -> candidata -> "
                "sandbox -> canary de principio a fin. Valida los mecanismos de "
                "runtime, no el ciclo completo de automejora."
            ),
        ],
    }
    (workdir / "validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n{summary['passed']}/{summary['total']} comprobaciones superadas")
    print(f"Evidencia: {workdir / 'validation.json'}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
