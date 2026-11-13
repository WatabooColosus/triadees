# Tríade Ω · Estado 0.9

## Nombre de fase

```text
TRIADE_SYSTEMD_SERVICE_0.9
```

---

## Objetivo

Preparar Tríade Ω API para ejecutarse como servicio local 24/7 en la PC mediante `systemd`, con API key, CORS controlado, logs y backup básico de SQLite.

---

## Qué agrega esta fase

- Servicio ejemplo:

```text
systemd/triade-api.service.example
```

- Guía de backups SQLite:

```text
scripts/README_BACKUPS.md
```

- Documentación de instalación, validación, logs y firewall local.

---

## Instalar servicio systemd

Desde el repo:

```bash
cd ~/triadees
source .venv/bin/activate
git pull
pip install -r requirements.txt
pytest
```

Copiar servicio:

```bash
sudo cp systemd/triade-api.service.example /etc/systemd/system/triade-api.service
```

Editar variables:

```bash
sudo nano /etc/systemd/system/triade-api.service
```

Cambiar al menos:

```text
Environment="TRIADE_API_KEY=cambia-esta-clave-local"
```

Por una clave propia.

---

## Activar servicio

```bash
sudo systemctl daemon-reload
sudo systemctl enable triade-api
sudo systemctl start triade-api
sudo systemctl status triade-api
```

---

## Ver logs

```bash
journalctl -u triade-api -f
```

Últimos logs:

```bash
journalctl -u triade-api -n 80 --no-pager
```

---

## Probar servicio

```bash
curl http://127.0.0.1:8000/health
```

Con API key:

```bash
curl -X POST http://127.0.0.1:8000/triade/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: TU_CLAVE" \
  -d '{"text":"Run desde servicio systemd","source":"systemd-test","use_ollama":false}'
```

---

## Reiniciar / detener

```bash
sudo systemctl restart triade-api
sudo systemctl stop triade-api
sudo systemctl disable triade-api
```

---

## Backup antes de modo 24/7

```bash
mkdir -p backups
sqlite3 triade/memory/triade.db ".backup 'backups/triade-before-systemd.db'"
```

Verificar:

```bash
sqlite3 backups/triade-before-systemd.db ".tables"
```

---

## Firewall local

Si se va a usar solo en la misma PC, no abrir firewall.

Si se necesita acceso LAN:

```bash
sudo ufw allow from 192.168.0.0/24 to any port 8000 proto tcp
sudo ufw status
```

No abrir a internet sin túnel seguro, VPN o proxy con HTTPS.

---

## Configuración LAN

El servicio ejemplo usa:

```text
--host 0.0.0.0 --port 8000
```

Esto permite conexiones desde la red local si el firewall lo permite.

Desde otra máquina:

```bash
curl http://IP_DE_LA_PC:8000/health
```

---

## Estado

```text
TRIADE_API_SECURITY_AND_N8N_0.8 → TRIADE_SYSTEMD_SERVICE_0.9
```

---

## Siguiente fase sugerida

```text
TRIADE_LOCAL_PRODUCTION_HARDENING_1.0
```

Prioridades:

1. Probar servicio systemd real.
2. Confirmar reinicio automático.
3. Agregar rotación/limpieza de runs antiguos.
4. Crear flujo n8n real.
5. Preparar release v1.0 local.
