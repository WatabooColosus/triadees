# n8n como servicio systemd · Tríade Ω

## Objetivo

Dejar n8n activo automáticamente cuando la PC se apague y vuelva a encender, igual que `triade-api.service`.

---

## Verificar si n8n existe

```bash
which n8n
n8n --version
```

Si no existe, instalar según tu método preferido.

---

## Servicio systemd sugerido para n8n instalado por npm

Crear archivo local:

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

Importante: reemplazar `TU_CLAVE_REAL` por la misma clave usada en `triade-api.service`.

---

## Activar servicio

```bash
sudo systemctl daemon-reload
sudo systemctl enable n8n
sudo systemctl start n8n
sudo systemctl status n8n
```

---

## Logs

```bash
journalctl -u n8n -f
```

---

## Probar n8n local

```bash
curl http://127.0.0.1:5678
```

También abrir en navegador:

```text
http://127.0.0.1:5678
```

---

## Relación con Tríade

El servicio n8n depende de `triade-api.service`:

```ini
Requires=triade-api.service
After=network-online.target triade-api.service
```

Esto ayuda a que Tríade API esté disponible antes de ejecutar automatizaciones.

---

## Si n8n usa Docker

Si se decide usar Docker, crear un servicio separado que levante el contenedor o usar Docker Compose. Esa ruta queda para una fase posterior si tu instalación real de n8n es Docker.
