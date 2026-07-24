"""T-015 — Evaluación avanzada: benchmark execution, mutation testing,
regression detection en tiempo real, y quality metrics compuestas."""

import hashlib
import json
import random
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS benchmark_runs (
    run_id         TEXT PRIMARY KEY,
    suite_name     TEXT NOT NULL,
    target         TEXT NOT NULL,
    cases_total    INTEGER DEFAULT 0,
    cases_passed   INTEGER DEFAULT 0,
    score          REAL DEFAULT 0.0,
    duration_ms    REAL DEFAULT 0.0,
    results_json   TEXT DEFAULT '[]',
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mutation_tests (
    mutation_id    TEXT PRIMARY KEY,
    target_file    TEXT NOT NULL,
    mutation_type  TEXT NOT NULL,
    original_code  TEXT DEFAULT '',
    mutated_code   TEXT DEFAULT '',
    test_name      TEXT DEFAULT '',
    killed         INTEGER DEFAULT 0,
    survived       INTEGER DEFAULT 0,
    timeout        INTEGER DEFAULT 0,
    strength       REAL DEFAULT 0.0,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS regression_events (
    event_id       TEXT PRIMARY KEY,
    metric_name    TEXT NOT NULL,
    baseline_value REAL NOT NULL,
    current_value  REAL NOT NULL,
    delta          REAL NOT NULL,
    severity       TEXT DEFAULT 'low',
    status         TEXT DEFAULT 'open',
    detected_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_composites (
    composite_id   TEXT PRIMARY KEY,
    target_name    TEXT NOT NULL,
    dimensions_json TEXT DEFAULT '{}',
    overall_score  REAL DEFAULT 0.0,
    grade          TEXT DEFAULT 'F',
    passed         INTEGER DEFAULT 0,
    failed         INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL
);
"""


class BenchmarkRunner:
    """Ejecuta benchmarks automatizados contra suites definidas."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def run_suite(
        self,
        suite_name: str,
        target: str,
        cases: list[dict[str, Any]],
        evaluator: Callable | None = None,
    ) -> dict:
        now = utc_now()
        run_id = _gen_id("bench")
        import time
        t0 = time.time()
        results = []
        passed = 0
        scores = []

        for i, case in enumerate(cases):
            case_id = case.get("id", f"case_{i}")
            expected = case.get("expected")
            inp = case.get("input", {})

            if evaluator:
                try:
                    actual = evaluator(inp)
                    score = _score_match(actual, expected)
                except Exception as e:
                    actual = {"error": str(e)}
                    score = 0.0
            else:
                actual = inp
                score = _score_match(inp, expected)

            ok = score >= 0.7
            if ok:
                passed += 1
            scores.append(score)
            results.append({
                "case_id": case_id, "score": score,
                "passed": ok, "input": inp, "expected": expected,
                "actual": actual,
            })

        dur = (time.time() - t0) * 1000
        avg_score = round(sum(scores) / max(len(scores), 1), 4)

        self._conn.execute(
            """INSERT INTO benchmark_runs
               (run_id, suite_name, target, cases_total, cases_passed,
                score, duration_ms, results_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (run_id, suite_name, target, len(cases), passed,
             avg_score, round(dur, 2), json.dumps(results, default=str), now),
        )
        self._conn.commit()
        return {
            "run_id": run_id, "suite": suite_name, "target": target,
            "total": len(cases), "passed": passed, "score": avg_score,
            "duration_ms": round(dur, 2),
        }

    def get(self, run_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM benchmark_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def compare_runs(self, run_id_a: str, run_id_b: str) -> dict:
        a = dict(self._conn.execute(
            "SELECT * FROM benchmark_runs WHERE run_id=?", (run_id_a,)
        ).fetchone() or {})
        b = dict(self._conn.execute(
            "SELECT * FROM benchmark_runs WHERE run_id=?", (run_id_b,)
        ).fetchone() or {})
        if not a or not b:
            return {"error": "run not found"}
        delta = round(b.get("score", 0) - a.get("score", 0), 4)
        return {
            "run_a": run_id_a, "run_b": run_id_b,
            "score_a": a.get("score", 0), "score_b": b.get("score", 0),
            "delta": delta, "improved": delta > 0,
        }

    def doctor(self) -> dict:
        runs = self._conn.execute("SELECT COUNT(*) as c FROM benchmark_runs").fetchone()["c"]
        return {"benchmark_runs": runs}


class MutationTester:
    """Mutation testing: genera mutantes del código y verifica si los tests los detectan."""

    MUTATION_OPERATORS = [
        ("negate_condition", "if (", "if not ("),
        ("swap_operators", "==", "!="),
        ("remove_return", "return ", "# return "),
        ("change_constant", "= 0", "= 1"),
        ("empty_function", "pass", "raise ValueError('mutant')"),
    ]

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def generate_mutations(self, code: str, target_file: str) -> list[dict]:
        mutations = []
        for op_name, pattern, replacement in self.MUTATION_OPERATORS:
            if pattern in code:
                mutated = code.replace(pattern, replacement, 1)
                mutations.append({
                    "mutation_type": op_name,
                    "original": code[:200],
                    "mutated": mutated[:200],
                    "target_file": target_file,
                })
        return mutations

    def record_mutation(
        self, target_file: str, mutation_type: str,
        original_code: str, mutated_code: str,
        test_name: str, killed: bool, survived: bool = False,
        timeout: bool = False,
    ) -> dict:
        mutation_id = _gen_id("mut")
        total = 1 if killed else (1 if survived else 0)
        strength = 1.0 if killed else 0.0

        self._conn.execute(
            """INSERT INTO mutation_tests
               (mutation_id, target_file, mutation_type, original_code,
                mutated_code, test_name, killed, survived, timeout,
                strength, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (mutation_id, target_file, mutation_type, original_code,
             mutated_code, test_name, 1 if killed else 0,
             1 if survived else 0, 1 if timeout else 0,
             strength, utc_now()),
        )
        self._conn.commit()
        return {"mutation_id": mutation_id, "killed": killed, "strength": strength}

    def mutation_score(self, target_file: str) -> dict:
        rows = self._conn.execute(
            "SELECT * FROM mutation_tests WHERE target_file=?", (target_file,)
        ).fetchall()
        total = len(rows)
        killed = sum(1 for r in rows if r["killed"])
        survived = sum(1 for r in rows if r["survived"])
        score = killed / max(total, 1)
        return {
            "target_file": target_file,
            "total_mutations": total, "killed": killed,
            "survived": survived, "score": round(score, 4),
        }

    def doctor(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) as c FROM mutation_tests").fetchone()["c"]
        killed = self._conn.execute("SELECT COUNT(*) as c FROM mutation_tests WHERE killed=1").fetchone()["c"]
        return {"total_mutations": total, "killed": killed,
                "score": round(killed / max(total, 1), 4)}


class RegressionDetector:
    """Detecta regresiones en tiempo real comparando valores baseline vs current."""

    SEVERITY_THRESHOLDS = {"low": 0.05, "medium": 0.10, "high": 0.20, "critical": 0.30}

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def check(self, metric_name: str, baseline: float, current: float) -> dict:
        delta = current - baseline
        rel_delta = abs(delta) / max(abs(baseline), 0.001)
        severity = "low"
        for sev, thresh in sorted(self.SEVERITY_THRESHOLDS.items(),
                                   key=lambda x: x[1], reverse=True):
            if rel_delta >= thresh:
                severity = sev
                break

        is_regression = delta < 0 and rel_delta >= 0.05
        event_id = None

        if is_regression:
            event_id = _gen_id("reg")
            self._conn.execute(
                """INSERT INTO regression_events
                   (event_id, metric_name, baseline_value, current_value,
                    delta, severity, detected_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (event_id, metric_name, baseline, current,
                 round(delta, 6), severity, utc_now()),
            )
            self._conn.commit()

        return {
            "metric": metric_name, "baseline": baseline, "current": current,
            "delta": round(delta, 6), "relative_delta": round(rel_delta, 4),
            "is_regression": is_regression, "severity": severity,
            "event_id": event_id,
        }

    def open_events(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM regression_events WHERE status='open' ORDER BY detected_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def resolve(self, event_id: str) -> dict:
        self._conn.execute(
            "UPDATE regression_events SET status='resolved' WHERE event_id=?",
            (event_id,),
        )
        self._conn.commit()
        return {"event_id": event_id, "status": "resolved"}

    def doctor(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) as c FROM regression_events").fetchone()["c"]
        open_events = self._conn.execute("SELECT COUNT(*) as c FROM regression_events WHERE status='open'").fetchone()["c"]
        return {"total_events": total, "open": open_events}


class QualityCompositor:
    """Calcula quality metrics compuestas multi-dimensión."""

    WEIGHTS = {
        "correctness": 0.30,
        "completeness": 0.20,
        "performance": 0.15,
        "security": 0.15,
        "maintainability": 0.10,
        "documentation": 0.10,
    }

    GRADES = [
        (0.95, "A+"), (0.90, "A"), (0.85, "A-"),
        (0.80, "B+"), (0.75, "B"), (0.70, "B-"),
        (0.65, "C+"), (0.60, "C"), (0.55, "C-"),
        (0.50, "D"), (0.0, "F"),
    ]

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def evaluate(self, target_name: str, dimensions: dict[str, float]) -> dict:
        composite_id = _gen_id("qcomp")
        now = utc_now()

        overall = sum(_clamp(dimensions.get(k, 0.0)) * w
                       for k, w in self.WEIGHTS.items())
        overall = round(_clamp(overall), 4)
        grade = "F"
        for thresh, g in self.GRADES:
            if overall >= thresh:
                grade = g
                break

        passed = sum(1 for v in dimensions.values() if v >= 0.7)
        failed = sum(1 for v in dimensions.values() if v < 0.7)

        self._conn.execute(
            """INSERT INTO quality_composites
               (composite_id, target_name, dimensions_json,
                overall_score, grade, passed, failed, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (composite_id, target_name, json.dumps(dimensions, default=str),
             overall, grade, passed, failed, now),
        )
        self._conn.commit()
        return {
            "composite_id": composite_id, "target": target_name,
            "dimensions": dimensions, "overall_score": overall,
            "grade": grade, "passed": passed, "failed": failed,
        }

    def history(self, target_name: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM quality_composites WHERE target_name=? ORDER BY created_at DESC",
            (target_name,),
        ).fetchall()
        return [dict(r) for r in rows]

    def doctor(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) as c FROM quality_composites").fetchone()["c"]
        avg = self._conn.execute("SELECT AVG(overall_score) as a FROM quality_composites").fetchone()["a"] or 0
        return {"total_evaluations": total, "avg_score": round(avg, 4)}


def _score_match(actual: dict, expected: dict | None) -> float:
    if not expected:
        return 1.0 if actual else 0.0
    if not actual:
        return 0.0
    matches = sum(1 for k, v in expected.items() if k in actual and actual[k] == v)
    return round(matches / max(len(expected), 1), 4)
