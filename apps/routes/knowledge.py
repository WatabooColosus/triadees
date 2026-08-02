"""Endpoints para ver qué sabe Tríade Ω, de dónde y cuándo lo usó.

Antes de esto `/api/knowledge/*` devolvía 404: el usuario no tenía forma de
mirar. Todo lo que se sirve aquí sale de `KnowledgeVisibilityService`, que
distingue candidato de saber; ningún endpoint inventa un número para que la
pantalla no se vea vacía.
"""

from __future__ import annotations

import os
import platform
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from triade.knowledge.visibility import (
    VISIBILITY_VERSION,
    KnowledgeVisibilityService,
)

router = APIRouter(tags=["knowledge"])

DB_PATH = os.getenv("TRIADE_DB_PATH", "triade/memory/triade.db")

_STARTED_AT = datetime.now(UTC).isoformat()


def _service() -> KnowledgeVisibilityService:
    return KnowledgeVisibilityService(DB_PATH)


def _git(*args: str) -> str:
    """SHA y rama del código en ejecución. Si no hay git, se dice."""
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            cwd=Path(__file__).resolve().parent.parent.parent,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


@router.get("/api/runtime/build")
def runtime_build() -> dict[str, Any]:
    """Permite comprobar que lo que se ve corresponde al código y a la DB reales.

    Sin esto es imposible distinguir «la función no existe» de «el proceso
    está corriendo una versión anterior».
    """
    db = Path(DB_PATH)
    return {
        "git_sha": _git("rev-parse", "HEAD"),
        "git_sha_short": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "started_at": _STARTED_AT,
        "db_path": str(db.resolve()) if db.exists() else f"{db} (no existe)",
        "db_exists": db.exists(),
        "db_size_bytes": db.stat().st_size if db.exists() else 0,
        "python_version": platform.python_version(),
        "working_directory": os.getcwd(),
        "worker_concurrency": os.getenv("TRIADE_WORKER_CONCURRENCY", "1"),
        "learning_enabled": os.getenv("TRIADE_POST_RUN_LEARNING", "0"),
        "knowledge_visibility_version": VISIBILITY_VERSION,
    }


@router.get("/api/knowledge/summary")
def knowledge_summary() -> dict[str, Any]:
    return _service().summary().to_dict()


@router.get("/api/knowledge")
def knowledge_list(
    limit: int = Query(50, ge=1, le=500),
    state: str | None = Query(None, description="stable, evidence_verified, …"),
) -> dict[str, Any]:
    estados = {s.strip() for s in state.split(",")} if state else None
    items = _service().list_knowledge(limit=limit, states=estados)
    return {
        "count": len(items),
        "items": [i.to_dict() for i in items],
        "visibility_version": VISIBILITY_VERSION,
    }


@router.get("/api/knowledge/{knowledge_id}")
def knowledge_detail(knowledge_id: str) -> dict[str, Any]:
    item = _service().get_knowledge(knowledge_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No existe saber: {knowledge_id}")
    return item.to_dict()


def _desde_hace_24h() -> str:
    """Corte de la ventana, en el mismo formato ISO que escriben las tablas."""
    return (datetime.now(UTC) - timedelta(hours=24)).isoformat()


def _rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


@router.get("/api/learning/activity")
def learning_activity(limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    """Eventos reales del ciclo de aprendizaje, del más reciente al más antiguo."""
    eventos: list[dict[str, Any]] = []

    for fila in _rows(
        "SELECT candidate_id, title, status, source_ref, created_at"
        " FROM learning_queue ORDER BY id DESC LIMIT ?",
        (limit,),
    ):
        eventos.append(
            {
                "event_id": f"cand-{fila['candidate_id']}",
                "timestamp": fila.get("created_at"),
                "type": "candidate_created",
                "candidate_id": fila.get("candidate_id"),
                "knowledge_id": fila.get("candidate_id"),
                "run_id": fila.get("source_ref"),
                "task_id": None,
                "status": fila.get("status"),
                "reason": "Candidato generado tras un run.",
                "evidence_ref": None,
            }
        )

    for fila in _rows(
        "SELECT memory_id, decision, reason_codes, run_id, created_at"
        " FROM retrieval_safety_decisions WHERE decision != 'allowed'"
        " ORDER BY id DESC LIMIT ?",
        (limit,),
    ):
        eventos.append(
            {
                "event_id": f"safety-{fila['memory_id']}-{fila['created_at']}",
                "timestamp": fila.get("created_at"),
                "type": "candidate_blocked",
                "candidate_id": fila.get("memory_id"),
                "knowledge_id": fila.get("memory_id"),
                "run_id": fila.get("run_id"),
                "task_id": None,
                "status": fila.get("decision"),
                "reason": str(fila.get("reason_codes") or ""),
                "evidence_ref": None,
            }
        )

    for fila in _rows(
        "SELECT run_id, injected_ids, created_at FROM learning_retrieval_decisions"
        " ORDER BY id DESC LIMIT ?",
        (limit,),
    ):
        eventos.append(
            {
                "event_id": f"inject-{fila['run_id']}",
                "timestamp": fila.get("created_at"),
                "type": "candidate_injected",
                "candidate_id": None,
                "knowledge_id": fila.get("injected_ids"),
                "run_id": fila.get("run_id"),
                "task_id": None,
                "status": "injected",
                "reason": "Inyectado en el contexto antes de generar la respuesta.",
                "evidence_ref": None,
            }
        )

    for fila in _rows(
        "SELECT candidate_id, decision, regression_report_id, updated_at"
        " FROM learning_evidence ORDER BY id DESC LIMIT ?",
        (limit,),
    ):
        eventos.append(
            {
                "event_id": f"ev-{fila['candidate_id']}",
                "timestamp": fila.get("updated_at"),
                "type": "evidence_started"
                if fila.get("decision") == "pending"
                else "evidence_passed",
                "candidate_id": fila.get("candidate_id"),
                "knowledge_id": fila.get("candidate_id"),
                "run_id": None,
                "task_id": None,
                "status": fila.get("decision"),
                "reason": "Evidencia de mejora.",
                "evidence_ref": fila.get("regression_report_id"),
            }
        )

    eventos.sort(key=lambda e: str(e.get("timestamp") or ""), reverse=True)
    return {"count": len(eventos[:limit]), "events": eventos[:limit]}


@router.get("/api/learning/rejections")
def learning_rejections(limit: int = Query(30, ge=1, le=200)) -> dict[str, Any]:
    items = _service().list_knowledge(limit=500, states={"rejected", "quarantined"})
    return {"count": len(items[:limit]), "items": [i.to_dict() for i in items[:limit]]}


@router.get("/api/learning/last-used")
def learning_last_used(limit: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
    usados = [i for i in _service().list_knowledge(limit=500) if i.last_used_at]
    usados.sort(key=lambda i: str(i.last_used_at), reverse=True)
    return {
        "count": len(usados[:limit]),
        "items": [i.to_dict() for i in usados[:limit]],
    }


@router.get("/api/learning/tasks")
def learning_tasks() -> dict[str, Any]:
    """Actividad de las tareas de aprendizaje, y si tuvieron efecto.

    Una tarea que corre y no cambia nada se marca `alive_but_no_effect`; contarla
    como éxito es lo que hace que un panel parezca vivo mientras no ocurre nada.
    """
    tipos = (
        "learning_candidate_deduplication",
        "learning_evidence_generation",
        "learning_evidence_review",
        "pending_learning_review",
        "stable_consolidation_review",
    )
    # La consulta declara su ventana. No la tenía: los campos se llamaban
    # `*_24h` y contaban el histórico entero. En producción eso hacía que
    # `pending_learning_review` reportase 205 ejecuciones "de 24 h" cuando en
    # 24 h reales habían corrido 40.
    filas = _rows(
        "SELECT task_type, status, count(*) n, max(updated_at) last_run"
        " FROM autonomous_tasks WHERE updated_at > ?"
        " GROUP BY task_type, status",
        (_desde_hace_24h(),),
    )
    por_tipo: dict[str, dict[str, Any]] = {
        t: {
            "task_type": t,
            "scheduled_24h": 0,
            "completed_24h": 0,
            "skipped_24h": 0,
            "failed_24h": 0,
            "blocked_24h": 0,
            "last_run": None,
            "last_effect": None,
            "reason": "Tipo de tarea no registrado todavía en autonomous_tasks.",
        }
        for t in tipos
    }
    for fila in filas:
        t = str(fila.get("task_type") or "")
        if t not in por_tipo:
            continue
        estado = str(fila.get("status") or "")
        n = int(fila.get("n") or 0)
        por_tipo[t]["scheduled_24h"] += n
        clave = {
            "completed": "completed_24h",
            "skipped": "skipped_24h",
            "failed": "failed_24h",
            "blocked": "blocked_24h",
        }.get(estado)
        if clave:
            por_tipo[t][clave] += n
        por_tipo[t]["last_run"] = fila.get("last_run")
        por_tipo[t]["reason"] = ""

    # El efecto se mide en la misma ventana que las ejecuciones. Antes salía de
    # un contador global de por vida (`resumen.evidence_verified`), así que un
    # único saber verificado —creado una vez, por un script— etiquetaba a todos
    # los tipos como `produced_knowledge` para siempre. El panel llegó a decir
    # `produced_knowledge` junto a `learned_today: 0`.
    saberes_en_ventana = _rows(
        "SELECT count(*) n FROM learning_queue"
        " WHERE status IN ('evidence_verified','stable') AND updated_at > ?",
        (_desde_hace_24h(),),
    )
    hubo_saber = int(saberes_en_ventana[0]["n"]) > 0 if saberes_en_ventana else False
    for datos in por_tipo.values():
        if datos["scheduled_24h"] == 0:
            datos["last_effect"] = "never_scheduled"
        elif not hubo_saber:
            datos["last_effect"] = "alive_but_no_effect"
            datos["reason"] = (
                "La tarea se ejecuta, pero ningún candidato llegó a ser saber."
            )
        else:
            datos["last_effect"] = "produced_knowledge"
    return {"tasks": list(por_tipo.values())}
