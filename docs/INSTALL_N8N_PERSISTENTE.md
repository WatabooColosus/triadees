# Instalación persistente de n8n · Tríade Ω

## Decisión operativa

Para esta PC se recomienda instalar n8n con npm + systemd, no con Docker, porque el objetivo es que n8n permanezca activo después de apagar y encender la PC.

Docker también puede ser persistente si se configura con volúmenes, pero en este entorno ya hubo pérdida de estado. Por eso se prioriza instalación local con `N8N_USER_FOLDER=/home/santiago/.n8n`.

---

## Paso 1 · Verificar Node.js

n8n requiere Node.js compatible. Verificar:

```bash
node -v
npm -v
```

Si Node no existe o está por debajo de la versión requerida por n8n, instalar Node.js LTS antes de instalar n8n.

---

## Paso 2 · Instalar n8n global

```bash
npm install n8n -g
```

Verificar:

```bash
which n8n
n8n --version
```

---

## Paso 3 · Crear carpeta persistente

```bash
mkdir -p /home/santiago/.n8n
```

Esta carpeta guarda configuración, base local y datos de n8n.

---

## Paso 4 · Probar n8n manualmente

```bash
export N8N_USER_FOLDER=/home/santiago/.n8n
export N8N_HOST=127.0.0.1
export N8N_PORT=5678
export N8N_PROTOCOL=http
export TRIADE_API_KEY="TU_CLAVE_REAL"
n8n start
```

Abrir:

```text
http://127.0.0.1:5678
```

Detener prueba manual con `CTRL+C` antes de activar systemd.

---

## Paso 5 · Crear servicio systemd

```bash
sudo nano /etc/systemd/system/n8n.service
```

Contenido sugerido:

```ini
[Unit]
Description=n8n Automation Service
After=network-online.target triade-api.service
Wants=network-online.target
Requires=triade-api.service

[Service]
Type=simple
User=santiago
Group=santiago
WorkingDirectory=/home/santiago
Environment="PATH=/usr/local/bin:/usr/bin:/bin:/home/santiago/.npm-global/bin"
Environment="N8N_HOST=127.0.0.1"
Environment="N8N_PORT=5678"
Environment="N8N_PROTOCOL=http"
Environment="N8N_USER_FOLDER=/home/santiago/.n8n"
Environment="TRIADE_API_KEY=TU_CLAVE_REAL"
ExecStart=/usr/bin/env n8n start
Restart=always
RestartSec=5
TimeoutStopSec=20

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/home/santiago/.n8n /home/santiago/triadees

[Install]
WantedBy=multi-user.target
```

Reemplazar `TU_CLAVE_REAL` por la misma API key de Tríade.

---

## Paso 6 · Activar n8n como servicio

```bash
sudo systemctl daemon-reload
sudo systemctl enable n8n
sudo systemctl start n8n
sudo systemctl status n8n --no-pager
```

---

## Paso 7 · Validar persistencia

```bash
curl http://127.0.0.1:5678
sudo systemctl status n8n --no-pager
journalctl -u n8n -n 80 --no-pager
```

Reiniciar la PC y validar:

```bash
sudo systemctl status triade-api --no-pager
sudo systemctl status n8n --no-pager
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:5678
```

---

## Paso 8 · Importar workflow Tríade

Importar desde n8n:

```text
n8n/triade_basic_webhook_workflow.json
```

---

## Reglas importantes

- No ejecutar `n8n start` manual y `n8n.service` al mismo tiempo en el puerto 5678.
- No compartir la clave real.
- No exponer n8n a internet en esta fase.
- Si se usa LAN, configurar firewall y acceso controlado.
