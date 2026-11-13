# Triade Omega - Model Compatibility Matrix 1.7E

## Fase

TRIADE_MODEL_COMPATIBILITY_MATRIX_1.7E

## Objetivo

Clasificar modelos disponibles o conocidos segun la capacidad real del sistema.

Estados posibles:

- recommended
- allowed
- risky
- blocked

## Archivos

- triade/models/compatibility_matrix.py
- apps/single_port_app.py
- tests/test_compatibility_matrix.py
- tests/test_single_port_app.py

## Endpoint nuevo

GET http://127.0.0.1:8010/api/models/compatibility

## Criterios iniciales

La matriz considera:

- modelo instalado o no
- RAM disponible
- RAM estimada por modelo
- tier de hardware
- GPU detectada
- VRAM detectada
- CUDA si existe
- rol recomendado del modelo

## Modelos evaluados

- qwen3:1.7b
- qwen2.5-coder:1.5b-base
- qwen2.5:3b-instruct
- qwen2.5-coder:3b
- qwen3:4b
- llama3:latest
- llama3.1:8b
- nomic-embed-text:latest
- qwen3-embedding:0.6b

## Validacion local

Ejecutar:

- git pull
- source .venv/bin/activate
- pytest
- sudo systemctl restart triade-chat-ui
- curl http://127.0.0.1:8010/api/models/compatibility

## Resultado esperado

La respuesta debe incluir:

- matrix.counts
- matrix.models
- status por modelo
- warnings
- reasons
- summary

## Siguiente fase sugerida

TRIADE_AUTO_MODEL_SELECTION_1.7F

Objetivo: que el Runner use automaticamente la matriz y el router para elegir modelos cuando el usuario no seleccione manualmente.
