"""Cristal Morfológico · regulador interno v2."""

from __future__ import annotations

from statistics import mean

from .contracts import CrystalPacket, MemoryPacket, SignalPacket


class Crystal:
    """Regulador de ética, profundidad, creatividad, relación y Q_cristal.

    Fase 1.8C: Q_cristal usa una aproximación operativa más cercana a la
    fórmula teórica oficial:

    S_rel(t) = α·S^H(t) + β·S^T(t)
    Q_cristal(t) = ((S_rel(t) + C'(t)) / I'(t)) ^ R'(t) · Φ(M,t)

    La fórmula se mantiene normalizada en [0, 1] para uso práctico dentro
    del ciclo cognitivo.
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
            "Cristal v2 1.8C aplicado.",
            "Q_cristal calculado con fórmula relacional operativa.",
        ]

        if signals.risk in {"high", "critical"}:
            ethics = max(ethics, 0.95)
            creativity = min(creativity, 0.35)
            regulation_notes.append("Se prioriza control por señal elevada.")

        if memory.confidence < 0.4:
            depth = min(depth, 0.55)
            regulation_notes.append("Memoria con baja confianza: respuesta prudente.")

        q_payload = self.q_crystal_payload(
            ethics=ethics,
            depth=depth,
            creativity=creativity,
            relation=relation,
            pv7_score=pv7_score,
            stability=stability,
            intensity=intensity,
            memory_confidence=memory.confidence,
            risk=signals.risk,
        )
        q_crystal = q_payload["q_crystal"]
        ethics_vector = self.ethics_vector(signals, pv7_score, stability, intensity)
        ethics_vector["q_crystal"] = q_crystal
        ethics_vector["s_rel"] = q_payload["s_rel"]
        ethics_vector["phi_memory"] = q_payload["phi_memory"]

        decision_notes = [
            *regulation_notes,
            f"pv7_score={pv7_score}",
            f"stability={stability}",
            f"intensity={intensity}",
            f"q_crystal={q_crystal}",
            f"s_rel={q_payload['s_rel']}",
            f"i_prime={q_payload['i_prime']}",
            f"r_prime={q_payload['r_prime']}",
            f"phi_memory={q_payload['phi_memory']}",
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
        """Compatibilidad hacia atrás: retorna solo el valor Q."""
        return cls.q_crystal_payload(
            ethics=ethics,
            depth=depth,
            creativity=creativity,
            relation=relation,
            pv7_score=pv7_score,
            stability=stability,
            intensity=intensity,
            memory_confidence=memory_confidence,
            risk="low",
        )["q_crystal"]

    @classmethod
    def q_crystal_payload(
        cls,
        ethics: float,
        depth: float,
        creativity: float,
        relation: float,
        pv7_score: float,
        stability: float,
        intensity: float,
        memory_confidence: float,
        risk: str,
    ) -> dict[str, float]:
        """Fórmula relacional operativa de Q_cristal.

        S^H aproxima señal afectivo-ética del Hipotálamo.
        S^T aproxima señal técnica/central desde coherencia y profundidad.
        I' penaliza intensidad y riesgo. R' eleva o estabiliza según estabilidad.
        Φ(M,t) pondera continuidad de memoria.
        """
        risk_pressure = {"low": 0.10, "medium": 0.35, "high": 0.70, "critical": 1.0}.get(risk, 0.35)
        s_h = cls._clamp((pv7_score * 0.48) + ((1.0 - intensity) * 0.30) + ((1.0 - risk_pressure) * 0.22))
        s_t = cls._clamp((ethics * 0.28) + (depth * 0.24) + (relation * 0.20) + (stability * 0.18) + (creativity * 0.10))
        alpha = cls._clamp(0.55 + pv7_score * 0.10 - risk_pressure * 0.10)
        beta = cls._clamp(1.0 - alpha)
        s_rel = cls._clamp((alpha * s_h) + (beta * s_t))
        c_prime = cls._clamp(creativity * 0.22 + depth * 0.08)
        i_prime = 1.0 + (intensity * 0.55) + (risk_pressure * 0.35)
        r_prime = 1.0 + (stability * 0.45) + (ethics * 0.10)
        phi_memory = cls._clamp(0.62 + memory_confidence * 0.38)
        base = cls._clamp((s_rel + c_prime) / i_prime)
        q_value = cls._clamp((base ** r_prime) * phi_memory)
        return {
            "q_crystal": round(q_value, 3),
            "s_h": round(s_h, 3),
            "s_t": round(s_t, 3),
            "s_rel": round(s_rel, 3),
            "alpha": round(alpha, 3),
            "beta": round(beta, 3),
            "c_prime": round(c_prime, 3),
            "i_prime": round(i_prime, 3),
            "r_prime": round(r_prime, 3),
            "phi_memory": round(phi_memory, 3),
        }

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
