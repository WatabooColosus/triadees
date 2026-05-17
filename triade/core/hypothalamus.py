"""Hipotálamo Emocional · MVP.

Convierte una entrada en señales afectivo-cognitivas simples.
"""

from __future__ import annotations

from .contracts import InputPacket, SignalPacket


class Hypothalamus:
    """Analizador inicial de intención, tono, urgencia, riesgo y PV-7."""

    def analyze(self, packet: InputPacket) -> SignalPacket:
        text = packet.user_input.lower().strip()

        urgency = "high" if any(word in text for word in ["urgente", "ya", "rápido", "error", "falló"]) else "medium"
        risk = "medium" if any(word in text for word in ["borrar", "eliminar", "credencial", "token", "contraseña"]) else "low"

        if any(word in text for word in ["crea", "crear", "construye", "avanza", "actualiza"]):
            intent = "build_or_update"
        elif any(word in text for word in ["analiza", "revisa", "audita"]):
            intent = "analyze"
        elif any(word in text for word in ["recuerda", "guarda", "memoria"]):
            intent = "memory"
        else:
            intent = "conversation"

        tone = "constructive"
        pv7 = {
            "humildad": 0.7,
            "generosidad": 0.7,
            "respeto": 0.8,
            "paciencia": 0.7,
            "templanza": 0.7,
            "caridad": 0.7,
            "diligencia": 0.8,
        }

        notes = [
            "Señales generadas por reglas MVP.",
            "PV-7 inclinado hacia virtudes operativas.",
        ]

        return SignalPacket(
            run_id=packet.run_id,
            intent=intent,
            tone=tone,
            urgency=urgency,  # type: ignore[arg-type]
            risk=risk,  # type: ignore[arg-type]
            pv7=pv7,
            notes=notes,
        )
