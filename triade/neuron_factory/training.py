"""T-008 — Formadora: pipeline de entrenamiento completo con datasets,
episodios, benchmarks, generalización, feedback loops, y ciclo de vida
de promoción/degradación/retiro."""

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


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS training_datasets (
    dataset_id    TEXT PRIMARY KEY,
    neuron_name   TEXT NOT NULL,
    domain        TEXT NOT NULL,
    name          TEXT NOT NULL,
    items_json    TEXT DEFAULT '[]',
    item_count    INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS training_episodes (
    episode_id    TEXT PRIMARY KEY,
    dataset_id    TEXT NOT NULL,
    neuron_name   TEXT NOT NULL,
    episode_index INTEGER DEFAULT 0,
    input_json    TEXT DEFAULT '{}',
    expected_json TEXT DEFAULT '{}',
    actual_json   TEXT DEFAULT '{}',
    score         REAL DEFAULT 0.0,
    duration_ms   REAL DEFAULT 0.0,
    status        TEXT DEFAULT 'pending',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ep_dataset ON training_episodes(dataset_id);
CREATE TABLE IF NOT EXISTS training_runs (
    run_id        TEXT PRIMARY KEY,
    neuron_name   TEXT NOT NULL,
    dataset_id    TEXT NOT NULL,
    episodes_total   INTEGER DEFAULT 0,
    episodes_passed  INTEGER DEFAULT 0,
    avg_score     REAL DEFAULT 0.0,
    benchmark_json TEXT DEFAULT '{}',
    generalization_json TEXT DEFAULT '{}',
    feedback_json TEXT DEFAULT '{}',
    status        TEXT DEFAULT 'running',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS neuron_lifecycle_actions (
    action_id     TEXT PRIMARY KEY,
    neuron_name   TEXT NOT NULL,
    action        TEXT NOT NULL,
    from_state    TEXT,
    to_state      TEXT,
    reason        TEXT DEFAULT '',
    metrics_json  TEXT DEFAULT '{}',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lc_neuron ON neuron_lifecycle_actions(neuron_name);
"""


class TrainingPipeline:
    """Pipeline completo de entrenamiento: dataset → episodios → benchmarks →
    generalización → feedback → ciclo de vida."""

    # Promotion thresholds
    MIN_AVG_SCORE = 0.75
    MIN_PASS_RATE = 0.80
    MIN_GENERALIZATION = 0.60

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    # ─── dataset management ───

    def create_dataset(
        self, neuron_name: str, domain: str, name: str,
        items: list[dict[str, Any]],
    ) -> dict:
        now = utc_now()
        dataset_id = _gen_id("ds")
        self._conn.execute(
            """INSERT INTO training_datasets
               (dataset_id, neuron_name, domain, name, items_json, item_count, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (dataset_id, neuron_name, domain, name,
             json.dumps(items, default=str), len(items), now),
        )
        self._conn.commit()
        return {"dataset_id": dataset_id, "item_count": len(items), "created_at": now}

    def get_dataset(self, dataset_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM training_datasets WHERE dataset_id=?", (dataset_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_datasets(self, neuron_name: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM training_datasets WHERE neuron_name=? ORDER BY created_at DESC",
            (neuron_name,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── training episodes ───

    def run_episodes(
        self,
        dataset_id: str,
        neuron_name: str,
        execute_fn: Any = None,
    ) -> dict:
        """Ejecuta episodios de entrenamiento sobre un dataset."""
        dataset = self.get_dataset(dataset_id)
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found")

        items = json.loads(dataset["items_json"]) if isinstance(dataset["items_json"], str) else dataset["items_json"]
        now = utc_now()
        run_id = _gen_id("trainrun")

        episodes = []
        scores = []
        for i, item in enumerate(items):
            ep_id = _gen_id("ep")
            inp = item.get("input", {})
            expected = item.get("expected", {})
            actual = {}
            score = 0.0
            dur = 0.0
            status = "pending"

            if execute_fn:
                import time
                t0 = time.time()
                try:
                    actual = execute_fn(inp)
                    dur = (time.time() - t0) * 1000
                    score = _score_match(actual, expected)
                    status = "pass" if score >= 0.7 else "fail"
                except Exception as e:
                    actual = {"error": str(e)}
                    dur = (time.time() - t0) * 1000
                    score = 0.0
                    status = "error"
            else:
                score = _score_match(inp, expected)
                status = "pass" if score >= 0.7 else "fail"
                actual = inp

            scores.append(score)
            ep = {
                "episode_id": ep_id,
                "dataset_id": dataset_id,
                "neuron_name": neuron_name,
                "episode_index": i,
                "input": inp,
                "expected": expected,
                "actual": actual,
                "score": score,
                "duration_ms": dur,
                "status": status,
            }
            episodes.append(ep)

            self._conn.execute(
                """INSERT INTO training_episodes
                   (episode_id, dataset_id, neuron_name, episode_index,
                    input_json, expected_json, actual_json,
                    score, duration_ms, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (ep_id, dataset_id, neuron_name, i,
                 json.dumps(inp, default=str), json.dumps(expected, default=str),
                 json.dumps(actual, default=str), score, dur, status, now),
            )

        avg_score = round(sum(scores) / max(len(scores), 1), 4)
        passed = sum(1 for s in scores if s >= 0.7)
        total = len(scores)

        self._conn.execute(
            """INSERT INTO training_runs
               (run_id, neuron_name, dataset_id, episodes_total,
                episodes_passed, avg_score, status, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (run_id, neuron_name, dataset_id, total, passed, avg_score, "completed", now),
        )
        self._conn.commit()

        return {
            "run_id": run_id,
            "neuron_name": neuron_name,
            "dataset_id": dataset_id,
            "episodes_total": total,
            "episodes_passed": passed,
            "avg_score": avg_score,
            "pass_rate": round(passed / max(total, 1), 4),
            "status": "completed",
        }

    # ─── benchmarks ───

    def benchmark(
        self, run_id: str, baseline_scores: dict[str, float] | None = None,
    ) -> dict:
        """Ejecuta benchmarks contra baseline y calcula deltas."""
        row = self._conn.execute(
            "SELECT * FROM training_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Run {run_id} not found")
        run = dict(row)
        baseline = baseline_scores or {}

        benchmark_result = {
            "run_id": run_id,
            "avg_score": run["avg_score"],
            "pass_rate": run["episodes_passed"] / max(run["episodes_total"], 1),
            "deltas": {},
        }
        for metric, base_val in baseline.items():
            current = run.get("avg_score", 0.0)
            benchmark_result["deltas"][metric] = round(current - base_val, 4)

        self._conn.execute(
            "UPDATE training_runs SET benchmark_json=? WHERE run_id=?",
            (json.dumps(benchmark_result, default=str), run_id),
        )
        self._conn.commit()
        return benchmark_result

    # ─── generalization testing ───

    def test_generalization(
        self,
        run_id: str,
        holdout_dataset_id: str,
        execute_fn: Any = None,
    ) -> dict:
        """Testea generalización con dataset de holdout."""
        holdout = self.get_dataset(holdout_dataset_id)
        if not holdout:
            raise ValueError(f"Holdout dataset {holdout_dataset_id} not found")

        items = json.loads(holdout["items_json"]) if isinstance(holdout["items_json"], str) else holdout["items_json"]
        scores = []
        for item in items:
            inp = item.get("input", {})
            expected = item.get("expected", {})
            if execute_fn:
                try:
                    actual = execute_fn(inp)
                    scores.append(_score_match(actual, expected))
                except Exception:
                    scores.append(0.0)
            else:
                scores.append(_score_match(inp, expected))

        gen_score = round(sum(scores) / max(len(scores), 1), 4)
        result = {
            "run_id": run_id,
            "holdout_dataset_id": holdout_dataset_id,
            "generalization_score": gen_score,
            "items_tested": len(scores),
            "passes_generalization": gen_score >= self.MIN_GENERALIZATION,
        }

        self._conn.execute(
            "UPDATE training_runs SET generalization_json=? WHERE run_id=?",
            (json.dumps(result, default=str), run_id),
        )
        self._conn.commit()
        return result

    # ─── feedback loops ───

    def record_feedback(
        self, run_id: str, feedback_type: str, details: dict,
    ) -> dict:
        """Registra feedback para un run de entrenamiento."""
        row = self._conn.execute(
            "SELECT feedback_json FROM training_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Run {run_id} not found")
        existing = json.loads(row["feedback_json"]) if row["feedback_json"] else {"items": []}
        if "items" not in existing:
            existing["items"] = []
        existing["items"].append({
            "type": feedback_type,
            "details": details,
            "timestamp": utc_now(),
        })

        self._conn.execute(
            "UPDATE training_runs SET feedback_json=? WHERE run_id=?",
            (json.dumps(existing, default=str), run_id),
        )
        self._conn.commit()
        return {"run_id": run_id, "feedback_count": len(existing["items"])}

    # ─── lifecycle: promote / degrade / retire ───

    def promote(self, neuron_name: str, run_id: str, reason: str = "") -> dict:
        run = dict(self._conn.execute(
            "SELECT * FROM training_runs WHERE run_id=?", (run_id,)
        ).fetchone() or {})
        avg = run.get("avg_score", 0.0)
        total = run.get("episodes_total", 0)
        passed = run.get("episodes_passed", 0)
        pass_rate = passed / max(total, 1)

        gen_raw = run.get("generalization_json", "{}")
        gen = json.loads(gen_raw) if isinstance(gen_raw, str) else gen_raw
        gen_score = gen.get("generalization_score", 0.0)

        if avg < self.MIN_AVG_SCORE:
            raise ValueError(f"Avg score {avg} < min {self.MIN_AVG_SCORE}")
        if pass_rate < self.MIN_PASS_RATE:
            raise ValueError(f"Pass rate {pass_rate} < min {self.MIN_PASS_RATE}")

        return self._lifecycle_action(neuron_name, "promote", "training", "promoted",
                                       reason or f"avg={avg} pass_rate={pass_rate} gen={gen_score}")

    def degrade(self, neuron_name: str, reason: str) -> dict:
        return self._lifecycle_action(neuron_name, "degrade", "promoted", "degraded", reason)

    def retire(self, neuron_name: str, reason: str) -> dict:
        return self._lifecycle_action(neuron_name, "retire", None, "retired", reason)

    def lifecycle_history(self, neuron_name: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM neuron_lifecycle_actions WHERE neuron_name=? ORDER BY created_at DESC",
            (neuron_name,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── diagnostics ───

    def doctor(self) -> dict:
        ds = self._conn.execute("SELECT COUNT(*) as c FROM training_datasets").fetchone()["c"]
        eps = self._conn.execute("SELECT COUNT(*) as c FROM training_episodes").fetchone()["c"]
        runs = self._conn.execute("SELECT COUNT(*) as c FROM training_runs").fetchone()["c"]
        actions = self._conn.execute("SELECT COUNT(*) as c FROM neuron_lifecycle_actions").fetchone()["c"]
        return {
            "datasets": ds,
            "episodes": eps,
            "runs": runs,
            "lifecycle_actions": actions,
        }

    # ─── internal ───

    def _lifecycle_action(
        self, neuron_name: str, action: str,
        from_state: str | None, to_state: str, reason: str,
    ) -> dict:
        now = utc_now()
        action_id = _gen_id("lcact")
        self._conn.execute(
            """INSERT INTO neuron_lifecycle_actions
               (action_id, neuron_name, action, from_state, to_state,
                reason, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (action_id, neuron_name, action, from_state, to_state, reason, now),
        )
        self._conn.commit()
        return {
            "action_id": action_id,
            "neuron_name": neuron_name,
            "action": action,
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
        }


def _score_match(actual: dict, expected: dict) -> float:
    if not expected:
        return 1.0 if actual else 0.0
    if not actual:
        return 0.0
    matches = 0
    total = len(expected)
    for k, v in expected.items():
        if k in actual and actual[k] == v:
            matches += 1
    return round(matches / max(total, 1), 4)
