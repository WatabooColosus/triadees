"""Proyección honesta de lo que Tríade Ω sabe, para que un humano lo vea.

El usuario decía «no veo que pase nada ni saberes» teniendo 633 candidatos en
la base y 1661 tests en verde. Tenía razón, y el motivo era doble:

1. No existía ninguna vista de "saber": `/api/knowledge/*` daba 404.
2. Lo que sí se mostraba mentía. `learning_journal` contaba como
   `candidates_verified` a los que están en `internally_checked` —el estado
   atascado, el que significa justamente que **nadie** tiene evidencia— y como
   `evidence_created` a filas de `neuron_evidence`, que es otra tabla.

Aquí un candidato **no es** un saber. Un saber es algo que se puede recuperar,
inyectar y cuyo efecto está medido. Si no hay ninguno, este servicio devuelve
cero y lo dice; nunca rellena el hueco con actividad.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from triade.db import sqlite3

VISIBILITY_VERSION = "knowledge-visibility-1.0.0"

KnowledgeState = Literal[
    "stable",
    "evidence_verified",
    "experimental",
    "candidate",
    "rejected",
    "quarantined",
    "duplicate",
]

#: Estados que el usuario puede leer como "Tríade sabe esto".
USER_VISIBLE_STATES: frozenset[str] = frozenset({"stable", "evidence_verified"})

#: Estados que pueden entrar en el contexto de un run.
INJECTABLE_STATES: frozenset[str] = frozenset(
    {"stable", "evidence_verified", "experimental"}
)

_DB_STATE_MAP: dict[str, KnowledgeState] = {
    "stable": "stable",
    "consolidated": "stable",
    "evidence_verified": "evidence_verified",
    "validated_in_runs": "experimental",
    "experimental": "experimental",
    "internally_checked": "candidate",
    "candidate": "candidate",
    "evaluated": "candidate",
    "rejected": "rejected",
    "regressed": "rejected",
    "quarantined": "quarantined",
    "blocked": "quarantined",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    for intento in (text, text.replace(" ", "T")):
        try:
            dt = datetime.fromisoformat(intento)
        except ValueError:
            continue
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return None


@dataclass
class KnowledgeItem:
    """Un saber, tal y como puede enseñarse a una persona."""

    knowledge_id: str
    title: str
    summary: str
    domain: str
    state: KnowledgeState
    confidence: float
    source_run_ids: list[str] = field(default_factory=list)
    evidence_status: str = "none"
    last_used_at: str | None = None
    use_count_causal: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    risk: str = "low"
    reason: str = ""
    version: str = ""
    content_hash: str = ""
    effect_delta: float | None = None
    regression_status: str = "not_run"
    is_retrievable: bool = False
    is_injectable: bool = False
    is_stable: bool = False
    is_visible_to_user: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeSummary:
    stable: int = 0
    evidence_verified: int = 0
    experimental: int = 0
    candidates: int = 0
    rejected: int = 0
    quarantined: int = 0
    duplicates: int = 0
    used_today: int = 0
    learned_today: int = 0
    last_learning_at: str | None = None
    last_learning_used_at: str | None = None
    status: str = ""
    visibility_version: str = VISIBILITY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeVisibilityService:
    """Traduce las tablas internas a saberes legibles. Única fuente para la UI."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
        """Una tabla ausente es un cero legítimo, no un fallo del servicio.

        Las tablas de deduplicación, retrieval y safety sólo existen cuando esos
        componentes han corrido alguna vez. Que falten es información: significa
        «todavía no ha pasado».
        """
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.Error:
            return []

    # ── inventario ───────────────────────────────────────────────────
    def list_knowledge(
        self, *, limit: int = 50, states: set[str] | None = None
    ) -> list[KnowledgeItem]:
        with self._connect() as conn:
            filas = self._rows(
                conn,
                "SELECT candidate_id, title, content, normalized_summary, domain,"
                " risk_level, confidence, status, source_ref, created_at, updated_at,"
                " run_use_count FROM learning_queue ORDER BY updated_at DESC, id DESC",
            )
            evidencias = {
                str(e["candidate_id"]): e
                for e in self._rows(conn, "SELECT * FROM learning_evidence")
            }
            suprimidos = {
                str(r["member_candidate_id"])
                for r in self._rows(
                    conn,
                    "SELECT member_candidate_id FROM learning_candidate_groups",
                )
            }
            usos = self._usage_index(conn)

        items: list[KnowledgeItem] = []
        for fila in filas:
            cid = str(fila.get("candidate_id") or "")
            if cid in suprimidos:
                estado: KnowledgeState = "duplicate"
            else:
                estado = _DB_STATE_MAP.get(str(fila.get("status") or ""), "candidate")

            ev = evidencias.get(cid)
            estado, evidencia_estado, delta, regresion = self._apply_evidence(
                estado, ev
            )

            if states and estado not in states:
                continue

            uso = usos.get(cid, {})
            resumen = str(
                fila.get("normalized_summary") or fila.get("content") or ""
            ).strip()
            items.append(
                KnowledgeItem(
                    knowledge_id=cid,
                    title=str(fila.get("title") or cid),
                    summary=resumen[:400],
                    domain=str(fila.get("domain") or "general"),
                    state=estado,
                    confidence=float(fila.get("confidence") or 0.0),
                    source_run_ids=[str(fila.get("source_ref") or "")]
                    if fila.get("source_ref")
                    else [],
                    evidence_status=evidencia_estado,
                    last_used_at=uso.get("last_used_at"),
                    use_count_causal=int(uso.get("count") or 0),
                    created_at=str(fila.get("created_at") or ""),
                    updated_at=str(fila.get("updated_at") or ""),
                    risk=str(fila.get("risk_level") or "low"),
                    reason=self._reason(estado, evidencia_estado),
                    version=str(fila.get("updated_at") or ""),
                    content_hash="",
                    effect_delta=delta,
                    regression_status=regresion,
                    is_retrievable=estado in INJECTABLE_STATES,
                    is_injectable=estado in INJECTABLE_STATES,
                    is_stable=estado == "stable",
                    is_visible_to_user=estado in USER_VISIBLE_STATES,
                )
            )
            if len(items) >= limit:
                break
        return items

    @staticmethod
    def _apply_evidence(
        estado: KnowledgeState, ev: dict | None
    ) -> tuple[KnowledgeState, str, float | None, str]:
        """La evidencia manda sobre el estado declarado, nunca al revés."""
        if not ev:
            return estado, "none", None, "not_run"

        completa = bool(
            ev.get("baseline_evaluation_json")
            and ev.get("candidate_evaluation_json")
            and ev.get("comparison_json")
        )
        decision = str(ev.get("decision") or "pending")
        regresion = "passed" if ev.get("regression_report_id") else "not_run"

        delta: float | None = None
        comparison = ev.get("comparison_json")
        if comparison:
            try:
                delta = float(json.loads(comparison).get("absolute_delta"))
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                delta = None

        if not completa:
            # Una evidencia a medias no asciende a nadie.
            return estado, f"incomplete:{decision}", delta, regresion
        if decision == "improved" and regresion == "passed":
            return "evidence_verified", "complete:improved", delta, regresion
        if decision in ("regressed", "rejected"):
            return "rejected", f"complete:{decision}", delta, regresion
        return estado, f"complete:{decision}", delta, regresion

    @staticmethod
    def _reason(estado: KnowledgeState, evidencia: str) -> str:
        if estado == "candidate":
            return (
                "Candidato sin evidencia: no se muestra como saber ni entra en "
                "el contexto."
            )
        if estado == "duplicate":
            return "Agrupado con un canónico; no se cuenta dos veces."
        if estado == "quarantined":
            return "Retenido por el filtro de seguridad."
        if estado == "rejected":
            return f"Descartado ({evidencia})."
        if estado == "evidence_verified":
            return "Efecto medido y sin regresiones: usable como saber experimental."
        if estado == "stable":
            return "Consolidado por vía gobernada."
        return "Experimental y reversible."

    def _usage_index(self, conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        """Usos **causales**: sólo lo que se inyectó antes de generar la respuesta.

        No se cuenta `run_use_count`: ese contador sube comparando la salida ya
        generada contra los candidatos, así que no prueba que el modelo lo viera.
        """
        index: dict[str, dict[str, Any]] = {}
        for fila in self._rows(
            conn,
            "SELECT injected_ids, created_at FROM learning_retrieval_decisions"
            " ORDER BY id DESC LIMIT 500",
        ):
            try:
                ids = json.loads(fila.get("injected_ids") or "[]")
            except json.JSONDecodeError:
                continue
            for cid in ids:
                entrada = index.setdefault(str(cid), {"count": 0, "last_used_at": None})
                entrada["count"] += 1
                if not entrada["last_used_at"]:
                    entrada["last_used_at"] = fila.get("created_at")
        return index

    def get_knowledge(self, knowledge_id: str) -> KnowledgeItem | None:
        for item in self.list_knowledge(limit=100_000):
            if item.knowledge_id == knowledge_id:
                return item
        return None

    # ── resumen ──────────────────────────────────────────────────────
    def summary(self) -> KnowledgeSummary:
        items = self.list_knowledge(limit=100_000)
        s = KnowledgeSummary()
        for item in items:
            if item.state == "stable":
                s.stable += 1
            elif item.state == "evidence_verified":
                s.evidence_verified += 1
            elif item.state == "experimental":
                s.experimental += 1
            elif item.state == "candidate":
                s.candidates += 1
            elif item.state == "rejected":
                s.rejected += 1
            elif item.state == "quarantined":
                s.quarantined += 1
            elif item.state == "duplicate":
                s.duplicates += 1

        desde = _utc_now() - timedelta(hours=24)
        for item in items:
            creado = _parse_ts(item.created_at)
            if creado and creado >= desde and item.is_visible_to_user:
                s.learned_today += 1
            usado = _parse_ts(item.last_used_at)
            if usado and usado >= desde:
                s.used_today += 1

        visibles = [i for i in items if i.is_visible_to_user]
        if visibles:
            s.last_learning_at = max(
                (i.updated_at or "" for i in visibles), default=None
            )
        usados = [i.last_used_at for i in items if i.last_used_at]
        s.last_learning_used_at = max(usados) if usados else None
        s.status = self._status_phrase(s)
        return s

    @staticmethod
    def _status_phrase(s: KnowledgeSummary) -> str:
        """Una frase que no promete más de lo que hay."""
        if s.stable or s.evidence_verified:
            return (
                f"{s.stable + s.evidence_verified} saberes utilizables; "
                f"{s.candidates} candidatos aún sin evidencia."
            )
        if s.candidates:
            return (
                f"Sin saberes todavía: {s.candidates} candidatos en cola, ninguno "
                "con evidencia de mejora. Un candidato no es un saber."
            )
        return "Sin candidatos ni saberes registrados."
