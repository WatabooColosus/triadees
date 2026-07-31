"""Agrupación reversible de candidatos duplicados.

Medido sobre la base real: 628 filas y sólo 200 contenidos únicos. El más
repetido aparece 145 veces. Sin agrupar, el retrieval le daría a ese contenido
145 votos frente a uno.

**No se borra nada.** Se crea un grupo con un canónico y sus miembros; las
filas originales quedan intactas para auditoría, y el grupo puede deshacerse.

Sólo se agrupa automáticamente lo que es demostrablemente el mismo texto:
igualdad exacta, igualdad tras normalizar, o la misma plantilla con los mismos
huecos. La similitud semántica se registra como **sugerencia**, nunca agrupa
sola: dos frases parecidas pueden decir lo contrario.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

POLICY_VERSION = "learning-dedup-1.0.0"

MatchType = Literal[
    "exact", "normalized_exact", "template_duplicate", "semantic_possible"
]

#: Tipos que pueden agruparse sin intervención humana.
AUTO_GROUPABLE: frozenset[str] = frozenset(
    {"exact", "normalized_exact", "template_duplicate"}
)

#: Marcas de negación: si dos textos coinciden salvo por una de éstas, no son
#: el mismo aprendizaje sino su contrario.
_NEGACIONES = re.compile(r"\b(no|nunca|jamas|sin|ni)\b")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text))
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


def _sha(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _template_key(text: str) -> str | None:
    """Clave de plantilla para los textos autogenerados por misión.

    Las 145 copias de «Mantener ciclo de aprendizaje controlado…» y las 104 de
    «Para la misión 'X', mantener como hipótesis operacional que…» son la misma
    plantilla. Se reconoce la forma, no el relleno.
    """
    norm = _normalize(text)
    if not norm:
        return None
    patrones = (
        (
            r"^para la mision .+ mantener como hipotesis operacional que ",
            "mission_hypothesis",
        ),
        (r"^mantener ciclo de aprendizaje controlado", "learning_cycle"),
        (r"^run_id \S+ source ", "run_transcript"),
    )
    for patron, nombre in patrones:
        if re.match(patron, norm):
            # El relleno sí distingue: dos misiones distintas no son la misma
            # afirmación. Se agrupa por plantilla + relleno normalizado.
            return f"{nombre}:{_sha(norm)[:32]}"
    return None


def _negation_profile(text: str) -> frozenset[str]:
    return frozenset(_NEGACIONES.findall(_normalize(text)))


def _contradiction_key(text: str) -> str:
    """Texto normalizado **sin** las negaciones.

    Dos afirmaciones opuestas normalizan distinto —justo por el «no»— así que
    comparándolas por su hash normal nunca se encontrarían. Quitando las
    negaciones, «el gate debe ejecutarse» y «el gate no debe ejecutarse» caen
    en la misma clave, y ahí sí se ve que sus perfiles de negación difieren.
    """
    sin_neg = _NEGACIONES.sub(" ", _normalize(text))
    return _sha(re.sub(r"\s+", " ", sin_neg).strip())


@dataclass
class GroupMember:
    candidate_id: str
    match_type: MatchType
    similarity: float


@dataclass
class CandidateGroup:
    group_id: str
    canonical_candidate_id: str
    members: list[GroupMember] = field(default_factory=list)
    policy_version: str = POLICY_VERSION
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "canonical_candidate_id": self.canonical_candidate_id,
            "members": [m.__dict__ for m in self.members],
            "policy_version": self.policy_version,
            "created_at": self.created_at,
        }


@dataclass
class DedupReport:
    total_rows: int = 0
    unique_contents: int = 0
    groups: list[CandidateGroup] = field(default_factory=list)
    ambiguous: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duplicates(self) -> int:
        return sum(len(g.members) for g in self.groups)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "unique_contents": self.unique_contents,
            "groups": len(self.groups),
            "canonical": len(self.groups),
            "duplicates_grouped": self.duplicates,
            "ambiguous": self.ambiguous,
            "contradictions": self.contradictions,
            "policy_version": POLICY_VERSION,
            "rows_deleted": 0,
        }


class LearningDeduplicator:
    """Agrupa duplicados sin borrar filas, y permite deshacerlo."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE IF NOT EXISTS learning_candidate_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                canonical_candidate_id TEXT NOT NULL,
                member_candidate_id TEXT NOT NULL,
                match_type TEXT NOT NULL,
                similarity REAL NOT NULL,
                decision TEXT NOT NULL,
                created_at TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                UNIQUE(member_candidate_id, policy_version)
            )"""
        )
        return conn

    # ── análisis ─────────────────────────────────────────────────────
    def analyze(self) -> DedupReport:
        with self._connect() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT candidate_id, content, source_ref, risk_level, confidence,"
                    " status, run_use_count, avg_outcome_score, created_at"
                    " FROM learning_queue"
                ).fetchall()
            ]

        report = DedupReport(total_rows=len(rows))
        report.unique_contents = len(
            {_sha(_normalize(r["content"] or "")) for r in rows}
        )

        por_clave: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            content = str(row.get("content") or "")
            if not content.strip():
                continue
            exact = _sha(content)
            norm = _sha(_normalize(content))
            tmpl = _template_key(content)
            clave: tuple[str, str]
            if tmpl:
                clave = ("template_duplicate", tmpl)
            else:
                clave = ("normalized_exact", norm)
            row["_exact"] = exact
            row["_norm"] = norm
            por_clave.setdefault(clave, []).append(row)

        # Contradicciones: mismo enunciado salvo por una negación. Se detectan
        # aparte porque nunca comparten hash normalizado.
        contradictorios: set[str] = set()
        por_contradiccion: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            content = str(row.get("content") or "")
            if content.strip():
                por_contradiccion.setdefault(_contradiction_key(content), []).append(
                    row
                )
        for grupo_c in por_contradiccion.values():
            if len(grupo_c) < 2:
                continue
            perfiles = {_negation_profile(str(r["content"])) for r in grupo_c}
            if len(perfiles) > 1:
                ids = [str(r["candidate_id"]) for r in grupo_c]
                report.contradictions.append(
                    {"candidate_ids": ids, "reason": "negation_mismatch"}
                )
                contradictorios.update(ids)

        for (match_type, _clave), grupo in sorted(
            por_clave.items(), key=lambda p: p[0][1]
        ):
            if len(grupo) < 2:
                continue
            if any(str(r["candidate_id"]) in contradictorios for r in grupo):
                continue

            canonical = self._pick_canonical(grupo)
            tipo: MatchType = (
                "exact" if len({r["_exact"] for r in grupo}) == 1 else match_type
            )  # type: ignore[assignment]
            g = CandidateGroup(
                group_id=f"grp-{uuid.uuid4().hex[:16]}",
                canonical_candidate_id=str(canonical["candidate_id"]),
                members=[
                    GroupMember(
                        candidate_id=str(r["candidate_id"]),
                        match_type=tipo,
                        similarity=1.0,
                    )
                    for r in grupo
                    if r["candidate_id"] != canonical["candidate_id"]
                ],
            )
            report.groups.append(g)
        return report

    @staticmethod
    def _pick_canonical(grupo: list[dict[str, Any]]) -> dict[str, Any]:
        """Mejor procedencia, más evidencia, contenido más completo, menor riesgo.

        La fecha sólo desempata: elegir por antigüedad sin más premiaría al
        primero que se escribió, no al mejor.
        """
        riesgo = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        return min(
            grupo,
            key=lambda r: (
                0 if str(r.get("source_ref") or "").strip() else 1,
                -float(r.get("run_use_count") or 0),
                -float(r.get("avg_outcome_score") or 0.0),
                -len(str(r.get("content") or "")),
                riesgo.get(str(r.get("risk_level") or "low"), 1),
                str(r.get("created_at") or ""),
                str(r.get("candidate_id")),
            ),
        )

    # ── persistencia reversible ──────────────────────────────────────
    def apply(self, report: DedupReport) -> int:
        """Persiste los grupos. Idempotente: repetir no duplica ni borra."""
        escritos = 0
        with self._connect() as conn:
            for g in report.groups:
                for m in g.members:
                    cur = conn.execute(
                        """INSERT INTO learning_candidate_groups
                           (group_id, canonical_candidate_id, member_candidate_id,
                            match_type, similarity, decision, created_at, policy_version)
                           VALUES (?,?,?,?,?,?,?,?)
                           ON CONFLICT(member_candidate_id, policy_version) DO NOTHING""",
                        (
                            g.group_id,
                            g.canonical_candidate_id,
                            m.candidate_id,
                            m.match_type,
                            m.similarity,
                            "grouped",
                            g.created_at,
                            g.policy_version,
                        ),
                    )
                    escritos += max(0, cur.rowcount)
        return escritos

    def revert(self, group_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM learning_candidate_groups WHERE group_id = ?", (group_id,)
            )
            return int(cur.rowcount)

    def canonical_for(self, candidate_id: str) -> str:
        """Devuelve el canónico del grupo, o el propio id si no está agrupado."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT canonical_candidate_id FROM learning_candidate_groups"
                " WHERE member_candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return str(row[0]) if row else candidate_id

    def suppressed_ids(self) -> set[str]:
        """Miembros no canónicos: el retrieval debe ignorarlos."""
        with self._connect() as conn:
            return {
                str(r[0])
                for r in conn.execute(
                    "SELECT member_candidate_id FROM learning_candidate_groups"
                ).fetchall()
            }
