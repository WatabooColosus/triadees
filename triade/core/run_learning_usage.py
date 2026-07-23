"""Conexión entre aprendizaje y uso real en runs — Tríade Ω.

Registra cuando una respuesta de run usa memoria o candidatos de aprendizaje
verificados, habilitando el ciclo: fuente → candidato → verificación →
uso en runs → validación → consolidación.

Soporta:
- output.memory_diff.used_learning_candidate_ids (explícito)
- memory.semantic_matches.document_id (explícito)
- evidence_refs (explícito)
- Overlap heurístico como fallback (marcado heuristic_match=True)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.core.error_bus import record_internal_error
from triade.learning.pipeline import LearningPipeline


def record_learning_usage_from_output(
    run_id: str,
    output_packet: Any,
    memory_packet: Any,
    db_path: str | Path = "triade/memory/triade.db",
) -> dict[str, Any]:
    """Registra uso de aprendizaje verificado en un run completado.

    Estrategia de matching:
    1. output.memory_diff.used_learning_candidate_ids → match explícito
    2. memory.semantic_matches.document_id → match de documento semántico
    3. output.memory_diff.evidence_refs → referencia a evidencia
    4. Overlap heurístico de palabras → fallback (heuristic_match=True)

    Cada candidato marcado incluye reason para trazabilidad.
    """
    db_path = Path(db_path)
    pipeline = LearningPipeline(db_path=db_path)
    result: dict[str, Any] = {
        "candidates_marked": 0,
        "run_id": run_id,
        "outcome_score": 0.0,
        "matched_by_source": {},
        "trace": [],
    }

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
                """SELECT id, candidate_id, title, content, domain, source_ref, status
                FROM learning_queue
                WHERE status IN ('verified', 'validated_in_runs')
                ORDER BY confidence DESC
                LIMIT 30"""
            ).fetchall()

        matched: list[dict[str, Any]] = []

        # ── 1. Match explícito: output.memory_diff.used_learning_candidate_ids ──
        explicit_ids = _extract_explicit_candidate_ids(output_packet)
        if explicit_ids:
            for cand in rows:
                cid = str(cand["candidate_id"] or "")
                if cid in explicit_ids or int(cand["id"]) in explicit_ids:
                    matched.append({
                        **dict(cand),
                        "match_source": "explicit_candidate_id",
                        "reason": f"Candidato {cid} listado en output.memory_diff.used_learning_candidate_ids",
                    })

        # ── 2. Match por documentos semánticos ──
        semantic_doc_ids = _extract_semantic_document_ids(memory_packet)
        if semantic_doc_ids:
            for cand in rows:
                sr = str(cand["source_ref"] or "")
                if sr and sr in semantic_doc_ids:
                    matched.append({
                        **dict(cand),
                        "match_source": "semantic_document",
                        "reason": f"Documento semántico {sr} referenciado en memory.semantic_matches",
                    })

        # ── 3. Match por evidence_refs ──
        evidence_refs = _extract_evidence_refs(output_packet)
        if evidence_refs:
            for cand in rows:
                sr = str(cand["source_ref"] or "")
                title = str(cand["title"] or "")
                if sr and any(sr in ref for ref in evidence_refs):
                    matched.append({
                        **dict(cand),
                        "match_source": "evidence_ref",
                        "reason": f"source_ref {sr} encontrado en evidence_refs del output",
                    })
                elif title and any(title.lower() in ref.lower() for ref in evidence_refs):
                    matched.append({
                        **dict(cand),
                        "match_source": "evidence_ref_title",
                        "reason": f"Title '{title[:40]}' matcheado por evidence_ref",
                    })

        # ── 4. Fallback: overlap heurístico ──
        response_lower = response_text.lower()
        for cand in rows:
            if any(m["id"] == cand["id"] for m in matched):
                continue
            title = str(cand["title"] or "").lower()
            content = str(cand["content"] or "").lower()
            domain = str(cand["domain"] or "").lower()

            heuristic_reason = None
            if title and title[:10] in response_lower:
                heuristic_reason = f"Title prefix '{title[:10]}' encontrado en respuesta"
            elif domain and domain in response_lower:
                heuristic_reason = f"Domain '{domain}' encontrado en respuesta"
            elif content:
                content_words = set(content.split())
                response_words = set(response_lower.split())
                overlap = len(content_words & response_words)
                if overlap >= 3:
                    heuristic_reason = f"Overlap de {overlap} palabras entre contenido y respuesta"

            if heuristic_reason:
                matched.append({
                    **dict(cand),
                    "match_source": "heuristic",
                    "heuristic_match": True,
                    "reason": heuristic_reason,
                })

        # ── Deduplicate by candidate id ──
        seen_ids: set[int] = set()
        unique_matched: list[dict[str, Any]] = []
        for m in matched:
            mid = int(m["id"])
            if mid not in seen_ids:
                seen_ids.add(mid)
                unique_matched.append(m)

        outcome_score = _compute_outcome_score(output_packet, memory_packet)

        # ── Mark each matched candidate ──
        for cand in unique_matched[:8]:
            candidate_id_str = str(cand["candidate_id"])
            match_source = cand.get("match_source", "unknown")
            reason = cand.get("reason", "Sin razón especificada")
            is_heuristic = cand.get("heuristic_match", False)

            try:
                pipeline.mark_used_in_run(
                    candidate_id=candidate_id_str,
                    run_id=run_id,
                    outcome_score=outcome_score,
                )
                result["candidates_marked"] += 1
                source_counter = result["matched_by_source"]
                source_counter[match_source] = source_counter.get(match_source, 0) + 1
                result["trace"].append({
                    "candidate_id": candidate_id_str,
                    "title": str(cand.get("title", ""))[:60],
                    "match_source": match_source,
                    "heuristic_match": is_heuristic,
                    "reason": reason,
                    "outcome_score": outcome_score,
                })
            except ValueError as exc:
                # A verified candidate may accumulate real-use observations before
                # Measurement Core has produced promotable evidence.  That is an
                # expected governance block, not an internal runtime failure.
                message = str(exc)
                if "evidencia Measurement Core" in message or "evidencia no demuestra mejora" in message:
                    result["trace"].append({
                        "candidate_id": candidate_id_str,
                        "match_source": match_source,
                        "status": "blocked_by_measurement_gate",
                        "reason": message,
                    })
                    continue
                result["trace"].append({
                    "candidate_id": candidate_id_str,
                    "match_source": match_source,
                    "error": message,
                })
                record_internal_error(
                    "learning_usage.mark_used",
                    exc,
                    run_id=run_id,
                    payload={"candidate_id": candidate_id_str, "match_source": match_source},
                    db_path=db_path,
                )
            except Exception as exc:
                result["trace"].append({
                    "candidate_id": candidate_id_str,
                    "match_source": match_source,
                    "error": str(exc),
                })
                record_internal_error(
                    "learning_usage.mark_used",
                    exc,
                    run_id=run_id,
                    payload={"candidate_id": candidate_id_str, "match_source": match_source},
                    db_path=db_path,
                )

        result["outcome_score"] = outcome_score
        result["matched_domains"] = list({str(c["domain"]) for c in unique_matched})
        result["total_candidates_checked"] = len(rows)
        result["total_unique_matches"] = len(unique_matched)

    except Exception as exc:
        result["error"] = str(exc)
        record_internal_error("learning_usage.main", exc, run_id=run_id, db_path=db_path)

    return result


def _extract_explicit_candidate_ids(output_packet: Any) -> set[str | int]:
    """Extrae candidate_ids explícitos de output.memory_diff.used_learning_candidate_ids."""
    ids: set[str | int] = set()
    try:
        mem_diff = {}
        if hasattr(output_packet, "memory_diff") and isinstance(output_packet.memory_diff, dict):
            mem_diff = output_packet.memory_diff
        elif isinstance(output_packet, dict):
            mem_diff = output_packet.get("memory_diff", {})

        used_ids = mem_diff.get("used_learning_candidate_ids") or []
        for item in used_ids:
            if isinstance(item, (str, int)):
                ids.add(item)
            elif isinstance(item, dict) and "candidate_id" in item:
                ids.add(item["candidate_id"])
    except Exception as exc:
        record_internal_error(
            "learning_usage.extract_explicit_candidate_ids",
            exc,
            payload={"module": __name__, "function": "_extract_explicit_candidate_ids", "operation": "parse_output_memory_diff"},
        )
    return ids


def _extract_semantic_document_ids(memory_packet: Any) -> set[str]:
    """Extrae document_ids de memory.semantic_matches."""
    ids: set[str] = set()
    try:
        if memory_packet is None:
            return ids
        semantic_recall = {}
        if hasattr(memory_packet, "semantic_recall") and isinstance(memory_packet.semantic_recall, dict):
            semantic_recall = memory_packet.semantic_recall
        elif hasattr(memory_packet, "semantic_matches"):
            matches = memory_packet.semantic_matches
            if isinstance(matches, list):
                for m in matches:
                    if isinstance(m, dict) and "document_id" in m:
                        ids.add(str(m["document_id"]))
                return ids

        matches = semantic_recall.get("authorized_matches") or semantic_recall.get("semantic_matches") or []
        if isinstance(matches, list):
            for m in matches:
                if isinstance(m, dict) and "document_id" in m:
                    ids.add(str(m["document_id"]))
    except Exception as exc:
        record_internal_error(
            "learning_usage.extract_semantic_document_ids",
            exc,
            payload={"module": __name__, "function": "_extract_semantic_document_ids", "operation": "parse_memory_semantic_matches"},
        )
    return ids


def _extract_evidence_refs(output_packet: Any) -> list[str]:
    """Extrae evidence_refs de output.memory_diff."""
    refs: list[str] = []
    try:
        mem_diff = {}
        if hasattr(output_packet, "memory_diff") and isinstance(output_packet.memory_diff, dict):
            mem_diff = output_packet.memory_diff
        elif isinstance(output_packet, dict):
            mem_diff = output_packet.get("memory_diff", {})

        raw_refs = mem_diff.get("evidence_refs") or []
        if isinstance(raw_refs, list):
            refs = [str(r) for r in raw_refs if r]
    except Exception as exc:
        record_internal_error(
            "learning_usage.extract_evidence_refs",
            exc,
            payload={"module": __name__, "function": "_extract_evidence_refs", "operation": "parse_output_evidence_refs"},
        )
    return refs


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

    except Exception as exc:
        record_internal_error("learning_usage.outcome_score", exc)

    return max(0.0, min(1.0, score))


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
