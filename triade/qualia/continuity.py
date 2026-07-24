"""Continuidad temporal: encadena experiencias Qualia entre runs.

Permite al sistema preguntar "¿qué pasó justo antes?" y mantener coherencia
narrativa entre ejecuciones. No asume persistencia automática: cada run
declara explícitamente su padre si existe.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now

from .contracts import new_qualia_id


@dataclass(slots=True)
class ExperienceAnchor:
    """Ancla una experiencia al historial de ContinuityChain."""

    packet_id: str
    run_id: str
    chain_id: str
    parent_packet_id: str
    created_at: str
    depth: int = 0
    summary_hash: str = ""
    bridged_sessions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "run_id": self.run_id,
            "chain_id": self.chain_id,
            "parent_packet_id": self.parent_packet_id,
            "created_at": self.created_at,
            "depth": self.depth,
            "summary_hash": self.summary_hash,
        }


class ContinuityEngine:
    """Gestiona la cadena de continuidad entre experiencias Qualia.

    Cada run puede referenciar un packet padre de un run anterior.
    La engine calcula la profundidad de la cadena y detecta puentes
    entre sesiones (runs separados).
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path) if db_path else None
        self._anchors: list[ExperienceAnchor] = []

    def anchor(
        self,
        *,
        packet_id: str,
        run_id: str,
        chain_id: str,
        parent_packet_id: str = "",
        summary_hash: str = "",
    ) -> ExperienceAnchor:
        """Registra un ancla de continuidad para un paquete."""
        parent_depth = 0
        bridged = False

        if parent_packet_id:
            parent = self._find_anchor(parent_packet_id)
            if parent:
                parent_depth = parent.depth
                bridged = parent.run_id != run_id

        anchor = ExperienceAnchor(
            packet_id=packet_id,
            run_id=run_id,
            chain_id=chain_id,
            parent_packet_id=parent_packet_id,
            created_at=utc_now(),
            depth=parent_depth + 1,
            summary_hash=summary_hash,
            bridged_sessions=1 if bridged else 0,
        )
        self._anchors.append(anchor)

        if self._db_path:
            self._persist_anchor(anchor)

        return anchor

    def build_chain(
        self,
        *,
        packet_id: str,
        parent_packet_id: str = "",
        parent_run_id: str = "",
        hops: list[str] | None = None,
    ) -> dict[str, Any]:
        """Construye un ContinuityChain dict para insertar en QualiaPacket."""
        parent = self._find_anchor(parent_packet_id) if parent_packet_id else None
        depth = (parent.depth + 1) if parent else 0
        chain_id = parent.chain_id if parent else new_qualia_id("chain")
        hop_list = list(hops or [])
        if parent_packet_id:
            hop_list.append(parent_packet_id)

        bridged = 0
        if parent and parent.run_id != parent_run_id:
            bridged = parent.bridged_sessions + 1

        return {
            "chain_id": chain_id,
            "parent_packet_id": parent_packet_id,
            "parent_run_id": parent_run_id,
            "depth": depth,
            "hops": hop_list[-20:],
            "bridged_sessions": bridged,
        }

    def get_history(
        self,
        *,
        chain_id: str | None = None,
        packet_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Recupera historial de anclas, filtrado por chain o packet."""
        anchors = self._anchors
        if chain_id:
            anchors = [a for a in anchors if a.chain_id == chain_id]
        if packet_id:
            anchors = [a for a in anchors if a.packet_id == packet_id]
        anchors = sorted(anchors, key=lambda a: a.depth, reverse=True)
        return [a.to_dict() for a in anchors[:limit]]

    def chain_length(self, chain_id: str) -> int:
        """Devuelve la longitud de una cadena específica."""
        return sum(1 for a in self._anchors if a.chain_id == chain_id)

    def detect_session_bridges(self, run_id: str) -> list[dict[str, Any]]:
        """Detecta puentes de sesión para un run dado (padres de otros runs)."""
        bridges = []
        for a in self._anchors:
            if a.run_id != run_id and a.parent_packet_id:
                parent = self._find_anchor(a.parent_packet_id)
                if parent and parent.run_id == run_id:
                    bridges.append({
                        "child_packet": a.packet_id,
                        "child_run": a.run_id,
                        "parent_packet": parent.packet_id,
                        "bridged_sessions": a.bridged_sessions,
                    })
        return bridges

    def _find_anchor(self, packet_id: str) -> ExperienceAnchor | None:
        for a in reversed(self._anchors):
            if a.packet_id == packet_id:
                return a
        return None

    def _persist_anchor(self, anchor: ExperienceAnchor) -> None:
        if not self._db_path:
            return
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """
                INSERT OR REPLACE INTO experience_continuity
                    (packet_id, run_id, chain_id, parent_packet_id,
                     created_at, depth, summary_hash, bridged_sessions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    anchor.packet_id,
                    anchor.run_id,
                    anchor.chain_id,
                    anchor.parent_packet_id,
                    anchor.created_at,
                    anchor.depth,
                    anchor.summary_hash,
                    anchor.bridged_sessions,
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
