"""T-009 — Canary deployment para cambios de aprendizaje: despliega cambios
de forma gradual con monitoreo, rollback automático y métricas comparativas."""

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
CREATE TABLE IF NOT EXISTS canary_deployments (
    canary_id      TEXT PRIMARY KEY,
    candidate_id   TEXT NOT NULL,
    ci_run_id      TEXT,
    traffic_pct    REAL DEFAULT 0.0,
    baseline_metrics_json TEXT DEFAULT '{}',
    canary_metrics_json   TEXT DEFAULT '{}',
    delta_json     TEXT DEFAULT '{}',
    verdict        TEXT DEFAULT 'pending',
    status         TEXT DEFAULT 'active',
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS canary_observations (
    observation_id TEXT PRIMARY KEY,
    canary_id      TEXT NOT NULL,
    metric_name    TEXT NOT NULL,
    baseline_value REAL DEFAULT 0.0,
    canary_value   REAL DEFAULT 0.0,
    delta          REAL DEFAULT 0.0,
    tolerance      REAL DEFAULT 0.1,
    passed         INTEGER DEFAULT 0,
    observed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_canary_obs ON canary_observations(canary_id);
CREATE TABLE IF NOT EXISTS canary_rollbacks (
    rollback_id    TEXT PRIMARY KEY,
    canary_id      TEXT NOT NULL,
    reason         TEXT NOT NULL,
    metrics_at_rollback TEXT DEFAULT '{}',
    rolled_back_at TEXT NOT NULL
);
"""


class CanaryDeployment:
    """Canary deployment con monitoreo comparativo, tolerancia configurable
    y rollback automático."""

    DEFAULT_TOLERANCE = 0.10

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def create(
        self,
        candidate_id: str,
        traffic_pct: float = 0.05,
        baseline_metrics: dict[str, float] | None = None,
        ci_run_id: str | None = None,
    ) -> dict:
        now = utc_now()
        canary_id = _gen_id("canary")
        self._conn.execute(
            """INSERT INTO canary_deployments
               (canary_id, candidate_id, ci_run_id, traffic_pct,
                baseline_metrics_json, status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (canary_id, candidate_id, ci_run_id,
             _clamp(traffic_pct, 0.0, 1.0),
             json.dumps(baseline_metrics or {}, default=str),
             "active", now),
        )
        self._conn.commit()
        return {"canary_id": canary_id, "candidate_id": candidate_id, "status": "active"}

    def record_observation(
        self,
        canary_id: str,
        metric_name: str,
        baseline_value: float,
        canary_value: float,
        tolerance: float | None = None,
    ) -> dict:
        tol = tolerance if tolerance is not None else self.DEFAULT_TOLERANCE
        delta = canary_value - baseline_value
        passed = abs(delta) <= abs(baseline_value * tol) + tol

        obs_id = _gen_id("cob")
        self._conn.execute(
            """INSERT INTO canary_observations
               (observation_id, canary_id, metric_name,
                baseline_value, canary_value, delta,
                tolerance, passed, observed_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (obs_id, canary_id, metric_name, baseline_value, canary_value,
             round(delta, 6), tol, 1 if passed else 0, utc_now()),
        )
        self._conn.commit()
        return {
            "observation_id": obs_id,
            "metric": metric_name,
            "baseline": baseline_value,
            "canary": canary_value,
            "delta": round(delta, 6),
            "passed": passed,
        }

    def verdict(self, canary_id: str) -> dict:
        rows = self._conn.execute(
            "SELECT * FROM canary_observations WHERE canary_id=?",
            (canary_id,),
        ).fetchall()
        obs = [dict(r) for r in rows]
        total = len(obs)
        passed = sum(1 for o in obs if o["passed"])
        all_pass = total > 0 and passed == total

        canary_status = dict(self._conn.execute(
            "SELECT * FROM canary_deployments WHERE canary_id=?", (canary_id,)
        ).fetchone() or {})

        verdict = "pass" if all_pass else "fail"
        new_traffic = canary_status.get("traffic_pct", 0.05)
        if all_pass:
            new_traffic = _clamp(new_traffic * 2, 0.0, 1.0)

        self._conn.execute(
            "UPDATE canary_deployments SET verdict=?, traffic_pct=? WHERE canary_id=?",
            (verdict, new_traffic, canary_id),
        )
        self._conn.commit()

        return {
            "canary_id": canary_id,
            "verdict": verdict,
            "observations": total,
            "passed": passed,
            "failed": total - passed,
            "traffic_pct": new_traffic,
        }

    def rollback(self, canary_id: str, reason: str) -> dict:
        now = utc_now()
        rollback_id = _gen_id("crb")
        canary = dict(self._conn.execute(
            "SELECT * FROM canary_deployments WHERE canary_id=?", (canary_id,)
        ).fetchone() or {})

        self._conn.execute(
            """INSERT INTO canary_rollbacks
               (rollback_id, canary_id, reason,
                metrics_at_rollback, rolled_back_at)
               VALUES (?,?,?,?,?)""",
            (rollback_id, canary_id, reason,
             canary.get("canary_metrics_json", "{}"), now),
        )
        self._conn.execute(
            "UPDATE canary_deployments SET status='rolled_back' WHERE canary_id=?",
            (canary_id,),
        )
        self._conn.commit()
        return {"rollback_id": rollback_id, "canary_id": canary_id, "reason": reason}

    def get(self, canary_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM canary_deployments WHERE canary_id=?", (canary_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_active(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM canary_deployments WHERE status='active' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def doctor(self) -> dict:
        active = self._conn.execute(
            "SELECT COUNT(*) as c FROM canary_deployments WHERE status='active'"
        ).fetchone()["c"]
        rolled_back = self._conn.execute(
            "SELECT COUNT(*) as c FROM canary_deployments WHERE status='rolled_back'"
        ).fetchone()["c"]
        total_obs = self._conn.execute(
            "SELECT COUNT(*) as c FROM canary_observations"
        ).fetchone()["c"]
        return {"active_canaries": active, "rolled_back": rolled_back, "total_observations": total_obs}
