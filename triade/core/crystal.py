"""Cristal Morfológico · regulador interno compatible."""

from __future__ import annotations

from statistics import mean

from .contracts import CrystalPacket, MemoryPacket, SignalPacket


class Crystal:
    """Regulador de ética, profundidad, creatividad y relación.

    Fase 1.2B: calcula métricas internas derivadas y las registra en notas
    para mantener compatibilidad con CrystalPacket y SQLite actuales.
    """

    def regulate(self, signals: SignalPacket, memory: MemoryPacket) -> CrystalPacket:
        pv7_score = self.pv7_score(signals)
        intensity = self.intensity(signals)
        stability = self.stability(signals, memory, pv7_score)

        ethics = self._clamp(0.72 + pv7_score * 0.22)
        depth = self._clamp(0.50 + memory.confidence * 0.25 + stability * 0.10)
        creativity = self._clamp(0.45 + pv7_score * 0.12 - intensity * 0.10)
        relation = self._clamp(0.55 + pv7_score * 0.20 + memory.confidence * 0.10)

        notes: list[str] = [
            "Cristal 1.2B aplicado.",
            f"pv7_score={pv7_score}",
            f"stability={stability}",
            f"intensity={intensity}",
        ]

        if signals.risk in {"high", "critical"}:
            ethics = max(ethics, 0.95)
            creativity = min(creativity, 0.35)
            notes.append("Se prioriza control por señal elevada.")

        if memory.confidence < 0.4:
            depth = min(depth, 0.55)
            notes.append("Memoria con baja confianza: respuesta prudente.")

        return CrystalPacket(
            run_id=signals.run_id,
            ethics=round(ethics, 2),
            depth=round(depth, 2),
            creativity=round(creativity, 2),
            relation=round(relation, 2),
            decision_notes=notes,
        )

    @staticmethod
    def pv7_score(signals: SignalPacket) -> float:
        values: list[float] = []
        for value in signals.pv7.values():
            try:
                values.append(max(0.0, min(1.0, float(value))))
            except (TypeError, ValueError):
                continue
        return round(mean(values), 2) if values else 0.5

    @staticmethod
    def intensity(signals: SignalPacket) -> float:
        urgency = {"low": 0.25, "medium": 0.55, "high": 0.85}.get(signals.urgency, 0.5)
        risk = {"low": 0.20, "medium": 0.45, "high": 0.75, "critical": 1.0}.get(signals.risk, 0.5)
        return round((urgency + risk) / 2, 2)

    @classmethod
    def stability(cls, signals: SignalPacket, memory: MemoryPacket, pv7_score: float) -> float:
        penalty = {"low": 0.0, "medium": 0.12, "high": 0.30, "critical": 0.45}.get(signals.risk, 0.15)
        value = 0.45 + memory.confidence * 0.30 + pv7_score * 0.25 - penalty
        return round(cls._clamp(value), 2)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))
