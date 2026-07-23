"""A/B Model Evaluator · compara modelos Ollama para cada tipo de tarea.

Ejecuta la misma tarea con dos modelos, compara calidad, velocidad y
consumo de recursos. Almacena resultados y recomienda el mejor modelo
por tipo de tarea.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_EVAL_TABLE = """
CREATE TABLE IF NOT EXISTS ab_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    model_a TEXT NOT NULL,
    model_b TEXT NOT NULL,
    model_a_duration_ms REAL,
    model_b_duration_ms REAL,
    model_a_score REAL DEFAULT 0.5,
    model_b_score REAL DEFAULT 0.5,
    model_a_output TEXT,
    model_b_output TEXT,
    model_a_error TEXT,
    model_b_error TEXT,
    winner TEXT,
    evaluated_at REAL NOT NULL,
    prompt TEXT
);
"""

_RECOMMENDATION_TABLE = """
CREATE TABLE IF NOT EXISTS ab_recommendations (
    task_type TEXT PRIMARY KEY,
    recommended_model TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    total_evals INTEGER DEFAULT 0,
    model_a_wins INTEGER DEFAULT 0,
    model_b_wins INTEGER DEFAULT 0,
    ties INTEGER DEFAULT 0,
    updated_at REAL NOT NULL
);
"""

DEFAULT_PROMPTS: dict[str, str] = {
    "neuron_candidate_formation": "Genera un candidato de neurona para detectar y prevenir errores de validación en pipelines de aprendizaje.",
    "pending_learning_review": "Evalúa si este candidato de aprendizaje es válido: 'El sistema debería aprender a detectar anomalías en el tráfico de red.'",
    "semantic_memory_governance": "Revisa la coherencia de la memoria semántica: ¿hay contradicciones entre episodios recientes?",
    "pulse_check": "Diagnóstico rápido del estado del sistema: ¿hay recursos suficientes para continuar?",
    "system_debt_scan": "Identifica deuda técnica en el módulo de neuronas: ¿hay código duplicado o patrones antiguos?",
}


class ABModelEvaluator:
    """Evalúa y compara modelos Ollama para cada tipo de tarea."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(_EVAL_TABLE)
            conn.execute(_RECOMMENDATION_TABLE)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(ab_recommendations)")}
            if "evidence_method" not in columns:
                conn.execute("ALTER TABLE ab_recommendations ADD COLUMN evidence_method TEXT NOT NULL DEFAULT 'internal_heuristic'")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ab_external_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_type TEXT NOT NULL,
                model_a TEXT NOT NULL, model_b TEXT NOT NULL,
                benchmark_run_a TEXT NOT NULL, benchmark_run_b TEXT NOT NULL,
                score_a REAL NOT NULL, score_b REAL NOT NULL, winner TEXT NOT NULL,
                created_at REAL NOT NULL)"""
            )

    def record_external_pair(self, *, task_type: str, model_a: str, benchmark_run_a: str,
                             model_b: str, benchmark_run_b: str) -> dict[str, Any]:
        """Selecciona modelo únicamente desde dos resultados externos congelados."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT run_id,subject_id,score FROM external_benchmark_runs
                WHERE run_id IN (?,?)""", (benchmark_run_a, benchmark_run_b)
            ).fetchall()
            found = {row["run_id"]: row for row in rows}
            if benchmark_run_a not in found or benchmark_run_b not in found:
                raise KeyError("ambos benchmark runs externos son obligatorios")
            if found[benchmark_run_a]["subject_id"] != model_a or found[benchmark_run_b]["subject_id"] != model_b:
                raise ValueError("el subject del benchmark no coincide con el modelo")
            score_a, score_b = float(found[benchmark_run_a]["score"]), float(found[benchmark_run_b]["score"])
            winner_key = "tie" if score_a == score_b else "model_a" if score_a > score_b else "model_b"
            winner = "tie" if winner_key == "tie" else model_a if winner_key == "model_a" else model_b
            conn.execute(
                """INSERT INTO ab_external_evaluations
                (task_type,model_a,model_b,benchmark_run_a,benchmark_run_b,score_a,score_b,winner,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (task_type, model_a, model_b, benchmark_run_a, benchmark_run_b, score_a, score_b, winner, time.time()),
            )
        self._update_recommendation(task_type, model_a, model_b, winner_key, evidence_method="external_frozen_benchmark")
        return {"task_type": task_type, "winner": winner, "model_a_score": score_a, "model_b_score": score_b,
                "evaluation_method": "external_frozen_benchmark", "counts_as_external_evidence": True}

    def evaluate_pair(
        self,
        task_type: str,
        model_a: str,
        model_b: str,
        prompt: str | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Evalúa dos modelos con el mismo prompt y compara."""
        prompt = prompt or DEFAULT_PROMPTS.get(task_type, f"Ejecuta la tarea '{task_type}' de forma óptima.")

        result_a = self._run_model(model_a, prompt, timeout)
        result_b = self._run_model(model_b, prompt, timeout)

        score_a = self._score_output(result_a, prompt)
        score_b = self._score_output(result_b, prompt)

        winner_key = self._determine_winner(score_a, score_b, result_a, result_b)
        winner = model_a if winner_key == "model_a" else model_b if winner_key == "model_b" else "tie"

        evaluation = {
            "task_type": task_type,
            "model_a": model_a,
            "model_b": model_b,
            "model_a_result": result_a,
            "model_b_result": result_b,
            "model_a_score": score_a,
            "model_b_score": score_b,
            "winner": winner,
            "prompt": prompt,
            "evaluation_method": "internal_heuristic",
            "counts_as_external_evidence": False,
        }

        self._store_evaluation(evaluation)
        self._update_recommendation(task_type, model_a, model_b, winner_key)

        return evaluation

    def get_recommendation(self, task_type: str) -> dict[str, Any]:
        """Retorna el modelo recomendado para un tipo de tarea."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ab_recommendations WHERE task_type = ?",
                (task_type,),
            ).fetchone()
            if row:
                return dict(row)
        return {
            "task_type": task_type,
            "recommended_model": None,
            "confidence": 0.0,
            "total_evals": 0,
        }

    def get_all_recommendations(self) -> dict[str, dict[str, Any]]:
        """Retorna recomendaciones para todos los tipos de tarea."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM ab_recommendations ORDER BY task_type").fetchall()
            return {row["task_type"]: dict(row) for row in rows}

    def get_evaluation_history(self, task_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Retorna historial de evaluaciones."""
        with self._connect() as conn:
            if task_type:
                rows = conn.execute(
                    "SELECT * FROM ab_evaluations WHERE task_type = ? ORDER BY id DESC LIMIT ?",
                    (task_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM ab_evaluations ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def compare_models(
        self,
        model_a: str,
        model_b: str,
        task_types: list[str] | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Comparación amplia de dos modelos en múltiples tareas."""
        task_types = task_types or list(DEFAULT_PROMPTS.keys())
        results = []
        model_a_wins = 0
        model_b_wins = 0

        for task_type in task_types:
            eval_result = self.evaluate_pair(task_type, model_a, model_b, timeout=timeout)
            results.append(eval_result)
            if eval_result["winner"] == model_a:
                model_a_wins += 1
            elif eval_result["winner"] == model_b:
                model_b_wins += 1

        overall_winner = model_a if model_a_wins > model_b_wins else model_b if model_b_wins > model_a_wins else "tie"

        return {
            "model_a": model_a,
            "model_b": model_b,
            "overall_winner": overall_winner,
            "model_a_wins": model_a_wins,
            "model_b_wins": model_b_wins,
            "ties": len(task_types) - model_a_wins - model_b_wins,
            "evaluations": results,
        }

    def _run_model(self, model: str, prompt: str, timeout: int) -> dict[str, Any]:
        """Ejecuta un modelo Ollama y captura resultado."""
        try:
            from triade.models.ollama_client import OllamaClient
            client = OllamaClient(timeout=timeout)
            started = time.perf_counter()
            response = client.generate(model=model, prompt=prompt)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if not response.ok:
                return {
                    "status": "error",
                    "error": response.error or "Ollama no produjo una respuesta.",
                    "duration_ms": duration_ms,
                    "output": "",
                }
            return {
                "status": "ok",
                "output": response.text[:2000],
                "duration_ms": duration_ms,
                "tokens_eval": 0,
            }
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc)[:500],
                "duration_ms": 0,
                "output": "",
            }

    def _score_output(self, result: dict[str, Any], prompt: str) -> float:
        """Evalúa la calidad de la salida de un modelo (0.0-1.0)."""
        if result.get("status") != "ok":
            return 0.1

        output = result.get("output", "")
        score = 0.3

        if len(output) > 50:
            score += 0.15
        if len(output) > 200:
            score += 0.1

        output_lower = output.lower()
        prompt_words = set(prompt.lower().split())
        overlap = sum(1 for w in prompt_words if w in output_lower)
        if overlap > 3:
            score += 0.15

        coherence_signals = ["porque", "por qué", "sin embargo", "además", "por lo tanto", "en conclusión"]
        if any(s in output_lower for s in coherence_signals):
            score += 0.1

        if result.get("duration_ms", 0) < 5000:
            score += 0.1
        elif result.get("duration_ms", 0) > 30000:
            score -= 0.1

        return round(min(1.0, max(0.0, score)), 3)

    def _determine_winner(
        self,
        score_a: float,
        score_b: float,
        result_a: dict[str, Any],
        result_b: dict[str, Any],
    ) -> str:
        """Determina el ganador."""
        diff = abs(score_a - score_b)
        if diff < 0.05:
            if result_a.get("duration_ms", 99999) < result_b.get("duration_ms", 99999):
                return "model_a"
            elif result_b.get("duration_ms", 99999) < result_a.get("duration_ms", 99999):
                return "model_b"
            return "tie"

        return "model_a" if score_a > score_b else "model_b"

    def _store_evaluation(self, evaluation: dict[str, Any]) -> None:
        """Almacena una evaluación."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO ab_evaluations
                   (task_type, model_a, model_b, model_a_duration_ms, model_b_duration_ms,
                    model_a_score, model_b_score, model_a_output, model_b_output,
                    model_a_error, model_b_error, winner, evaluated_at, prompt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evaluation["task_type"],
                    evaluation["model_a"],
                    evaluation["model_b"],
                    evaluation["model_a_result"].get("duration_ms"),
                    evaluation["model_b_result"].get("duration_ms"),
                    evaluation["model_a_score"],
                    evaluation["model_b_score"],
                    evaluation["model_a_result"].get("output", "")[:1000],
                    evaluation["model_b_result"].get("output", "")[:1000],
                    evaluation["model_a_result"].get("error"),
                    evaluation["model_b_result"].get("error"),
                    evaluation["winner"],
                    time.time(),
                    evaluation.get("prompt", ""),
                ),
            )

    def _update_recommendation(
        self,
        task_type: str,
        model_a: str,
        model_b: str,
        winner: str,
        evidence_method: str = "internal_heuristic",
    ) -> None:
        """Actualiza la recomendación para un tipo de tarea."""
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ab_recommendations WHERE task_type = ?", (task_type,)
            ).fetchone()

            if row is None:
                recommended = model_a if winner in {"model_a", "tie"} else model_b
                conn.execute(
                    """INSERT INTO ab_recommendations
                       (task_type, recommended_model, confidence, total_evals,
                        model_a_wins, model_b_wins, ties, updated_at)
                       VALUES (?, ?, ?, 1, ?, ?, ?, ?)""",
                    (
                        task_type,
                        recommended,
                        0.5,
                        1 if winner == "model_a" else 0,
                        1 if winner == "model_b" else 0,
                        1 if winner == "tie" else 0,
                        now,
                    ),
                )
                conn.execute("UPDATE ab_recommendations SET evidence_method=? WHERE task_type=?", (evidence_method, task_type))
            else:
                total = row["total_evals"] + 1
                a_wins = row["model_a_wins"] + (1 if winner == "model_a" else 0)
                b_wins = row["model_b_wins"] + (1 if winner == "model_b" else 0)
                ties = row["ties"] + (1 if winner == "tie" else 0)
                confidence = min(1.0, total / 10)
                recommended = model_a if a_wins > b_wins else model_b if b_wins > a_wins else row["recommended_model"]

                conn.execute(
                    """UPDATE ab_recommendations SET
                       recommended_model = ?, confidence = ?, total_evals = ?,
                       model_a_wins = ?, model_b_wins = ?, ties = ?, updated_at = ?
                       WHERE task_type = ?""",
                    (recommended, confidence, total, a_wins, b_wins, ties, now, task_type),
                )
                if evidence_method == "external_frozen_benchmark":
                    conn.execute("UPDATE ab_recommendations SET evidence_method=? WHERE task_type=?", (evidence_method, task_type))
