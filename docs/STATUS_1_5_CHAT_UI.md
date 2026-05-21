# Tríade Ω · Chat UI local

## Nombre de fase

```text
TRIADE_CHAT_UI_1.5A
```

## Objetivo

Crear una interfaz web local simple para conversar con Tríade desde navegador, sin depender de `curl` ni de la vista de ejecuciones de n8n.

## Archivo agregado

```text
apps/chat_ui_app.py
```

## Ruta local

La interfaz corre como app independiente.

```bash
python -m uvicorn apps.chat_ui_app:app --host 127.0.0.1 --port 8010
```

Abrir:

```text
http://127.0.0.1:8010/ui
```

## Requisitos

La API principal debe estar activa:

```bash
sudo systemctl status triade-api
curl http://127.0.0.1:8000/health
```

## Uso

En la interfaz:

1. API base: `http://127.0.0.1:8000`
2. API key local: la misma clave de `triade-api.service`
3. Elegir si usar Ollama.
4. Enviar mensaje.

La UI muestra:

```text
response
run_id
run_path
modelo Hipotálamo
modelo Central
```

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
python -m uvicorn apps.chat_ui_app:app --host 127.0.0.1 --port 8010
```

Luego abrir:

```text
http://127.0.0.1:8010/ui
```

## Siguiente mejora

Crear `triade-chat-ui.service` para que la interfaz también arranque con la PC.
