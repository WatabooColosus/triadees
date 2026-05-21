"""Cristal Morfológico · regulador interno v2."""

from __future__ import annotations

from statistics import mean

from .contracts import CrystalPacket, MemoryPacket, SignalPacket


class Crystal:
    """Regulador de ética, profundidad, creatividad, relación y Q_cristal.

    Fase 1.8A: las métricas profundas dejan de vivir solo en notas y pasan
    a ser campos reales del CrystalPacket.
    """

    def regulate(self, signals: SignalPacket, memory: MemoryPacket) -> CrystalPacket:
        pv7_score = self.pv7_score(signals)
        intensity = self.intensity(signals)
        stability = self.stability(signals, memory, pv7_score)

        ethics = self._clamp(0.72 + pv7_score * 0.22)
        depth = self._clamp(0.50 + memory.confidence * 0.25 + stability * 0.10)
        creativity = self._clamp(0.45 + pv7_score * 0.12 - intensity * 0.10)
        relation = self._clamp(0.55 + pv7_score * 0.20 + memory.confidence * 0.10)

        regulation_notes: list[str] = [
            "Cristal v2 1.8A aplicado.",
            "Métricas profundas registradas como campos reales.",
        ]

        if signals.risk in {"high", "critical"}:
            ethics = max(ethics, 0.95)
            creativity = min(creativity, 0.35)
            regulation_notes.append("Se prioriza control por señal elevada.")

        if memory.confidence < 0.4:
            depth = min(depth, 0.55)
            regulation_notes.append("Memoria con baja confianza: respuesta prudente.")

        q_crystal = self.q_crystal(
            ethics=ethics,
            depth=depth,
            creativity=creativity,
            relation=relation,
            pv7_score=pv7_score,
            stability=stability,
            intensity=intensity,
            memory_confidence=memory.confidence,
        )
        ethics_vector = self.ethics_vector(signals, pv7_score, stability, intensity)

        decision_notes = [
            *regulation_notes,
            f"pv7_score={pv7_score}",
            f"stability={stability}",
            f"intensity={intensity}",
            f"q_crystal={q_crystal}",
        ]

        return CrystalPacket(
            run_id=signals.run_id,
            ethics=round(ethics, 2),
            depth=round(depth, 2),
            creativity=round(creativity, 2),
            relation=round(relation, 2),
            pv7_score=pv7_score,
            stability=stability,
            intensity=intensity,
            q_crystal=q_crystal,
            ethics_vector=ethics_vector,
            regulation_notes=regulation_notes,
            decision_notes=decision_notes,
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

    @classmethod
    def q_crystal(
        cls,
        ethics: float,
        depth: float,
        creativity: float,
        relation: float,
        pv7_score: float,
        stability: float,
        intensity: float,
        memory_confidence: float,
    ) -> float:
        """Aproximación operativa inicial de Q_cristal.

        No pretende cerrar la fórmula filosófica completa; crea una métrica
        verificable y estable para regular el ciclo.
        """
        coherence = (ethics * 0.30) + (depth * 0.18) + (creativity * 0.12) + (relation * 0.16)
        regulators = (pv7_score * 0.10) + (stability * 0.10) + (memory_confidence * 0.04)
        penalty = intensity * 0.10
        return round(cls._clamp(coherence + regulators - penalty), 3)

    @staticmethod
    def ethics_vector(signals: SignalPacket, pv7_score: float, stability: float, intensity: float) -> dict[str, float]:
        risk_pressure = {"low": 0.1, "medium": 0.35, "high": 0.7, "critical": 1.0}.get(signals.risk, 0.35)
        return {
            "virtue_alignment": pv7_score,
            "risk_pressure": risk_pressure,
            "stability": stability,
            "intensity": intensity,
            "care_bias": round(max(pv7_score, 1.0 - risk_pressure), 2),
        }

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))
