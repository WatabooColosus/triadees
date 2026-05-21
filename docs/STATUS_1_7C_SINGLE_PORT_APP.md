# Tríade Omega - Single Port App 1.7C

## Fase

TRIADE_SINGLE_PORT_APP_1.7C

## Decision

El puerto 8010 queda como centro unico para la experiencia local de Triade.

La app unica contiene:

- UI web
- /api/health
- /api/router/doctor
- /api/run
- /triade/run
- HardwareProfiler
- ModelRouter
- TriadeRunner

## Archivos

- apps/single_port_app.py
- systemd/triade-chat-ui.service
- tests/test_single_port_app.py

## Resultado

El navegador solo necesita abrir:

http://127.0.0.1:8010/ui

El chat local ya no depende obligatoriamente de triade-api en 8000 ni de triade-model-router en 8020.

triade-api puede seguir existiendo para n8n o integraciones externas.
triade-model-router queda opcional o deprecable.

## Validacion local

1. git pull
2. activar venv
3. correr pytest
4. copiar systemd/triade-chat-ui.service a /etc/systemd/system/
5. daemon-reload
6. restart triade-chat-ui
7. abrir http://127.0.0.1:8010/ui

## Endpoints clave

- GET http://127.0.0.1:8010/api/health
- POST http://127.0.0.1:8010/api/router/doctor
- POST http://127.0.0.1:8010/api/run

## Servicios recomendados

Minimo para chat local:

- triade-chat-ui.service
- ollama opcional si se usan modelos locales

Opcional para automatizacion:

- n8n.service
- triade-api.service

Opcional/deprecated:

- triade-model-router.service

## Siguiente fase sugerida

TRIADE_SYSTEM_CAPABILITY_PROFILE_1.7D

Objetivo: ampliar hardware profile para Windows/Linux con CPU name, GPU, VRAM, disco, sistema operativo y compatibilidad por modelo.
