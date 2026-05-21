# Tríade Ω · Chat UI + Model Router 1.6D

## Nombre de fase

```text
TRIADE_CHAT_UI_MODEL_ROUTER_1.6D
```

## Objetivo

Crear una interfaz de chat local que consulte el Model Router y permita aplicar modelos recomendados antes de enviar mensajes a Tríade.

## Archivo agregado

```text
apps/chat_ui_router_app.py
tests/test_chat_ui_router_app.py
```

## Ejecución local

```bash
python -m uvicorn apps.chat_ui_router_app:app --host 127.0.0.1 --port 8011
```

Abrir:

```text
http://127.0.0.1:8011/ui
```

## Servicios requeridos

```text
triade-api.service           http://127.0.0.1:8000
triade-model-router.service  http://127.0.0.1:8020
```

## Uso

1. Escribir API key local.
2. Seleccionar intención y urgencia.
3. Pulsar `Consultar Model Router`.
4. Revisar modelos recomendados.
5. Pulsar `Aplicar recomendados`.
6. Enviar mensaje.

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
python -m uvicorn apps.chat_ui_router_app:app --host 127.0.0.1 --port 8011
```

Luego:

```bash
curl -i http://127.0.0.1:8011/ui
```

## Siguiente fase

Crear servicio:

```text
triade-chat-router-ui.service
```

O reemplazar la UI estable de puerto 8010 por esta versión cuando esté validada.
