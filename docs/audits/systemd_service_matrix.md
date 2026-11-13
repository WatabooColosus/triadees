# Systemd Service Matrix · Tríade Ω

## Servicios Instalados

| Unidad | Descripción | Estado | Enabled | Puerto | Dependencias |
|---|---|---|---|---|---|
| `triade-ollama.service` | Ollama model runtime | active | enabled | 11434 | network-online |
| `triade-api.service` | API single-port | active | enabled | 8010 | ollama |
| `triade-workers.service` | Workers gobernados | inactive | enabled | - | api |
| `triade-watchdog.service` | Progress watchdog | inactive | enabled | - | workers |
| `triade-backup.service` | Backup oneshot | inactive | enabled | - | - |
| `triade-backup.timer` | Backup diario | inactive | enabled | - | - |

## Archivos de Unidad

### `/etc/systemd/system/triade-ollama.service`
```
[Unit]
Description=Ollama model runtime for Tríade Ω
After=network-online.target

[Service]
User=agenciadigitalwataboo
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_MODELS=/teamspace/studios/this_studio/.ollama/models"
ExecStart=/teamspace/studios/this_studio/.ollama/runtime/bin/ollama serve
Restart=always
RestartSec=5
```

### `/etc/systemd/system/triade-api.service`
```
[Unit]
Description=Tríade Ω governed API (single-port)
After=network-online.target triade-ollama.service

[Service]
User=agenciadigitalwataboo
WorkingDirectory=/teamspace/studios/this_studio/triadees
EnvironmentFile=/etc/triade/triade.env
ExecStart=/home/zeus/miniconda3/envs/cloudspace/bin/python \
  -m uvicorn apps.single_port_app:app \
  --host 0.0.0.0 --port 8010 --proxy-headers --forwarded-allow-ips='*'
Restart=always
RestartSec=5
```

### `/etc/systemd/system/triade-backup.timer`
```
[Unit]
Description=Daily Tríade Ω backup timer

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=900
Unit=triade-backup.service
```

## Lightning Studio Auto-Start (`on_start.sh`)

Además de systemd, se configuró el script `~/.lightning_studio/on_start.sh` para iniciar Ollama y la API automáticamente cuando el entorno Lightning Studio se reinicia. Esto garantiza redundancia en el autoarranque.

## Orden de Arranque

```
1. network-online.target
2. triade-ollama.service (Ollama)
3. triade-api.service (API single-port)
4. triade-workers.service (Workers) [After=api]
5. triade-watchdog.service (Watchdog) [After=workers]
6. triade-backup.timer (Backup diario)
```

## Variables de Entorno (`/etc/triade/triade.env`)

```
TRIADE_API_KEY=
TRIADE_CORS_ORIGINS=http://127.0.0.1:5678,http://localhost:5678
TRIADE_PUBLIC_GUARDED=false
TRIADE_ALWAYS_ON=true
TRIADE_ALWAYS_ON_MODE=full_local_guarded
TRIADE_WORKERS_ALWAYS_ON=true
TRIADE_WORKERS_AUTOSTART=true
TRIADE_WORKERS_WATCHDOG=true
TRIADE_WORKER_MODE=full_local_guarded
OLLAMA_HOST=127.0.0.1:11434
OLLAMA_MODELS=/teamspace/studios/this_studio/.ollama/models
PYTHONUNBUFFERED=1
TRIADE_STUDIO_PORT=8010
```

## Políticas de Reinicio

| Servicio | Restart | RestartSec | TimeoutStopSec |
|---|---|---|---|
| triade-ollama | always | 5s | 30s |
| triade-api | always | 5s | 30s |
| triade-workers | always | 10s | 20s |
| triade-watchdog | always | 30s | 15s |
| triade-backup | oneshot | - | - |
