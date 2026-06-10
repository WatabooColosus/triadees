"""Hipotálamo Emocional · MVP with optional model signals.

Desde Fase F incluye estado emocional persistente: mood (VAD),
fatiga y línea base de PV-7 cargada desde hypothalamus_state.
"""

from __future__ import annotations

import json
from typing import Any

from triade.memory.hypothalamus_store import HypothalamusStateStore, EmotionalState, mood_from_signals
from triade.models.ollama_client import OllamaClient

from .contracts import InputPacket, RiskLevel, SignalPacket, Urgency


MOOD_PV7_MODULATION: dict[str, dict[str, float]] = {
    "fatigued": {"diligencia": 0.85, "paciencia": 1.15},
    "engaged": {"diligencia": 1.1, "generosidad": 1.1},
    "anxious": {"diligencia": 1.15, "paciencia": 0.85, "templanza": 0.8},
    "calm": {"paciencia": 1.1, "templanza": 1.1},
    "withdrawn": {"generosidad": 0.85, "caridad": 0.85, "diligencia": 0.85},
    "positive": {"generosidad": 1.1, "caridad": 1.1, "respeto": 1.05},
    "cautious": {"paciencia": 1.05, "templanza": 1.05, "diligencia": 1.1},
}


class Hypothalamus:
    """Analizador de intención, tono, urgencia, riesgo y PV-7.

    Usa modelo local si está disponible y conserva fallback por reglas.
    Desde Fase F mantiene estado emocional persistente.
    """

    def __init__(
        self,
        model_client: OllamaClient | None = None,
        model_name: str = "qwen2.5:3b-instruct",
        state_store: HypothalamusStateStore | None = None,
    ) -> None:
        self.model_client = model_client
        self.model_name = model_name
        self.state_store = state_store
        self._cached_mood: EmotionalState | None = None
        self.last_model_result: dict[str, Any] = {
            "provider": "rules",
            "name": "rules-fallback",
            "ok": False,
            "error": None,
        }

    @property
    def mood(self) -> EmotionalState | None:
        if self._cached_mood is None and self.state_store is not None:
            self._cached_mood = self.state_store.load_latest()
        return self._cached_mood

    def load_mood(self) -> EmotionalState | None:
        loaded = None
        if self.state_store is not None:
            loaded = self.state_store.load_latest()
        self._cached_mood = loaded
        return loaded

    def analyze(self, packet: InputPacket) -> SignalPacket:
        current_mood = self.load_mood()
        fallback = self._analyze_rules(packet, mood=current_mood)

        if self.model_client is None:
            self.last_model_result = {
                "provider": "rules",
                "name": "rules-fallback",
                "ok": False,
                "error": None,
            }
            return self._save_and_return(packet.run_id, fallback, current_mood)

        system = (
            "Eres el Hipotálamo Emocional de Tríade. "
            "Devuelve SOLO JSON válido con estas claves: intent, tone, urgency, risk, pv7, notes. "
            "intent debe ser conversation, build_or_update, analyze o memory. "
            "urgency debe ser low, medium o high. risk debe ser low, medium, high o critical. "
            "pv7 debe contener humildad, generosidad, respeto, paciencia, templanza, caridad y diligencia con números entre 0 y 1."
        )
        prompt = (
            "Analiza esta entrada del usuario y genera señales afectivo-cognitivas para Tríade.\n\n"
            f"Entrada: {packet.user_input}"
        )
        result = self.model_client.generate(self.model_name, prompt=prompt, system=system)

        if not result.ok or not result.text:
            self.last_model_result = {
                "provider": "ollama",
                "name": self.model_name,
                "ok": False,
                "error": result.error,
            }
            fallback.notes.append("Hipotálamo usó fallback por reglas porque Ollama no generó señales.")
            return self._save_and_return(packet.run_id, fallback, current_mood)

        parsed = self._parse_model_json(result.text)
        if parsed is None:
            self.last_model_result = {
                "provider": "ollama",
                "name": self.model_name,
                "ok": False,
                "error": "Respuesta del modelo no fue JSON válido para señales.",
            }
            fallback.notes.append("Hipotálamo usó fallback por reglas porque el JSON del modelo no fue válido.")
            return self._save_and_return(packet.run_id, fallback, current_mood)

        self.last_model_result = {
            "provider": "ollama",
            "name": self.model_name,
            "ok": True,
            "error": None,
        }

        signals = SignalPacket(
            run_id=packet.run_id,
            intent=self._safe_intent(parsed.get("intent"), fallback.intent),
            tone=str(parsed.get("tone") or fallback.tone),
            urgency=self._safe_urgency(parsed.get("urgency"), fallback.urgency),
            risk=self._safe_risk(parsed.get("risk"), fallback.risk),
            pv7=self._safe_pv7(parsed.get("pv7"), fallback.pv7),
            notes=self._safe_notes(parsed.get("notes")) + ["Señales generadas por Hipotálamo con modelo local Ollama."],
        )
        return self._save_and_return(packet.run_id, signals, current_mood)

    def _save_and_return(self, run_id: str, signals: SignalPacket, previous_mood: EmotionalState | None) -> SignalPacket:
        if self.state_store is not None:
            self.state_store.save(run_id, signals, previous=previous_mood)
            self._cached_mood = self.state_store.load_latest()
        return signals

    def _analyze_rules(self, packet: InputPacket, mood: EmotionalState | None = None) -> SignalPacket:
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

        tone = self._mood_modulate_tone(mood)

        pv7 = {
            "humildad": 0.7,
            "generosidad": 0.7,
            "respeto": 0.8,
            "paciencia": 0.7,
            "templanza": 0.7,
            "caridad": 0.7,
            "diligencia": 0.8,
        }
        pv7 = self._mood_modulate_pv7(pv7, mood)

        notes = [
            "Señales generadas por reglas MVP.",
            "PV-7 inclinado hacia virtudes operativas.",
        ]
        if mood:
            notes.append(f"Mood activo: {mood.primary_emotion} (fatiga={mood.fatigue:.2f})")

        return SignalPacket(
            run_id=packet.run_id,
            intent=intent,
            tone=tone,
            urgency=urgency,  # type: ignore[arg-type]
            risk=risk,  # type: ignore[arg-type]
            pv7=pv7,
            notes=notes,
        )

    def _mood_modulate_tone(self, mood: EmotionalState | None) -> str:
        if mood is None:
            return "constructive"
        if mood.fatigue > 0.6:
            return "cautious"
        if mood.primary_emotion in ("anxious", "withdrawn"):
            return "cautious"
        if mood.primary_emotion == "positive" and mood.valence > 0.4:
            return "encouraging"
        if mood.primary_emotion in ("engaged", "excited"):
            return "constructive"
        return "constructive"

    def _mood_modulate_pv7(self, base: dict[str, float], mood: EmotionalState | None) -> dict[str, float]:
        if mood is None:
            return base
        mod = MOOD_PV7_MODULATION.get(mood.primary_emotion, {})
        result = dict(base)
        for key, factor in mod.items():
            if key in result:
                clamped = max(0.0, min(1.0, result[key] * factor))
                result[key] = clamped
        return result

    @staticmethod
    def _parse_model_json(text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
        if "```" in cleaned:
            cleaned = cleaned.replace("```json", "```")
            parts = cleaned.split("```")
            cleaned = max(parts, key=len).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _safe_intent(value: Any, fallback: str) -> str:
        allowed = {"conversation", "build_or_update", "analyze", "memory"}
        return str(value) if str(value) in allowed else fallback

    @staticmethod
    def _safe_urgency(value: Any, fallback: Urgency) -> Urgency:
        allowed = {"low", "medium", "high"}
        return str(value) if str(value) in allowed else fallback  # type: ignore[return-value]

    @staticmethod
    def _safe_risk(value: Any, fallback: RiskLevel) -> RiskLevel:
        allowed = {"low", "medium", "high", "critical"}
        return str(value) if str(value) in allowed else fallback  # type: ignore[return-value]

    @staticmethod
    def _safe_pv7(value: Any, fallback: dict[str, float]) -> dict[str, float]:
        if not isinstance(value, dict):
            return fallback
        keys = ["humildad", "generosidad", "respeto", "paciencia", "templanza", "caridad", "diligencia"]
        safe: dict[str, float] = {}
        for key in keys:
            try:
                raw = float(value.get(key, fallback.get(key, 0.7)))
            except (TypeError, ValueError):
                raw = fallback.get(key, 0.7)
            safe[key] = max(0.0, min(1.0, raw))
        return safe

    @staticmethod
    def _safe_notes(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value[:5]]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []
