# Triade Omega - Model Install Queue 1.7G

## Fase

TRIADE_MODEL_INSTALL_QUEUE_1.7G

## Objetivo

Crear una cola segura de instalacion de modelos recomendados no instalados.

Esta fase no descarga modelos automaticamente. Solo genera candidatos, comandos sugeridos, prioridad, advertencias y politica de autorizacion.

## Archivos

- triade/models/model_install_queue.py
- apps/single_port_app.py
- tests/test_model_install_queue.py
- tests/test_single_port_app.py

## Endpoint

GET http://127.0.0.1:8010/api/models/install-queue

Parametro opcional:

include_allowed=true

## Politica

- auto_install: false
- requires_authorization: true
- no ejecuta ollama pull automaticamente
- calcula disco minimo sugerido
- advierte si el disco libre es insuficiente
- omite modelos instalados
- omite modelos blocked/risky por defecto

## Resultado esperado

La respuesta incluye:

- policy
- hardware
- available_models
- candidates
- command por modelo
- priority
- warnings
- summary

## UI

La Single Port App agrega boton:

Cola modelos

## Validacion local

Ejecutar:

- git pull
- source .venv/bin/activate
- pytest
- sudo systemctl restart triade-chat-ui
- curl http://127.0.0.1:8010/api/models/install-queue

## Siguiente fase sugerida

TRIADE_MODEL_INSTALL_EXECUTOR_1.7H

Objetivo: ejecutar ollama pull solo con autorizacion explicita, registro de evidencia, validacion de disco y timeout seguro.
