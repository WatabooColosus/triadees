"""Hipotálamo Emocional · MVP with optional model signals."""

from __future__ import annotations

import json
from typing import Any

from triade.models.ollama_client import OllamaClient

from .contracts import InputPacket, RiskLevel, SignalPacket, Urgency


class Hypothalamus:
    """Analizador de intención, tono, urgencia, riesgo y PV-7.

    Usa modelo local si está disponible y conserva fallback por reglas.
    """

    def __init__(self, model_client: OllamaClient | None = None, model_name: str = "qwen2.5:3b-instruct") -> None:
        self.model_client = model_client
        self.model_name = model_name
        self.last_model_result: dict[str, Any] = {
            "provider": "rules",
            "name": "rules-fallback",
            "ok": False,
            "error": None,
        }

    def analyze(self, packet: InputPacket) -> SignalPacket:
        fallback = self._analyze_rules(packet)

        if self.model_client is None:
            self.last_model_result = {
                "provider": "rules",
                "name": "rules-fallback",
                "ok": False,
                "error": None,
            }
            return fallback

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
            return fallback

        parsed = self._parse_model_json(result.text)
        if parsed is None:
            self.last_model_result = {
                "provider": "ollama",
                "name": self.model_name,
                "ok": False,
                "error": "Respuesta del modelo no fue JSON válido para señales.",
            }
            fallback.notes.append("Hipotálamo usó fallback por reglas porque el JSON del modelo no fue válido.")
            return fallback

        self.last_model_result = {
            "provider": "ollama",
            "name": self.model_name,
            "ok": True,
            "error": None,
        }

        return SignalPacket(
            run_id=packet.run_id,
            intent=self._safe_intent(parsed.get("intent"), fallback.intent),
            tone=str(parsed.get("tone") or fallback.tone),
            urgency=self._safe_urgency(parsed.get("urgency"), fallback.urgency),
            risk=self._safe_risk(parsed.get("risk"), fallback.risk),
            pv7=self._safe_pv7(parsed.get("pv7"), fallback.pv7),
            notes=self._safe_notes(parsed.get("notes")) + ["Señales generadas por Hipotálamo con modelo local Ollama."],
        )

    def _analyze_rules(self, packet: InputPacket) -> SignalPacket:
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
