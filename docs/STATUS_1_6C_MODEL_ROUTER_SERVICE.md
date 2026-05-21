# Tríade Ω · Model Router Service 1.6C

## Nombre de fase

```text
TRIADE_MODEL_ROUTER_SERVICE_1.6C
```

## Objetivo

Dejar el Model Router como servicio persistente de `systemd`, para que esté disponible al prender la PC.

## Archivo agregado

```text
systemd/triade-model-router.service
```

## Servicio

```text
triade-model-router.service
```

## Instalación local

```bash
cd ~/triadees
git pull
sudo cp systemd/triade-model-router.service /etc/systemd/system/triade-model-router.service
sudo systemctl daemon-reload
sudo systemctl enable triade-model-router
sudo systemctl start triade-model-router
sudo systemctl status triade-model-router --no-pager
```

## Pruebas

```bash
curl http://127.0.0.1:8020/health
curl "http://127.0.0.1:8020/models/doctor?intent=analyze&urgency=medium"
```

## Stack esperado

```text
triade-api.service           active/running
n8n.service                  active/running
triade-chat-ui.service       active/running
triade-model-router.service  active/running
```

## Siguiente fase

```text
TRIADE_CHAT_UI_MODEL_ROUTER_1.6D
```

Objetivo: conectar la Chat UI con el Model Router para mostrar recomendaciones y permitir aplicar modelos sugeridos.
