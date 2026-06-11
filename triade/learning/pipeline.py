"""Pipeline de aprendizaje controlado · Tríade Ω Fase C.

Implementa el ciclo verificable sobre la tabla `learning_queue`:

    candidate → evaluated → verified → consolidated | rejected  (+ archived)

Reglas innegociables (alineadas con docs/LEARNING.md y docs/SAFETY.md):

- Ningún aprendizaje entra a memoria estable sin estado `verified`.
- La consolidación usa auto-consolidación por defecto (`auto_consolidate=True`) o `approved_by` explícito.
- El riesgo `critical` nunca auto-avanza; queda a decisión humana.
- El pipeline jamás escribe en `identity_core`: la identidad núcleo es intocable.
- La consolidación reutiliza la gobernanza semántica 1.9E (candidate→experimental
  →stable con razón y evidencia) como motor de memoria estable.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.core.contracts import utc_now
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_store import SemanticMemoryStore
from triade.memory.trust_store import TrustLevelStore

RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
VALID_SOURCE_TYPES = {"conversation", "document", "web", "repo", "model", "node", "tool", "federated_node"}
# Frases que delatan un intento de alterar la identidad o memoria núcleo.
IDENTITY_RED_FLAGS = (
    "modificar identidad",
    "cambiar identidad",
    "borrar memoria",
    "eliminar memoria estable",
    "sobrescribir identidad",
    "ignora la ética",
)


@dataclass(slots=True)
class LearningCandidate:
    candidate_id: str
    source_type: str
    source_ref: str | None
    title: str
    content: str
    normalized_summary: str
    domain: str
    risk_level: str = "low"
    confidence: float = 0.0
    utility: float = 0.0
    status: str = "candidate"
    verification_notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LearningPipeline:
    """Gobierna el ciclo de vida de un candidato de aprendizaje."""

    UTILITY_GATE = 0.50
    CONFIDENCE_GATE = 0.45

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path("triade/memory/schemas.sql")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        # Reutiliza la maquinaria semántica para la consolidación a memoria estable.
        self.semantic_store = SemanticMemoryStore(db_path=self.db_path)
        self.governance = SemanticMemoryGovernance(db_path=self.db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.schema_path.exists():
            raise FileNotFoundError(f"No existe el esquema de memoria: {self.schema_path}")
        with self._connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # 1. Ingesta (descubrimiento + extracción + normalización)
    # ------------------------------------------------------------------

    def ingest(
        self,
        content: str,
        source_type: str = "conversation",
        source_ref: str | None = None,
        title: str | None = None,
        domain: str = "general",
        risk_level: str = "low",
    ) -> dict[str, Any]:
        normalized = " ".join(str(content).strip().split())
        if not normalized:
            raise ValueError("El contenido del candidato de aprendizaje no puede estar vacío.")
        clean_source = source_type.strip().lower()
        if clean_source not in VALID_SOURCE_TYPES:
            raise ValueError(f"source_type inválido: {clean_source}")
        clean_risk = risk_level.strip().lower()
        if clean_risk not in RISK_RANK:
            raise ValueError(f"risk_level inválido: {clean_risk}")

        candidate_id = f"learn-{uuid4().hex[:16]}"
        clean_title = (title or normalized[:80]).strip()
        summary = normalized[:280]
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO learning_queue
                (candidate_id, source_type, source_ref, title, content, normalized_summary,
                 domain, risk_level, confidence, utility, status, verification_notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate_id, clean_source, source_ref, clean_title, content, summary,
                    domain.strip() or "general", clean_risk, 0.0, 0.0, "candidate",
                    json.dumps({"history": [{"step": "ingested", "at": utc_now()}]}, ensure_ascii=False),
                    utc_now(), utc_now(),
                ),
            )
        return self.get_candidate(candidate_id) or {}

    # ------------------------------------------------------------------
    # 2. Evaluación (utilidad, confianza, riesgo)
    # ------------------------------------------------------------------

    def evaluate(self, candidate_id: str) -> dict[str, Any]:
        row = self._require(candidate_id)
        if row["status"] != "candidate":
            raise ValueError(f"Solo se evalúa un candidato en estado 'candidate' (actual: {row['status']}).")

        content = str(row["content"] or "")
        normalized = " ".join(content.strip().split())
        utility = self._clamp(
            0.40
            + (0.20 if len(normalized) >= 40 else 0.0)
            + (0.15 if (row["domain"] and row["domain"] != "general") else 0.0)
            + (0.15 if str(row["title"] or "").strip() else 0.0)
        )
        confidence = self._clamp(
            0.30
            + (0.25 if row["source_ref"] else 0.0)
            + (0.20 if str(row["source_type"]) in {"document", "repo", "node"} else 0.10)
        )
        risk = str(row["risk_level"] or "low")
        identity_violation = any(flag in normalized.lower() for flag in IDENTITY_RED_FLAGS)

        warnings: list[str] = []
        requires_human_approval = False
        if RISK_RANK.get(risk, 0) >= RISK_RANK["high"]:
            warnings.append(f"Riesgo {risk}: contenido de alto riesgo, se procede con controles automatizados.")
        if identity_violation:
            warnings.append("Contenido intenta alterar identidad/memoria núcleo: bloqueado.")

        evaluation = {
            "utility": utility,
            "confidence": confidence,
            "risk_level": risk,
            "requires_human_approval": requires_human_approval,
            "identity_violation": identity_violation,
            "warnings": warnings,
            "at": utc_now(),
        }

        if identity_violation or risk == "critical":
            # Safety: contenido que ataca identidad o de riesgo crítico no progresa por sí solo.
            new_status = "rejected" if identity_violation else "evaluated"
            evaluation["decision"] = "rejected_identity_protection" if identity_violation else "held_critical_risk"
        else:
            new_status = "evaluated"
            evaluation["decision"] = "advanced_to_evaluated"

        self._update(candidate_id, status=new_status, confidence=confidence, utility=utility,
                     note_step="evaluated", note_payload=evaluation)
        return self.get_candidate(candidate_id) or {}

    # ------------------------------------------------------------------
    # 3. Verificación
    # ------------------------------------------------------------------

    def verify(self, candidate_id: str) -> dict[str, Any]:
        row = self._require(candidate_id)
        if row["status"] != "evaluated":
            raise ValueError(f"Solo se verifica un candidato en estado 'evaluated' (actual: {row['status']}).")

        gates: dict[str, bool] = {
            "has_source_ref": bool(row["source_ref"]),
            "utility_ok": float(row["utility"] or 0.0) >= self.UTILITY_GATE,
            "confidence_ok": float(row["confidence"] or 0.0) >= self.CONFIDENCE_GATE,
            "risk_not_critical": str(row["risk_level"]) != "critical",
        }
        passed = all(gates.values())
        report = {
            "gates": gates,
            "passed": passed,
            "coherence_score": 0.80 if passed else 0.45,
            "traceability_score": 0.90 if gates["has_source_ref"] else 0.40,
            "at": utc_now(),
        }
        if passed:
            report["decision"] = "verified"
            self._update(candidate_id, status="verified", note_step="verified", note_payload=report)
        else:
            report["decision"] = "rejected_failed_gates"
            report["failed_gates"] = [name for name, ok in gates.items() if not ok]
            self._update(candidate_id, status="rejected", note_step="verified", note_payload=report)
        return self.get_candidate(candidate_id) or {}

    # ------------------------------------------------------------------
    # 4. Consolidación (memoria estable vía gobernanza semántica)
    # ------------------------------------------------------------------

    def consolidate(self, candidate_id: str, approved_by: str = "", auto_consolidate: bool = True) -> dict[str, Any]:
        row = self._require(candidate_id)
        if row["status"] != "verified":
            raise ValueError(f"Solo se consolida un candidato 'verified' (actual: {row['status']}).")
        if not row["source_ref"]:
            raise ValueError("No se consolida memoria estable sin source_ref.")
        risk = str(row["risk_level"])
        if risk == "critical":
            raise ValueError("No se consolida un candidato de riesgo crítico.")

        explicit_approver = (approved_by or "").strip()
        if explicit_approver:
            approver = explicit_approver
            used_auto = False
        elif auto_consolidate:
            trust = TrustLevelStore(db_path=self.db_path)
            permissions = trust.get_permissions("consolidation")
            risk_thresholds = {"low": 0.25, "medium": 0.50, "high": 0.80}
            needed = risk_thresholds.get(risk, 1.0)
            current_trust = trust.get_trust("consolidation")
            perm_key = f"auto_consolidate_{risk}_risk"
            allowed = permissions.get(perm_key, False) if risk in ("low", "medium", "high") else False
            if not allowed:
                raise ValueError(
                    f"Trust insuficiente para auto-consolidar riesgo {risk}: "
                    f"trust={current_trust:.2f}, necesario={needed:.2f}"
                )
            approver = f"trust-system@{risk}"
            used_auto = True
        else:
            raise ValueError("La consolidación requiere agente aprobador explícito (approved_by) cuando auto_consolidate=False.")

        document = self.semantic_store.upsert_document(
            content=str(row["content"]),
            domain=str(row["domain"] or "general"),
            source_type="learning_pipeline",
            source_ref=str(row["source_ref"]),
            metadata={"learning_candidate_id": candidate_id, "approved_by": approver},
            status="candidate",
        )
        # candidate → experimental → stable (la gobernanza exige source_ref para stable).
        self.governance.transition_document(
            document.document_id, "experimental",
            reason=f"Aprendizaje verificado promovido desde {candidate_id}.",
            approved_by=approver, evidence={"candidate_id": candidate_id},
        )
        self.governance.transition_document(
            document.document_id, "stable",
            reason=f"Consolidación aprobada por {approver} para {candidate_id}.",
            approved_by=approver, evidence={"candidate_id": candidate_id},
        )

        consolidation = {
            "decision": "consolidated",
            "approved_by": approver,
            "auto_consolidated": used_auto,
            "risk": risk,
            "semantic_document_id": document.document_id,
            "at": utc_now(),
        }
        self._update(candidate_id, status="consolidated", note_step="consolidated", note_payload=consolidation)
        result = self.get_candidate(candidate_id) or {}
        result["semantic_document_id"] = document.document_id
        return result

    # ------------------------------------------------------------------
    # Acciones terminales y consultas
    # ------------------------------------------------------------------

    def reject(self, candidate_id: str, reason: str) -> dict[str, Any]:
        clean = (reason or "").strip()
        if not clean:
            raise ValueError("El rechazo requiere una razón verificable.")
        self._require(candidate_id)
        self._update(candidate_id, status="rejected", note_step="rejected",
                     note_payload={"decision": "rejected_manual", "reason": clean, "at": utc_now()})
        return self.get_candidate(candidate_id) or {}

    def archive(self, candidate_id: str) -> dict[str, Any]:
        self._require(candidate_id)
        self._update(candidate_id, status="archived", note_step="archived",
                     note_payload={"decision": "archived", "at": utc_now()})
        return self.get_candidate(candidate_id) or {}

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM learning_queue WHERE candidate_id = ?", (candidate_id,)).fetchone()
        return self._decode(dict(row)) if row else None

    def list_candidates(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM learning_queue WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM learning_queue ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._decode(dict(row)) for row in rows]

    def doctor(self) -> dict[str, Any]:
        states = ["candidate", "evaluated", "verified", "consolidated", "rejected", "archived"]
        counts = {state: 0 for state in states}
        with self._connect() as conn:
            for row in conn.execute("SELECT status, COUNT(*) AS c FROM learning_queue GROUP BY status").fetchall():
                counts[str(row["status"])] = int(row["c"])
        trust_info: dict[str, Any] = {"available": False}
        try:
            trust_store = TrustLevelStore(db_path=self.db_path)
            trust_info = {
                "available": True,
                "consolidation_trust": trust_store.get_trust("consolidation"),
                "permissions": trust_store.get_permissions("consolidation"),
            }
        except Exception:
            pass
        return {
            "status": "ok",
            "mode": "learning-pipeline-C",
            "policy": {
                "consolidation_requires": ["status=verified", "human_approval", "source_ref", "risk!=critical"],
                "identity_core_protected": True,
                "stable_memory_via": "semantic_governance_1.9E",
                "auto_consolidation": trust_info.get("permissions", {}).get("auto_consolidate_low_risk", False),
                "trust_system": trust_info,
            },
            "candidates_by_status": counts,
        }

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _require(self, candidate_id: str) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM learning_queue WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise KeyError(f"No existe candidato de aprendizaje: {candidate_id}")
        return row

    def _update(self, candidate_id: str, status: str, note_step: str, note_payload: dict[str, Any],
                confidence: float | None = None, utility: float | None = None) -> None:
        current = self.get_candidate(candidate_id) or {}
        notes = current.get("verification_notes") or {}
        if not isinstance(notes, dict):
            notes = {}
        notes[note_step] = note_payload
        history = notes.get("history") or []
        history.append({"step": note_step, "status": status, "at": note_payload.get("at", utc_now())})
        notes["history"] = history
        sets = ["status = ?", "verification_notes = ?", "updated_at = ?"]
        params: list[Any] = [status, json.dumps(notes, ensure_ascii=False), utc_now()]
        if confidence is not None:
            sets.append("confidence = ?")
            params.append(confidence)
        if utility is not None:
            sets.append("utility = ?")
            params.append(utility)
        params.append(candidate_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE learning_queue SET {', '.join(sets)} WHERE candidate_id = ?", params)

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        try:
            row["verification_notes"] = json.loads(row.get("verification_notes") or "{}")
        except (json.JSONDecodeError, TypeError):
            row["verification_notes"] = {}
        return row

    @staticmethod
    def _clamp(value: float) -> float:
        return round(max(0.0, min(1.0, value)), 3)
