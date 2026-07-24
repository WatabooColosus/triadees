"""Cristal Morfológico · regulador interno v2."""

from __future__ import annotations

from statistics import mean
from typing import Any

from .contracts import CrystalPacket, MemoryPacket, SignalPacket


class Crystal:
    """Regulador de ética, profundidad, creatividad, relación y Q_cristal.

    Fase 1.8F: Q_cristal conserva fórmula relacional operativa y compara el
    estado presente únicamente contra una ventana histórica contextualizada.
    """

    def regulate_from_packet(
        self,
        packet: Any,
        history: list[dict[str, Any]] | None = None,
        comparison_basis: dict[str, Any] | None = None,
    ) -> CrystalPacket:
        """Regula directamente desde un QualiaPacket (T-002)."""
        signal = packet.signal
        state = packet.state
        meaning = packet.meaning
        continuity = packet.continuity
        fragmentation = packet.fragmentation

        from .contracts import MemoryPacket as _MP, SignalPacket as _SP

        pv7_raw: dict[str, float] = {}
        if signal:
            pv7_raw = {
                "intensity": float(signal.intensity or 0),
                "valence": float(signal.valence or 0),
                "urgency": float(signal.urgency or 0),
                "curiosity": float(signal.curiosity or 0),
                "risk": float(signal.risk or 0),
                "confidence": float(signal.confidence or 0),
            }
        if state:
            pv7_raw.setdefault("curiosity", float(getattr(state, "curiosity", 0) or 0))
            pv7_raw.setdefault("novelty", float(getattr(state, "novelty", 0) or 0))

        sig = _SP(
            run_id=packet.run_id,
            pv7=pv7_raw,
            urgency="high" if float(signal.urgency or 0) > 0.7 else "medium" if float(signal.urgency or 0) > 0.4 else "low",
            risk="high" if float(signal.risk or 0) > 0.7 else "medium" if float(signal.risk or 0) > 0.4 else "low",
            intent=signal.signal_type if signal else "observe",
            tone=signal.tone_hint if signal and hasattr(signal, "tone_hint") else "",
        )

        mem = _MP(
            run_id=packet.run_id,
            confidence=float(signal.confidence or 0.5) if signal else 0.5,
        )

        result = self.regulate(sig, mem, history=history, comparison_basis=comparison_basis)

        if meaning and hasattr(meaning, "composite"):
            result.ethics_vector["meaning_composite"] = float(meaning.composite)
            if float(meaning.composite or 0) > 0.75:
                result.regulation_notes.append("Experiencia de alto significado detectada.")
        if continuity and hasattr(continuity, "depth") and continuity.depth > 0:
            result.ethics_vector["chain_depth"] = continuity.depth
            result.regulation_notes.append(f"Cadena de continuidad profundidad={continuity.depth}.")
        if fragmentation and hasattr(fragmentation, "drift_detected") and fragmentation.drift_detected:
            result.regulation_notes.append("Fragmentación detectada: coherencia reducida.")

        return result

    def regulate(
        self,
        signals: SignalPacket,
        memory: MemoryPacket,
        history: list[dict[str, Any]] | None = None,
        comparison_basis: dict[str, Any] | None = None,
    ) -> CrystalPacket:
        history = history or []
        comparison_basis = comparison_basis or {
            "context_scope": "source_intent",
            "context_key": "",
            "source": None,
            "intent": signals.intent,
        }
        pv7_score = self.pv7_score(signals)
        intensity = self.intensity(signals)
        stability = self.stability(signals, memory, pv7_score)

        ethics = self._clamp(0.72 + pv7_score * 0.22)
        depth = self._clamp(0.50 + memory.confidence * 0.25 + stability * 0.10)
        creativity = self._clamp(0.45 + pv7_score * 0.12 - intensity * 0.10)
        relation = self._clamp(0.55 + pv7_score * 0.20 + memory.confidence * 0.10)

        regulation_notes: list[str] = [
            "Cristal v2 1.8F aplicado.",
            "Q_cristal calculado con fórmula relacional operativa.",
            f"Historial comparable filtrado por contexto: {comparison_basis.get('context_scope', 'source_intent')}.",
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
        temporal = self.temporal_state(q_crystal=q_crystal, stability=stability, history=history)
        regulation_notes.extend(temporal["alerts"])

        ethics_vector = self.ethics_vector(signals, pv7_score, stability, intensity)
        ethics_vector["q_crystal"] = q_crystal
        ethics_vector["s_rel"] = q_payload["s_rel"]
        ethics_vector["phi_memory"] = q_payload["phi_memory"]
        ethics_vector["q_delta"] = temporal["q_delta"]
        ethics_vector["stability_delta"] = temporal["stability_delta"]

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
            f"temporal_status={temporal['status']}",
            f"q_delta={temporal['q_delta']}",
            f"stability_delta={temporal['stability_delta']}",
            f"history_window={temporal['history_window']}",
            f"context_scope={comparison_basis.get('context_scope', 'source_intent')}",
            f"context_key={comparison_basis.get('context_key', '')}",
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
            previous_q_crystal=temporal["previous_q_crystal"],
            previous_stability=temporal["previous_stability"],
            q_delta=temporal["q_delta"],
            stability_delta=temporal["stability_delta"],
            temporal_status=temporal["status"],
            temporal_alerts=temporal["alerts"],
            history_window=temporal["history_window"],
            context_scope=str(comparison_basis.get("context_scope", "source_intent")),
            context_key=str(comparison_basis.get("context_key", "")),
            comparison_basis=dict(comparison_basis),
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

    @classmethod
    def temporal_state(cls, q_crystal: float, stability: float, history: list[dict[str, Any]]) -> dict[str, Any]:
        if not history:
            return {
                "status": "baseline",
                "previous_q_crystal": None,
                "previous_stability": None,
                "q_delta": 0.0,
                "stability_delta": 0.0,
                "history_window": 0,
                "alerts": ["Línea base temporal iniciada; aún no hay historial comparable."],
            }
        latest = history[0]
        previous_q = float(latest.get("q_crystal") or 0.0)
        previous_stability = float(latest.get("stability") or 0.0)
        q_delta = round(q_crystal - previous_q, 3)
        stability_delta = round(stability - previous_stability, 3)
        historic_q = [float(item.get("q_crystal") or 0.0) for item in history]
        historic_avg = round(mean(historic_q), 3) if historic_q else previous_q
        alerts: list[str] = []
        if q_crystal < 0.30 or stability < 0.35:
            status = "critical"
            alerts.append("Alerta temporal crítica: Q_cristal o estabilidad en umbral bajo.")
        elif q_delta <= -0.15 or stability_delta <= -0.15:
            status = "degrading"
            alerts.append("Alerta temporal: degradación marcada frente al ciclo anterior.")
        elif q_delta >= 0.10 and stability_delta >= 0.05:
            status = "improving"
            alerts.append("Tendencia temporal favorable: Q_cristal y estabilidad mejoran.")
        else:
            status = "stable"
            alerts.append("Continuidad temporal estable dentro de umbrales operativos.")
        if q_crystal < historic_avg - 0.12 and status not in {"critical", "degrading"}:
            status = "degrading"
            alerts.append("Q_cristal actual por debajo del promedio histórico reciente.")
        return {
            "status": status,
            "previous_q_crystal": round(previous_q, 3),
            "previous_stability": round(previous_stability, 3),
            "q_delta": q_delta,
            "stability_delta": stability_delta,
            "history_window": len(history),
            "alerts": alerts,
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
