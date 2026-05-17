"""Cristal Morfológico · MVP."""

from __future__ import annotations

from .contracts import CrystalPacket, MemoryPacket, SignalPacket


class Crystal:
    """Regulador simple de ética, profundidad, creatividad y relación."""

    def regulate(self, signals: SignalPacket, memory: MemoryPacket) -> CrystalPacket:
        ethics = 0.85
        depth = 0.65
        creativity = 0.55
        relation = 0.75

        notes: list[str] = ["Cristal aplicado con ponderaciones MVP."]

        if signals.risk in {"high", "critical"}:
            ethics = 0.95
            creativity = 0.35
            notes.append("Riesgo elevado: se aumenta ética y se reduce creatividad operativa.")

        if memory.confidence < 0.4:
            depth = 0.55
            notes.append("Memoria con baja confianza: se evita exceso de certeza.")

        return CrystalPacket(
            run_id=signals.run_id,
            ethics=ethics,
            depth=depth,
            creativity=creativity,
            relation=relation,
            decision_notes=notes,
        )
