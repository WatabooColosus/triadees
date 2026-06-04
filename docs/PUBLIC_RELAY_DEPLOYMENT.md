# Tríade Ω · Public Relay

El relay público permite conectar celulares/tablets desde navegador sin depender
de que la PC central esté encendida ni de puertos abiertos en la red local.

## Servicio

App:

```text
apps.public_relay_app:app
```

Comando:

```bash
uvicorn apps.public_relay_app:app --host 0.0.0.0 --port ${PORT:-8000}
```

Variables obligatorias en producción:

```text
TRIADE_RELAY_PAIRING_TOKEN=<token para conectar dispositivos>
TRIADE_RELAY_ADMIN_TOKEN=<token para administrar nodos/jobs>
TRIADE_RELAY_DB=/data/public_relay.db
```

## Docker

```bash
docker build -t triade-public-relay .
docker run -p 8000:8000 \
  -e TRIADE_RELAY_PAIRING_TOKEN=... \
  -e TRIADE_RELAY_ADMIN_TOKEN=... \
  triade-public-relay
```

## Railway / Render

El repo incluye:

```text
railway.json
render.yaml
Procfile
Dockerfile
```

En el panel del proveedor:

1. Conectar el repo `https://github.com/WatabooColosus/triadees`.
2. Seleccionar rama con los cambios del relay.
3. Configurar variables:

```text
TRIADE_RELAY_PAIRING_TOKEN
TRIADE_RELAY_ADMIN_TOKEN
TRIADE_RELAY_DB
```

4. Publicar y abrir `/health`.

## Uso

Dispositivo:

```text
https://TU_DOMINIO_PUBLICO/?token=TOKEN_DE_PAIRING
```

Administración desde la PC:

```bash
python triade_digimon.py relay --url https://TU_DOMINIO_PUBLICO --admin-token TOKEN_ADMIN nodes
python triade_digimon.py relay --url https://TU_DOMINIO_PUBLICO --admin-token TOKEN_ADMIN jobs
```
