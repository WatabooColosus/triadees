"""T-024 — Integración Final: validación end-to-end de todos los subsistemas
de Tríade Ω working together."""

import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    import hashlib
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS integration_runs (
    run_id         TEXT PRIMARY KEY,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    status         TEXT DEFAULT 'running',
    tests_total    INTEGER DEFAULT 0,
    tests_passed   INTEGER DEFAULT 0,
    tests_failed   INTEGER DEFAULT 0,
    results_json   TEXT DEFAULT '[]',
    summary        TEXT DEFAULT '',
    duration_ms    REAL DEFAULT 0.0
);
CREATE TABLE IF NOT EXISTS integration_tests (
    test_id        TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    test_name      TEXT NOT NULL,
    subsystem      TEXT NOT NULL,
    status         TEXT DEFAULT 'pending',
    duration_ms    REAL DEFAULT 0.0,
    details_json   TEXT DEFAULT '{}',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_it_run ON integration_tests(run_id);
"""


class IntegrationValidator:
    """Validación end-to-end de todos los subsistemas de Tríade Ω."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def run_full_validation(self) -> dict:
        run_id = _gen_id("intrun")
        now = utc_now()
        t0 = time.time()

        self._conn.execute(
            "INSERT INTO integration_runs (run_id, started_at, status) VALUES (?,?,?)",
            (run_id, now, "running"),
        )

        tests = [
            ("constitution_check", "constitution", self._test_constitution),
            ("system_monitor", "monitor", self._test_monitor),
            ("scheduler_basic", "scheduler", self._test_scheduler),
            ("tool_registry", "tool_registry", self._test_tool_registry),
            ("federation_trust", "federation", self._test_federation),
            ("model_router", "models", self._test_model_router),
            ("neuron_training", "neuron_factory", self._test_neuron_training),
            ("causal_learning", "learning", self._test_causal_learning),
            ("quality_composite", "evaluation", self._test_quality),
            ("triadeos_cycle", "triadeos", self._test_triadeos),
            ("autonomous_routine", "autonomous", self._test_autonomous),
        ]

        results = []
        passed = 0
        failed = 0

        for test_name, subsystem, test_fn in tests:
            test_id = _gen_id("itest")
            t_start = time.time()
            status = "pass"
            details = {}
            try:
                details = test_fn()
            except Exception as e:
                status = "fail"
                details = {"error": str(e)}

            dur = (time.time() - t_start) * 1000
            if status == "pass":
                passed += 1
            else:
                failed += 1

            result = {
                "test_id": test_id, "name": test_name,
                "subsystem": subsystem, "status": status,
                "duration_ms": round(dur, 2), "details": details,
            }
            results.append(result)

            self._conn.execute(
                """INSERT INTO integration_tests
                   (test_id, run_id, test_name, subsystem, status,
                    duration_ms, details_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (test_id, run_id, test_name, subsystem, status,
                 round(dur, 2), json.dumps(details, default=str), utc_now()),
            )

        total_dur = (time.time() - t0) * 1000
        overall = "passed" if failed == 0 else "failed"
        summary = f"{passed}/{len(tests)} tests passed"

        self._conn.execute(
            """UPDATE integration_runs
               SET status=?, finished_at=?, tests_total=?, tests_passed=?,
                   tests_failed=?, results_json=?, summary=?, duration_ms=?
               WHERE run_id=?""",
            (overall, utc_now(), len(tests), passed, failed,
             json.dumps(results, default=str), summary,
             round(total_dur, 2), run_id),
        )
        self._conn.commit()

        return {
            "run_id": run_id, "status": overall,
            "total": len(tests), "passed": passed, "failed": failed,
            "duration_ms": round(total_dur, 2), "results": results,
        }

    def get_run(self, run_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM integration_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def run_history(self, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM integration_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def doctor(self) -> dict:
        runs = self._conn.execute("SELECT COUNT(*) as c FROM integration_runs").fetchone()["c"]
        passed = self._conn.execute("SELECT COUNT(*) as c FROM integration_runs WHERE status='passed'").fetchone()["c"]
        return {"total_runs": runs, "passed": passed, "failed": runs - passed}

    # ─── individual tests ───

    def _test_constitution(self) -> dict:
        from triade.constitution.enforcer import ConstitutionEnforcer
        ce = ConstitutionEnforcer()
        result = ce.check_article("central", 1, {"modifies_identity": False})
        assert result["status"] == "pass", f"Constitution check failed: {result}"
        return {"article_1": "pass"}

    def _test_monitor(self) -> dict:
        from triade.core.system_monitor import SystemMonitor
        mon = SystemMonitor()
        snap = mon.snapshot({"cpu_percent": 50.0, "ram_percent": 60.0, "disk_percent": 40.0})
        assert snap["snapshot_id"].startswith("snap-")
        return {"snapshot": snap["snapshot_id"]}

    def _test_scheduler(self) -> dict:
        from triade.workers.advanced_scheduler import AdvancedScheduler
        sch = AdvancedScheduler()
        q = sch.check_quota("pulse_check")
        assert q["allowed"]
        return {"quota_ok": True}

    def _test_tool_registry(self) -> dict:
        from triade.sandbox.enhanced_tool_registry import EnhancedToolRegistry, ToolContract
        etr = EnhancedToolRegistry()
        tc = ToolContract(tool_id="test_int", name="IntTest", category="system")
        etr.register(tc)
        t = etr.get("test_int")
        assert t is not None
        return {"registered": True}

    def _test_federation(self) -> dict:
        from triade.federation.federation_advanced import FederationAdvanced
        fed = FederationAdvanced()
        trust = fed.update_trust("test_node", success=True, latency_ms=50.0)
        assert trust["trust_score"] > 0.4
        return {"trust_score": trust["trust_score"]}

    def _test_model_router(self) -> dict:
        from triade.models.smart_router import SmartModelRouter
        router = SmartModelRouter()
        decision = router.select("central", difficulty="medium", available_ram_gb=31.0)
        assert decision["model"]
        return {"selected_model": decision["model"]}

    def _test_neuron_training(self) -> dict:
        from triade.neuron_factory.training import TrainingPipeline
        tp = TrainingPipeline()
        ds = tp.create_dataset("int_test", "test", "int-ds", [
            {"input": {"x": 1}, "expected": {"x": 1}},
        ])
        run = tp.run_episodes(ds["dataset_id"], "int_test")
        assert run["avg_score"] >= 0.0
        return {"avg_score": run["avg_score"]}

    def _test_causal_learning(self) -> dict:
        from triade.learning.causal_learning import CausalLearningEngine
        cle = CausalLearningEngine()
        n = cle.add_node("test_event", "event", "test")
        assert n["node_id"]
        return {"node_created": True}

    def _test_quality(self) -> dict:
        from triade.evaluation.advanced_evaluation import QualityCompositor
        qc = QualityCompositor()
        r = qc.evaluate("int_test", {
            "correctness": 0.9, "completeness": 0.8,
            "performance": 0.8, "security": 0.9,
            "maintainability": 0.8, "documentation": 0.7,
        })
        assert r["overall_score"] > 0.5
        return {"score": r["overall_score"]}

    def _test_triadeos(self) -> dict:
        from triade.os.triadeos_complete import TriadeOSComplete
        os = TriadeOSComplete()
        cycle = os.start_cycle()
        result = os.run_full_check(cycle["cycle_id"])
        assert result["healthy"] > 0
        return {"healthy_subsystems": result["healthy"]}

    def _test_autonomous(self) -> dict:
        from triade.os.autonomous_routines import AutonomousRoutines
        ar = AutonomousRoutines()
        routine = ar.create_routine("health_maintenance")
        result = ar.execute_routine(routine["routine_id"])
        assert result["status"] == "completed"
        return {"routine_completed": True}
