"""Manifiesto dinámico de UI para la consola 8010 de Tríade Ω."""

from __future__ import annotations

from typing import Any


def build_ui_manifest() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "ui_manifest",
        "version": "0.1",
        "policy": "no_fake_buttons_live_data_first",
        "sections": [
            {
                "id": "status",
                "title": "Estado vivo",
                "kind": "live_data",
                "items": [
                    {"id": "pulse", "label": "Pulso vivo", "method": "GET", "endpoint": "/api/system/pulse?sync_relay=true", "refresh_seconds": 15},
                    {"id": "capacity", "label": "Capacidad y nodos", "method": "GET", "endpoint": "/api/system/model-capacity?sync_relay=true", "refresh_seconds": 15},
                    {"id": "neurons", "label": "Neuronas", "method": "GET", "endpoint": "/api/system/neurons?limit=50", "refresh_seconds": 20},
                ],
            },
            {
                "id": "session",
                "title": "Configuración de sesión",
                "kind": "config_input",
                "fields": [
                    {"id": "api_key", "label": "API key", "type": "password"},
                    {"id": "intent", "label": "Intención", "type": "select", "options": ["conversation", "analyze", "memory", "build_or_update"]},
                    {"id": "urgency", "label": "Urgencia", "type": "select", "options": ["low", "medium", "high"]},
                    {"id": "use_ollama", "label": "Usar Ollama", "type": "checkbox"},
                    {"id": "auto_select_models", "label": "Auto elegir modelos", "type": "checkbox"},
                    {"id": "hypothalamus_model", "label": "Modelo Hipotálamo", "type": "text"},
                    {"id": "central_model", "label": "Modelo Central", "type": "text"},
                ],
            },
            {
                "id": "diagnostics",
                "title": "Diagnósticos",
                "kind": "diagnostic",
                "items": [
                    {"id": "health", "label": "Health completo", "method": "GET", "endpoint": "/api/health"},
                    {"id": "compatibility", "label": "Compatibilidad", "method": "GET", "endpoint": "/api/models/compatibility"},
                    {"id": "queue", "label": "Cola modelos", "method": "GET", "endpoint": "/api/models/install-queue?include_allowed=false"},
                    {"id": "semantic", "label": "Memoria semántica", "method": "GET", "endpoint": "/api/semantic/governance/doctor"},
                    {"id": "router", "label": "Recomendar modelos", "method": "POST", "endpoint": "/api/router/doctor"},
                    {"id": "android_doctor", "label": "Doctor Android", "method": "POST", "endpoint": "/api/distributed-runtime/android-model-doctor"},
                    {"id": "runtime_probe", "label": "Probar runtime distribuido", "method": "POST", "endpoint": "/api/distributed-runtime/probe"},
                    {"id": "preprocess", "label": "Preprocesar en nodos", "method": "POST", "endpoint": "/api/distributed-runtime/preprocess"},
                ],
            },
            {
                "id": "actions",
                "title": "Acciones humanas",
                "kind": "real_action",
                "items": [
                    {"id": "send", "label": "Enviar mensaje", "method": "POST", "endpoint": "/api/run", "enabled": True},
                    {"id": "neuron_decision", "label": "Decidir neurona", "method": "POST", "endpoint": "/api/system/neurons/decision", "enabled": False, "disabled_reason": "Pendiente endpoint UI; usar CLI por ahora."},
                    {"id": "promote_stable", "label": "Promover stable", "method": "POST", "endpoint": "/api/system/neurons/promote-stable", "enabled": False, "disabled_reason": "Pendiente endpoint UI; usar CLI por ahora."},
                ],
            },
            {
                "id": "downloads",
                "title": "Descargas",
                "kind": "download",
                "items": [
                    {"id": "android_node_apk", "label": "Descargar Android Node", "href": "/downloads/triade-android-node.apk"}
                ],
            },
        ],
        "truth": "La UI debe renderizar datos vivos desde endpoints; lo estático queda declarado para poder volverlo configurable después.",
    }
