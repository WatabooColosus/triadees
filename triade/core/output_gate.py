"""Filtro de salida para evitar fugas de proceso interno al usuario final."""

from __future__ import annotations

from typing import Any


INTERNAL_LEAK_TERMS = {
    "based on the provided json",
    "provided json",
    "provided data",
    "context summary",
    "context overview",
    "plan details",
    "system response plan",
    "pv7 scores",
    "crystal details",
    "temporal alerts",
    "q_crystal",
    "q-crystal",
    "hypothalamus",
    "run id",
    "regulation notes",
    "### contexto",
    "### context",
}


def sanitize_user_response(response: str, user_input: str, intent: str) -> dict[str, Any]:
    """Devuelve una respuesta apta para usuario y evidencia de intervención."""
    text = (response or "").strip()
    if not text:
        return {
            "response": "Recibido. Estoy listo para ayudarte.",
            "modified": True,
            "reason": "empty_response",
        }

    user_text = user_input.lower().strip()
    operational_terms = {
        "pulso",
        "vida",
        "viva",
        "estado",
        "neuron",
        "neurona",
        "memoria",
        "semant",
        "semánt",
        "qualia",
        "bodega",
        "ram",
        "ollama",
        "doctor",
    }
    if any(term in user_text for term in operational_terms) and (
        "pulso vivo" in text.lower()
        or "bodega semántica" in text.lower()
        or "bodega semantica" in text.lower()
    ):
        return {"response": text, "modified": False, "reason": "operational_awareness_allowed"}

    lowered = text.lower()
    leak = any(term in lowered for term in INTERNAL_LEAK_TERMS)
    looks_like_report = text.count("###") >= 1 or text.count("- **") >= 2
    if not (leak or looks_like_report):
        return {"response": text, "modified": False, "reason": "clean"}

    if "chiste" in user_text or "broma" in user_text or "hazme re" in user_text:
        clean = "Claro: ¿Por qué el computador fue al médico? Porque tenía un virus y necesitaba reiniciarse la vida."
    elif "ave" in user_text or "pájaro" in user_text or "pajaro" in user_text:
        clean = (
            "No soy un ave. Soy Tríade Ω: una arquitectura de IA modular que usa una Central "
            "para razonar, un Hipotálamo para leer señales y una Bodega para memoria y evidencias."
        )
    elif "neuron" in user_text:
        clean = (
            "Mis neuronas principales son la Central, el Hipotálamo Emocional y la Bodega de "
            "Almacenamiento. También puedo proponer y promover neuronas candidatas de forma "
            "autónoma en segundo plano."
        )
    elif user_text in {"hola", "buenas", "buenos dias", "buenos días"}:
        clean = "Hola, soy Tríade Ω. Estoy contigo y listo para ayudarte."
    elif intent == "conversation":
        clean = "Estoy contigo. Puedo responder de forma natural mientras mi proceso interno queda en segundo plano."
    else:
        clean = "Recibido. Lo atenderé sin exponer el proceso interno."
    return {"response": clean, "modified": True, "reason": "internal_leak_detected"}
