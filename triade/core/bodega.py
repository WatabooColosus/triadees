"""Bodega de Almacenamiento · MVP.

Implementación mínima sin base de datos activa. Sirve como puente hacia SQLite.
"""

from __future__ import annotations

from .contracts import InputPacket, MemoryPacket, OutputPacket


class Bodega:
    """Memoria funcional inicial.

    En esta versión no consulta SQLite todavía; devuelve identidad semilla
    y prepara el contrato para persistencia futura.
    """

    def recall(self, packet: InputPacket) -> MemoryPacket:
        identity = [
            {
                "key": "entity_name",
                "value": "Tríade Ω",
                "confidence": 1.0,
            },
            {
                "key": "core_mission",
                "value": "Sistema cognitivo modular en construcción verificable",
                "confidence": 1.0,
            },
            {
                "key": "ethical_principle",
                "value": "Toda alma cuenta",
                "confidence": 1.0,
            },
        ]

        return MemoryPacket(
            run_id=packet.run_id,
            identity_matches=identity,
            confidence=0.6,
        )

    def diff_from_output(self, output: OutputPacket) -> dict[str, object]:
        return {
            "run_id": output.run_id,
            "stored": False,
            "reason": "MVP sin persistencia activa; listo para conectar SQLite.",
        }
