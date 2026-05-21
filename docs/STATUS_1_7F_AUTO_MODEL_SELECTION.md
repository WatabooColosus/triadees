# Triade Omega - Auto Model Selection 1.7F

## Fase

TRIADE_AUTO_MODEL_SELECTION_1.7F

## Objetivo

Hacer que Triade elija automaticamente modelos para Hipotalamo y Central cuando el usuario no los defina manualmente.

## Archivos

- triade/core/runner.py
- apps/single_port_app.py
- tests/test_auto_model_selection.py
- tests/test_single_port_app.py

## Comportamiento

Si use_ollama=true, no se pasan modelos manuales y Ollama esta disponible:

1. Runner detecta hardware con HardwareProfiler.
2. Consulta modelos instalados con OllamaClient.health().
3. Usa ModelRouter con hardware.
4. Selecciona modelo para Hipotalamo.
5. Selecciona modelo para Central.
6. Guarda model_selection en memory_diff, integrity y respuesta.

Si Ollama no esta disponible o esta desactivado:

- Usa fallback configurado.
- model_selection.enabled=false.
- reason indica la causa.

Si el usuario define modelos manuales:

- Respeta el valor manual.
- No fuerza seleccion automatica.

## UI

La Single Port App permite:

- dejar Hipotalamo vacio para automatico
- dejar Central vacio para automatico
- activar Auto elegir modelos
- activar Usar Ollama

## Nota sobre descarga 24/7

Esta fase NO descarga modelos automaticamente.

La descarga automatica debe implementarse despues con control humano y reglas de red/disco/seguridad, porque bajar modelos sin limite puede consumir ancho de banda, disco y recursos.

## Validacion local

Ejecutar:

- git pull
- source .venv/bin/activate
- pytest
- sudo systemctl restart triade-chat-ui

Prueba endpoint:

POST http://127.0.0.1:8010/api/run

Payload sugerido:

{
  "text": "Prueba auto model selection",
  "use_ollama": true,
  "hypothalamus_model": "",
  "central_model": "",
  "auto_select_models": true
}

La respuesta debe incluir model_selection.

## Siguiente fase sugerida

TRIADE_MODEL_INSTALL_QUEUE_1.7G

Objetivo: generar cola de instalacion de modelos recomendados no instalados, con autorizacion, limites de red/disco y trazabilidad.
