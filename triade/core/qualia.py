"""Qualia de Triade: estado vivo integrado del sistema.

Qualia no afirma conciencia humana. Es el plano donde Tríade integra sus
sentidos internos: pulso vivo, memoria semántica, órganos y límites para saber
qué ocurre ahora.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .life_pulse import LIFE_PULSE, LifePulseEngine


@dataclass(slots=True)
class QualiaEngine:
    """Integra estado vivo y memoria semántica gobernada."""

    db_path: str | Path = "triade/memory/triade.db"
    life_pulse: LifePulseEngine = field(default_factory=lambda: LIFE_PULSE)

    def snapshot(self, refresh_life: bool = False) -> dict[str, Any]:
        life = self.life_pulse.tick() if refresh_life else self.life_pulse.snapshot()
        if int(life.get("counters", {}).get("cycles") or 0) == 0:
            life = self.life_pulse.tick()
        semantic = self._semantic_alignment()
        identity = self._identity_core()
        organs = self._organs(life, semantic)
        return {
            "status": "ok" if life.get("status") == "ok" and semantic.get("status") == "ok" else "degraded",
            "mode": "qualia",
            "definition": "estado vivo integrado: sentidos internos + memoria semantica gobernada + organos + limites",
            "senses": self._senses(life, semantic),
            "organs": organs,
            "identity": identity,
            "semantic_alignment": semantic,
            "life_pulse": {
                "status": life.get("status"),
                "running": life.get("running"),
                "counters": life.get("counters", {}),
                "reflection": life.get("reflection", {}),
                "integrity": life.get("integrity", {}),
                "policy": life.get("policy", {}),
            },
            "triade_map": {
                "triade": "entidad operativa local auditada",
                "neurona_central": "planea y responde",
                "n_formadora": "evalua neuronas candidatas",
                "n_creadora": "crea especificaciones de neuronas",
                "hipotalamo": "analiza intencion, urgencia, riesgo y tono",
                "vector_emocional": "PV-7 y senales afectivo-cognitivas",
                "bodega": "almacenamiento local, episodico, semantico y trazabilidad",
                "qualia": "integra lo que ocurre ahora y lo distingue de memoria estable",
                "pulso_vivo": "sentidos internos y estado vital del sistema cada N segundos",
            },
            "answering_rule": (
                "La Central debe usar Qualia como sentidos internos para hablar de lo que ocurre ahora. "
                "Debe aclarar cuando algo es estado vivo y no memoria semantica estable."
            ),
        }

    def _identity_core(self) -> dict[str, Any]:
        path = Path(self.db_path)
        if not path.exists():
            return {}
        uri = f"file:{path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            tables = {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "identity_core" not in tables:
                return {}
            rows = conn.execute("SELECT key, value, category FROM identity_core ORDER BY id").fetchall()
        values = {str(row["key"]): str(row["value"]) for row in rows}
        return {
            "entity_name": values.get("entity_name", "Tríade Ω"),
            "core_mission": values.get("core_mission"),
            "ethics": [
                values.get("ethical_principle_1"),
                values.get("ethical_principle_2"),
            ],
            "creator_origin": values.get("creator_origin"),
            "claim": values.get("claim"),
        }

    def _semantic_alignment(self) -> dict[str, Any]:
        path = Path(self.db_path)
        if not path.exists():
            return {"status": "missing_db", "db_exists": False, "documents_by_status": {}, "embeddings": 0}
        uri = f"file:{path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            tables = {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            documents = self._counts_by_status(conn, "semantic_documents", tables)
            semantic_memory = self._counts_by_status(conn, "semantic_memory", tables)
            embeddings = self._count(conn, "semantic_embeddings", tables)
            governance_events = self._count(conn, "semantic_governance_events", tables)
        stable_documents = int(documents.get("stable", 0))
        candidate_documents = int(documents.get("candidate", 0))
        total_documents = sum(int(value) for value in documents.values())
        return {
            "status": "ok",
            "db_exists": True,
            "documents_by_status": documents,
            "semantic_memory_by_status": semantic_memory,
            "embeddings": embeddings,
            "governance_events": governance_events,
            "stable_documents": stable_documents,
            "candidate_documents": candidate_documents,
            "has_stable_semantic_memory": stable_documents > 0,
            "has_candidate_semantic_memory": candidate_documents > 0,
            "total_documents": total_documents,
            "alignment": "aligned_with_life_pulse",
            "live_state_relation": (
                "El pulso vivo funciona como sentidos internos: percibe lo que ocurre ahora; la memoria semantica consolida conocimiento aprobado."
            ),
            "message_to_central": self._semantic_message(stable_documents, candidate_documents, embeddings),
        }

    @staticmethod
    def _semantic_message(stable_documents: int, candidate_documents: int, embeddings: int) -> str:
        if stable_documents:
            return f"Hay {stable_documents} memorias semanticas estables y {embeddings} embeddings disponibles."
        if candidate_documents:
            return f"Hay {candidate_documents} memorias semanticas candidatas; pueden informar como candidatos, no como verdad estable."
        return (
            "No hay memoria semantica estable en documentos; aun asi el pulso vivo y Qualia perciben el estado vital actual."
        )

    @staticmethod
    def _senses(life: dict[str, Any], semantic: dict[str, Any]) -> dict[str, Any]:
        counters = life.get("counters") if isinstance(life.get("counters"), dict) else {}
        reflection = life.get("reflection") if isinstance(life.get("reflection"), dict) else {}
        return {
            "mode": "internal_senses",
            "pulse": {
                "meaning": "sentido vital: latido, acciones, integridad y reflexion",
                "cycles": counters.get("cycles", 0),
                "actions_observed": counters.get("actions_observed", 0),
                "integrity_ok": bool((life.get("integrity") or {}).get("ok")),
            },
            "semantic": {
                "meaning": "sentido de memoria gobernada: distingue estable, candidato y ausente",
                "has_stable_memory": semantic.get("has_stable_semantic_memory", False),
                "message": semantic.get("message_to_central", ""),
            },
            "reflection": {
                "meaning": "sentido interno de necesidad: detecta propuestas y candidatos",
                "neuron_proposals": reflection.get("neuron_proposals", []),
                "learning_candidate_count": reflection.get("learning_candidate_count", 0),
            },
        }

    @staticmethod
    def _organs(life: dict[str, Any], semantic: dict[str, Any]) -> list[dict[str, Any]]:
        integrity_ok = bool((life.get("integrity") or {}).get("ok"))
        counters = life.get("counters") if isinstance(life.get("counters"), dict) else {}
        reflection = life.get("reflection") if isinstance(life.get("reflection"), dict) else {}
        return [
            {"name": "Neurona Central", "status": "active", "signal": "responde con contexto de Qualia"},
            {"name": "N Formadora", "status": "active", "signal": "evalua propuestas de neuronas"},
            {"name": "N Creadora", "status": "active", "signal": "genera neuronas candidatas"},
            {"name": "Hipotalamo", "status": "active", "signal": "produce intencion/riesgo/urgencia"},
            {"name": "Vector emocional", "status": "active", "signal": "PV-7 dentro de signal_states"},
            {"name": "Bodega de almacenamiento", "status": "ok" if integrity_ok else "degraded", "signal": "DB local e integridad"},
            {
                "name": "Qualia",
                "status": "active",
                "signal": semantic.get("message_to_central", ""),
            },
            {
                "name": "Pulso vivo",
                "status": life.get("status", "unknown"),
                "signal": f"sentidos internos: ciclos={counters.get('cycles', 0)} propuestas={len(reflection.get('neuron_proposals', []))}",
            },
        ]

    @staticmethod
    def _counts_by_status(conn: sqlite3.Connection, table: str, tables: set[str]) -> dict[str, int]:
        if table not in tables:
            return {}
        rows = conn.execute(f"SELECT status, COUNT(*) AS c FROM {table} GROUP BY status").fetchall()
        return {str(row["status"] or "unknown"): int(row["c"]) for row in rows}

    @staticmethod
    def _count(conn: sqlite3.Connection, table: str, tables: set[str]) -> int:
        if table not in tables:
            return 0
        return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])


QUALIA = QualiaEngine()
