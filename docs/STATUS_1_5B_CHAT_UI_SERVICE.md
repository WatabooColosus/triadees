# Tríade Ω · Chat UI Service

## Nombre de fase

```text
TRIADE_CHAT_UI_SERVICE_1.5B
```

## Objetivo

Dejar la interfaz local de chat como servicio `systemd`, para que arranque automáticamente junto con la PC.

## Archivo agregado

```text
systemd/triade-chat-ui.service
```

## Servicio

```text
triade-chat-ui.service
```

## Instalación local

Desde el repo:

```bash
cd ~/triadees
git pull
sudo cp systemd/triade-chat-ui.service /etc/systemd/system/triade-chat-ui.service
sudo systemctl daemon-reload
sudo systemctl enable triade-chat-ui
sudo systemctl start triade-chat-ui
sudo systemctl status triade-chat-ui --no-pager
```

## Prueba

```bash
curl -i http://127.0.0.1:8010/ui
```

Abrir en navegador:

```text
http://127.0.0.1:8010/ui
```

## Stack esperado tras reinicio

```text
triade-api.service      active/running
n8n.service             active/running
triade-chat-ui.service  active/running
```

## Validación completa

```bash
sudo systemctl status triade-api --no-pager
sudo systemctl status n8n --no-pager
sudo systemctl status triade-chat-ui --no-pager
curl http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8010/ui
```

## Nota CORS

La API principal debe permitir el origen:

```text
http://127.0.0.1:8010
http://localhost:8010
```

Si la UI muestra `NetworkError when attempting to fetch resource`, revisar `TRIADE_CORS_ORIGINS` en `triade-api.service`.

## Siguiente fase sugerida

```text
TRIADE_MODEL_ROUTER_1.6
```

Objetivo: elegir automáticamente modelos por rol/neurona según tarea, hardware y software disponible.
