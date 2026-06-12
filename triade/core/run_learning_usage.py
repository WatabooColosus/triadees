"""Conexión entre aprendizaje y uso real en runs — Tríade Ω.

Registra cuando una respuesta de run usa memoria o candidatos de aprendizaje
verificados, habilitando el ciclo: fuente → candidato → verificación →
uso en runs → validación → consolidación.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.learning.pipeline import LearningPipeline


def record_learning_usage_from_output(
    run_id: str,
    output_packet: Any,
    memory_packet: Any,
    db_path: str | Path = "triade/memory/triade.db",
) -> dict[str, Any]:
    """Registra uso de aprendizaje verificado en un run completado.

    Busca candidatos verified que pudieron ser usados en la respuesta
    y los marca con `mark_used_in_run()` para habilitar consolidación.

    No consolida automáticamente — respeta gates del LearningPipeline.
    """
    db_path = Path(db_path)
    pipeline = LearningPipeline(db_path=db_path)
    result = {"candidates_marked": 0, "run_id": run_id, "outcome_score": 0.0}

    try:
        response_text = ""
        if hasattr(output_packet, "response"):
            response_text = str(output_packet.response or "")
        elif isinstance(output_packet, dict):
            response_text = str(output_packet.get("response", ""))

        if not response_text:
            return result

        with _connect(db_path) as conn:
            rows = conn.execute(
                """SELECT id, candidate_id, title, content, domain, source_ref
                FROM learning_queue
                WHERE status IN ('verified', 'validated_in_runs')
                ORDER BY confidence DESC
                LIMIT 20"""
            ).fetchall()

        matched = []
        response_lower = response_text.lower()
        for cand in rows:
            title = str(cand["title"] or "").lower()
            content = str(cand["content"] or "").lower()
            domain = str(cand["domain"] or "").lower()

            if (title and title[:10] in response_lower) or (domain and domain in response_lower):
                matched.append(cand)
            elif content:
                content_words = set(content.split())
                response_words = set(response_lower.split())
                overlap = len(content_words & response_words)
                if overlap >= 3:
                    matched.append(cand)

        outcome_score = _compute_outcome_score(output_packet, memory_packet)

        for cand in matched[:5]:
            candidate_id_str = str(cand["candidate_id"])
            try:
                pipeline.mark_used_in_run(
                    candidate_id=candidate_id_str,
                    run_id=run_id,
                    outcome_score=outcome_score,
                )
                result["candidates_marked"] += 1
            except Exception:
                pass

        result["outcome_score"] = outcome_score
        result["matched_domains"] = list({str(c["domain"]) for c in matched})

    except Exception as exc:
        result["error"] = str(exc)

    return result


def _compute_outcome_score(output_packet: Any, memory_packet: Any) -> float:
    """Calcula un outcome_score prudente basado en calidad del output."""
    score = 0.5

    try:
        if hasattr(output_packet, "status"):
            if output_packet.status == "ok":
                score += 0.2
            elif output_packet.status == "blocked":
                score -= 0.3

        if hasattr(output_packet, "model_ok") and output_packet.model_ok:
            score += 0.1

        if hasattr(output_packet, "response"):
            response = str(output_packet.response or "")
            if len(response) > 50:
                score += 0.1
            if len(response) > 200:
                score += 0.05

        if memory_packet is not None:
            if hasattr(memory_packet, "verification_status"):
                if memory_packet.verification_status == "ok":
                    score += 0.1

    except Exception:
        pass

    return max(0.0, min(1.0, score))


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
