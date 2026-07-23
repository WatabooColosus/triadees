"""Benchmarks congelados y evidencia producida fuera del modelo evaluado."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FrozenBenchmarkRegistry:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS frozen_benchmarks (
                    benchmark_id TEXT NOT NULL, version TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL, manifest_json TEXT NOT NULL,
                    frozen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (benchmark_id, version)
                );
                CREATE TABLE IF NOT EXISTS external_benchmark_runs (
                    run_id TEXT PRIMARY KEY, benchmark_id TEXT NOT NULL, version TEXT NOT NULL,
                    subject_id TEXT NOT NULL, evaluator_id TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL, score REAL NOT NULL,
                    metrics_json TEXT NOT NULL, artifact_sha256 TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def freeze(self, manifest: dict[str, Any]) -> dict[str, Any]:
        benchmark_id = str(manifest.get("benchmark_id") or "").strip()
        version = str(manifest.get("version") or "").strip()
        cases = manifest.get("cases")
        if not benchmark_id or not version or not isinstance(cases, list) or not cases:
            raise ValueError("benchmark_id, version y cases no vacíos son obligatorios")
        digest = canonical_sha256(manifest)
        payload = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT manifest_sha256 FROM frozen_benchmarks WHERE benchmark_id=? AND version=?",
                (benchmark_id, version),
            ).fetchone()
            if row and row[0] != digest:
                raise ValueError("un benchmark congelado no puede modificarse en la misma versión")
            conn.execute(
                "INSERT OR IGNORE INTO frozen_benchmarks (benchmark_id,version,manifest_sha256,manifest_json) VALUES (?,?,?,?)",
                (benchmark_id, version, digest, payload),
            )
        return {"benchmark_id": benchmark_id, "version": version, "manifest_sha256": digest, "frozen": True}

    def record_external_run(
        self, *, run_id: str, benchmark_id: str, version: str, subject_id: str,
        evaluator_id: str, score: float, metrics: dict[str, Any], artifact: dict[str, Any],
    ) -> dict[str, Any]:
        if evaluator_id.strip().lower() in {"triade", "self", subject_id.strip().lower()}:
            raise ValueError("el evaluador debe ser independiente del sujeto")
        if not 0.0 <= float(score) <= 1.0:
            raise ValueError("score debe estar entre 0 y 1")
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT manifest_sha256 FROM frozen_benchmarks WHERE benchmark_id=? AND version=?",
                (benchmark_id, version),
            ).fetchone()
            if not row:
                raise KeyError("benchmark no congelado")
            artifact_sha = canonical_sha256(artifact)
            conn.execute(
                """INSERT INTO external_benchmark_runs
                (run_id,benchmark_id,version,subject_id,evaluator_id,manifest_sha256,score,metrics_json,artifact_sha256)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (run_id, benchmark_id, version, subject_id, evaluator_id, row[0], float(score),
                 json.dumps(metrics, sort_keys=True), artifact_sha),
            )
        return {"run_id": run_id, "score": float(score), "artifact_sha256": artifact_sha,
                "counts_as_external_evidence": True, "evaluator_id": evaluator_id}

    def cumulative_improvement(self, subject_id: str, benchmark_id: str, version: str) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT run_id,score,evaluator_id,artifact_sha256,created_at FROM external_benchmark_runs
                WHERE subject_id=? AND benchmark_id=? AND version=? ORDER BY created_at,rowid""",
                (subject_id, benchmark_id, version),
            ).fetchall()
        scores = [float(row[1]) for row in rows]
        delta = scores[-1] - scores[0] if len(scores) >= 2 else 0.0
        return {"subject_id": subject_id, "samples": len(scores), "baseline": scores[0] if scores else None,
                "latest": scores[-1] if scores else None, "delta": round(delta, 6),
                "improved": len(scores) >= 2 and delta > 0.0,
                "evidence": [{"run_id": r[0], "score": r[1], "evaluator_id": r[2], "artifact_sha256": r[3]} for r in rows]}
