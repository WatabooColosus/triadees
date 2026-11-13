# Tríade Ω · Chat UI Unificada 1.6D

## Nombre de fase

```text
TRIADE_UNIFIED_CHAT_UI_MODEL_ROUTER_1.6D
```

## Decisión

Se elimina la idea de mantener múltiples interfaces. La Chat UI estable del puerto `8010` se convierte en centro único.

## Archivo actualizado

```text
apps/chat_ui_app.py
```

## Principio de diseño

El navegador solo habla con:

```text
http://127.0.0.1:8010
```

La app de Chat UI hace proxy interno hacia:

```text
Tríade API    → http://127.0.0.1:8000
Model Router  → http://127.0.0.1:8020
```

Esto evita errores CORS como:

```text
NetworkError when attempting to fetch resource
```

## Endpoints internos de la UI

```text
GET  /api/health
POST /api/router/doctor
POST /api/run
```

## Servicios requeridos

```text
triade-api.service
triade-model-router.service
triade-chat-ui.service
```

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
sudo systemctl restart triade-chat-ui
curl -i http://127.0.0.1:8010/ui
```

Abrir:

```text
http://127.0.0.1:8010/ui
```

## Flujo unificado

```text
Navegador
→ Chat UI 8010
→ proxy /api/health → Tríade API 8000
→ proxy /api/router/doctor → Model Router 8020
→ proxy /api/run → Tríade API 8000 /triade/run
```

## Estado esperado

- Un solo chat principal.
- Sin CORS entre navegador y servicios internos.
- Model Router visible y aplicable desde la misma UI.
- Servicio systemd existente `triade-chat-ui.service` sigue funcionando sin cambiar puerto.
