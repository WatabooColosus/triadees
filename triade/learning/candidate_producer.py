"""Extrae una unidad aprendible de una experiencia real.

El corpus actual tiene 633 filas y ~200 contenidos únicos, casi todos
transcripciones de runs («run_id: … response: …») y plantillas autogeneradas.
Nada de eso es un saber: es el sistema copiándose a sí mismo.

Aquí se extrae **una proposición atómica** y sólo si es explícita y verificable.
La regla de oro: lo que aprende Tríade tiene que haberlo dicho la persona, no
haberlo inferido el modelo de su propia respuesta.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

PRODUCER_VERSION = "candidate-producer-1.0.0"

CandidateType = Literal["fact", "preference", "correction", "procedure", "rule"]

#: Sólo el turno de la persona funda una preferencia o una corrección. Aprender
#: de la propia respuesta del modelo es cómo se fabrican 633 transcripciones.
TRUSTED_ROLES: frozenset[str] = frozenset({"user", "human", "operator"})

MIN_CONTENT_CHARS = 12
MAX_CONTENT_CHARS = 600


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text))
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


def _sha(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


# ── señales de que hay una proposición, no una ocurrencia ─────────────

# Se aceptan indicativo y subjuntivo: «nunca incluyas» es tan explícito como
# «siempre incluye», y quedarse con una sola forma deja fuera media lengua.
_VERBOS_PREFERENCIA = (
    r"(?:usa\w*|use\w*|pon\w*|escrib\w*|empie\w*|empez\w*|comien\w*|"
    r"inici\w*|inclu\w*|formate\w*|orden\w*)"
)
_PREFERENCIA = re.compile(
    rf"\b(?:prefiero|prefiere|quiero que|siempre\s+{_VERBOS_PREFERENCIA}|"
    rf"{_VERBOS_PREFERENCIA}\s+siempre|"
    r"a partir de ahora|de ahora en adelante|por norma|por regla|"
    rf"usa primero|nunca\s+{_VERBOS_PREFERENCIA})\b"
)
_CORRECCION = re.compile(
    r"\b(?:no es|no era|est(?:a|á|aba)\s+mal|incorrecto|equivocado|"
    r"en realidad|corrige|correccion|lo correcto es)\b"
)
_HECHO = re.compile(
    r"\b(?:es|son|se llama|equivale a|corresponde a|el identificador|"
    r"la direccion|el telefono|la version)\b"
)
_PROCEDIMIENTO = re.compile(
    r"\b(?:primero|luego|despues|por ultimo|el paso|procedimiento|"
    r"para\s+\w+\s+hay que)\b"
)

#: Marcas de que la frase no afirma nada estable.
_ESPECULACION = re.compile(
    r"\b(?:quiza|quizas|tal vez|creo que|puede que|no estoy seguro|"
    r"probablemente|supongo|me parece que)\b"
)
# Se evalúa contra el texto ya normalizado, donde `run_id:` es `run id` y
# `verification_status` es `verification status`: los guiones bajos y los dos
# puntos ya no existen.
_AUTORREFERENCIA = re.compile(
    r"\b(?:soy triade|como asistente|como modelo|mi respuesta|"
    r"run id|verification status|source type|candidate id)\b"
)


@dataclass
class LearningCandidate:
    candidate_id: str
    content: str
    normalized_content: str
    type: CandidateType
    domain: str
    source_run_id: str
    source_message_ids: list[str] = field(default_factory=list)
    source_role: str = "user"
    provenance: str = ""
    explicitness_score: float = 0.0
    verifiability: str = "unknown"
    risk_level: str = "low"
    created_at: str = field(default_factory=_utc_now)
    content_hash: str = ""
    producer_version: str = PRODUCER_VERSION
    previous_value: str | None = None
    corrected_value: str | None = None
    postcondition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionResult:
    candidates: list[LearningCandidate] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "rejected": self.rejected,
            "producer_version": PRODUCER_VERSION,
        }


class ExperienceLearningCandidateProducer:
    """Convierte un mensaje real en, como mucho, un candidato aprendible."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    # ── extracción ───────────────────────────────────────────────────
    def produce(
        self,
        *,
        run_id: str,
        message: str,
        role: str,
        domain: str = "general",
        message_id: str | None = None,
    ) -> ProductionResult:
        result = ProductionResult()
        texto = " ".join(str(message or "").split())
        motivo = self._reject_reason(texto, role)
        if motivo:
            result.rejected.append({"content": texto[:120], "reason": motivo})
            return result

        tipo, extra = self._classify(texto)
        if tipo is None:
            result.rejected.append(
                {"content": texto[:120], "reason": "sin_proposicion_explicita"}
            )
            return result

        normalizado = _normalize(texto)
        candidato = LearningCandidate(
            candidate_id=f"exp-{uuid.uuid4().hex[:16]}",
            content=texto,
            normalized_content=normalizado,
            type=tipo,
            domain=domain,
            source_run_id=run_id,
            source_message_ids=[message_id or f"{run_id}:0"],
            source_role=role,
            provenance=f"run:{run_id}|role:{role}",
            explicitness_score=self._explicitness(texto, tipo),
            verifiability="deterministic" if tipo != "rule" else "declarative",
            risk_level="low",
            content_hash=_sha(texto),
            **extra,
        )
        result.candidates.append(candidato)
        return result

    def _reject_reason(self, texto: str, role: str) -> str | None:
        if role not in TRUSTED_ROLES:
            # Aprender de la salida del modelo es exactamente cómo se llenó la
            # cola de transcripciones.
            return f"rol_no_confiable:{role}"
        if len(texto) < MIN_CONTENT_CHARS:
            return "demasiado_corto"
        if len(texto) > MAX_CONTENT_CHARS:
            return "demasiado_largo"
        norm = _normalize(texto)
        if _AUTORREFERENCIA.search(norm):
            return "autorreferencial_o_transcripcion"
        if _ESPECULACION.search(norm):
            return "especulativo"
        return None

    @staticmethod
    def _classify(texto: str) -> tuple[CandidateType | None, dict[str, Any]]:
        norm = _normalize(texto)
        if _CORRECCION.search(norm):
            anterior, corregido = ExperienceLearningCandidateProducer._split_correction(
                texto
            )
            if not corregido:
                return None, {}
            return "correction", {
                "previous_value": anterior,
                "corrected_value": corregido,
            }
        if _PREFERENCIA.search(norm):
            return "preference", {}
        if _PROCEDIMIENTO.search(norm):
            return "procedure", {"postcondition": texto}
        if _HECHO.search(norm):
            return "fact", {}
        return None, {}

    @staticmethod
    def _split_correction(texto: str) -> tuple[str | None, str | None]:
        """Una corrección necesita el valor viejo y el nuevo, o no es corrección."""
        m = re.search(
            r"(.+?)\s*(?:no es|no era|est[aá] mal[,;]?)\s*(.+?)[.;]?\s*"
            r"(?:es|lo correcto es|en realidad es)\s+(.+)",
            texto,
            re.IGNORECASE,
        )
        if m:
            return m.group(2).strip(), m.group(3).strip()
        m = re.search(r"(.+?)\s+en realidad\s+(?:es|son)\s+(.+)", texto, re.IGNORECASE)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return None, None

    @staticmethod
    def _explicitness(texto: str, tipo: CandidateType) -> float:
        norm = _normalize(texto)
        score = 0.5
        if tipo in ("preference", "correction"):
            score += 0.3
        if re.search(r"\b(?:siempre|nunca|debe|hay que)\b", norm):
            score += 0.2
        return round(min(score, 1.0), 3)

    # ── persistencia por la cola existente ───────────────────────────
    def persist(self, candidato: LearningCandidate) -> bool:
        """Escribe en `learning_queue`. Idempotente por contenido normalizado."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            ya = conn.execute(
                "SELECT candidate_id FROM learning_queue WHERE normalized_summary = ?",
                (candidato.normalized_content,),
            ).fetchone()
            if ya:
                return False
            conn.execute(
                """INSERT INTO learning_queue
                   (candidate_id, source_type, source_ref, title, content,
                    normalized_summary, domain, risk_level, confidence, utility,
                    status, verification_notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    candidato.candidate_id,
                    "experience",
                    f"run:{candidato.source_run_id}",
                    f"{candidato.type}: {candidato.content[:60]}",
                    candidato.content,
                    candidato.normalized_content,
                    candidato.domain,
                    candidato.risk_level,
                    candidato.explicitness_score,
                    0.9,
                    "internally_checked",
                    json.dumps(
                        {
                            "producer": PRODUCER_VERSION,
                            "type": candidato.type,
                            "role": candidato.source_role,
                        },
                        ensure_ascii=False,
                    ),
                    candidato.created_at,
                    candidato.created_at,
                ),
            )
        return True
