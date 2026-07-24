"""T-020 — Model Router avanzado: selección automática basada en recursos,
dificultad de tarea, costo, latencia, e historial de rendimiento."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass(frozen=True, slots=True)
class ModelRouteDecision:
    model: str
    role: str
    reason: str
    score: float
    candidates: tuple = ()
    fallback_used: bool = False
    hardware_ok: bool = True
    difficulty: str = "medium"
    estimated_tokens: int = 0
    estimated_latency_ms: float = 0.0


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS model_performance (
    model_name     TEXT NOT NULL,
    role           TEXT NOT NULL,
    avg_latency_ms REAL DEFAULT 0.0,
    avg_tokens     REAL DEFAULT 0.0,
    success_rate   REAL DEFAULT 1.0,
    total_calls    INTEGER DEFAULT 0,
    failed_calls   INTEGER DEFAULT 0,
    last_used      TEXT,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (model_name, role)
);
CREATE TABLE IF NOT EXISTS model_route_log (
    log_id         TEXT PRIMARY KEY,
    role           TEXT NOT NULL,
    selected_model TEXT NOT NULL,
    reason         TEXT DEFAULT '',
    score          REAL DEFAULT 0.0,
    difficulty     TEXT DEFAULT 'medium',
    latency_ms     REAL DEFAULT 0.0,
    tokens_used    INTEGER DEFAULT 0,
    success        INTEGER DEFAULT 1,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mrl_role ON model_route_log(role);
"""


class SmartModelRouter:
    """Router inteligente con historial de rendimiento, dificultad de tarea,
    costo y selección basada en scoring compuesto."""

    MODEL_RAM_GB = {
        "qwen3:1.7b": 2.5, "qwen2.5-coder:1.5b-base": 2.5,
        "qwen2.5:3b-instruct": 4.0, "qwen2.5-coder:3b": 4.0,
        "qwen3:4b": 5.5, "deepseek-coder-v2:16b": 12.0,
        "llama3:latest": 7.0, "llama3.1:8b": 8.5,
        "llama3.2:3b": 4.0, "llama3.2:1b": 2.0,
        "nomic-embed-text:latest": 1.0, "qwen3-embedding:0.6b": 1.0,
    }

    ROLE_MODELS = {
        "hypothalamus": ["qwen2.5:3b-instruct", "qwen3:1.7b", "qwen3:4b"],
        "central": ["qwen2.5:3b-instruct", "llama3:latest", "qwen3:4b"],
        "creator": ["qwen2.5:3b-instruct", "qwen3:4b", "llama3:latest"],
        "trainer": ["qwen2.5:3b-instruct", "qwen3:4b"],
        "coder": ["qwen2.5-coder:3b", "qwen2.5-coder:1.5b-base"],
        "embedding": ["nomic-embed-text:latest", "qwen3-embedding:0.6b"],
        "fast": ["qwen3:1.7b", "qwen2.5:3b-instruct"],
        "deep": ["llama3.1:8b", "llama3:latest", "qwen3:4b"],
    }

    DIFFICULTY_MAP = {
        "trivial": "fast", "simple": "fast",
        "medium": "medium", "moderate": "medium",
        "complex": "deep", "hard": "deep",
    }

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def select(
        self,
        role: str,
        difficulty: str = "medium",
        available_ram_gb: float = 31.0,
        cost_weight: float = 0.3,
        latency_weight: float = 0.3,
        performance_weight: float = 0.4,
    ) -> dict:
        candidates = self.ROLE_MODELS.get(role, self.ROLE_MODELS["central"])
        difficulty_role = self.DIFFICULTY_MAP.get(difficulty, "medium")
        if difficulty_role == "deep" and role in ("central", "creator", "trainer"):
            candidates = self.ROLE_MODELS.get("deep", candidates)
        elif difficulty_role == "fast":
            candidates = self.ROLE_MODELS.get("fast", candidates)

        scored = []
        for model in candidates:
            ram_needed = self.MODEL_RAM_GB.get(model, 4.0)
            hw_ok = ram_needed <= available_ram_gb
            if not hw_ok:
                continue

            perf = self._get_performance(model, role)
            cost_score = 1.0 - min(ram_needed / 16.0, 1.0)
            latency_score = 1.0 - min(perf["avg_latency_ms"] / 5000.0, 1.0)
            perf_score = perf["success_rate"]

            total = (cost_weight * cost_score +
                     latency_weight * latency_score +
                     performance_weight * perf_score)

            scored.append({
                "model": model, "score": round(total, 4),
                "ram_gb": ram_needed, "hw_ok": hw_ok,
                "perf": perf,
            })

        if not scored:
            fallback = candidates[0] if candidates else "qwen2.5:3b-instruct"
            return {
                "model": fallback, "role": role, "reason": "fallback_no_hardware_match",
                "score": 0.0, "candidates": tuple(candidates),
                "fallback_used": True, "hardware_ok": False,
                "difficulty": difficulty,
            }

        scored.sort(key=lambda x: x["score"], reverse=True)
        best = scored[0]

        return {
            "model": best["model"], "role": role,
            "reason": f"highest_score_{best['score']}_for_{difficulty}",
            "score": best["score"],
            "candidates": tuple(s["model"] for s in scored),
            "fallback_used": False, "hardware_ok": True,
            "difficulty": difficulty,
        }

    def record_result(
        self, model: str, role: str, success: bool,
        latency_ms: float = 0.0, tokens_used: int = 0,
        difficulty: str = "medium",
    ) -> dict:
        now = utc_now()
        log_id = _gen_id("mroute")

        row = self._conn.execute(
            "SELECT * FROM model_performance WHERE model_name=? AND role=?",
            (model, role),
        ).fetchone()

        if row:
            total = row["total_calls"] + 1
            failed = row["failed_calls"] + (0 if success else 1)
            sr = 1.0 - failed / max(total, 1)
            avg_lat = (row["avg_latency_ms"] * row["total_calls"] + latency_ms) / max(total, 1)
            avg_tok = (row["avg_tokens"] * row["total_calls"] + tokens_used) / max(total, 1)
            self._conn.execute(
                """UPDATE model_performance
                   SET avg_latency_ms=?, avg_tokens=?, success_rate=?,
                       total_calls=?, failed_calls=?, last_used=?, updated_at=?
                   WHERE model_name=? AND role=?""",
                (round(avg_lat, 2), round(avg_tok, 1), round(sr, 4),
                 total, failed, now, now, model, role),
            )
        else:
            self._conn.execute(
                """INSERT INTO model_performance
                   (model_name, role, avg_latency_ms, avg_tokens,
                    success_rate, total_calls, failed_calls,
                    last_used, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (model, role, latency_ms, tokens_used,
                 1.0 if success else 0.0, 1, 0 if success else 1,
                 now, now),
            )

        self._conn.execute(
            """INSERT INTO model_route_log
               (log_id, role, selected_model, reason, score,
                difficulty, latency_ms, tokens_used, success, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (log_id, role, model, "", 0.0, difficulty,
             latency_ms, tokens_used, 1 if success else 0, now),
        )
        self._conn.commit()
        return {"model": model, "role": role, "success": success}

    def _get_performance(self, model: str, role: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM model_performance WHERE model_name=? AND role=?",
            (model, role),
        ).fetchone()
        if row:
            return {
                "avg_latency_ms": row["avg_latency_ms"],
                "avg_tokens": row["avg_tokens"],
                "success_rate": row["success_rate"],
                "total_calls": row["total_calls"],
            }
        return {"avg_latency_ms": 0.0, "avg_tokens": 0.0,
                "success_rate": 0.8, "total_calls": 0}

    def model_stats(self, model: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM model_performance WHERE model_name=?", (model,)
        ).fetchall()
        return [dict(r) for r in rows]

    def role_stats(self, role: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM model_performance WHERE role=? ORDER BY success_rate DESC",
            (role,),
        ).fetchall()
        return [dict(r) for r in rows]

    def doctor(self) -> dict:
        models = self._conn.execute("SELECT COUNT(DISTINCT model_name) as c FROM model_performance").fetchone()["c"]
        logs = self._conn.execute("SELECT COUNT(*) as c FROM model_route_log").fetchone()["c"]
        return {"unique_models": models, "route_logs": logs}
