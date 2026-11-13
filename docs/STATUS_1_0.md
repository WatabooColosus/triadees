# Tríade Ω · Release local 1.0

## Nombre de fase

```text
TRIADE_LOCAL_PRODUCTION_HARDENING_1.0
```

---

## Objetivo

Cerrar la primera versión local operativa de Tríade Ω como sistema vivo en PC local:

```text
GitHub → fuente de verdad
PC local → cuerpo de ejecución
systemd → servicio 24/7
FastAPI → entrada HTTP
API key → seguridad local
SQLite → memoria persistente
Ollama → modelos locales
runs/ → evidencia auditable
doctor → diagnóstico operativo
n8n → integración externa controlada
```

---

## Estado confirmado antes de 1.0

Fases confirmadas en PC local:

```text
0.1 MVP SQLite
0.2 PC local running
0.3 Persistencia completa
0.4 Ollama para Central
0.5 Doble rol Hipotálamo + Central
0.6 CLI por modelos + calidad + model_events
0.7 API FastAPI local
0.8 Seguridad API key + CORS + n8n ready
0.9 systemd service 24/7
```

---

## Componentes activos

### CLI

```bash
python triade_digimon.py run "mensaje"
python triade_digimon.py chat
python triade_digimon.py recall memoria
python triade_digimon.py doctor
python triade_digimon.py api
```

### API

```text
GET  /health
POST /triade/run
GET  /triade/recall
GET  /triade/doctor
```

### Servicio

```bash
sudo systemctl status triade-api
journalctl -u triade-api -f
```

---

## Checklist de producción local

### 1. Código actualizado

```bash
cd ~/triadees
source .venv/bin/activate
git pull
pip install -r requirements.txt
pytest
```

### 2. Backup antes de cambios

```bash
mkdir -p backups
sqlite3 triade/memory/triade.db ".backup 'backups/triade-before-release-1-0.db'"
sqlite3 backups/triade-before-release-1-0.db ".tables"
```

### 3. Servicio activo

```bash
sudo systemctl daemon-reload
sudo systemctl restart triade-api
sudo systemctl status triade-api
```

### 4. Health check

```bash
curl http://127.0.0.1:8000/health
```

### 5. Run protegido

```bash
curl -i -X POST http://127.0.0.1:8000/triade/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: TU_CLAVE" \
  -d '{"text":"Release 1.0 health run","source":"release-1.0","use_ollama":false}'
```

### 6. Doctor protegido

```bash
curl "http://127.0.0.1:8000/triade/doctor?use_ollama=true" \
  -H "X-TRIADE-API-Key: TU_CLAVE"
```

---

## Operación diaria

### Ver estado

```bash
sudo systemctl status triade-api
curl http://127.0.0.1:8000/health
```

### Ver logs

```bash
journalctl -u triade-api -n 80 --no-pager
journalctl -u triade-api -f
```

### Reiniciar

```bash
sudo systemctl restart triade-api
```

### Detener

```bash
sudo systemctl stop triade-api
```

---

## Política de seguridad local

- No subir `.env` ni claves reales al repositorio.
- No compartir `TRIADE_API_KEY` en chat.
- No exponer puerto 8000 a internet.
- Usar LAN solo con firewall y API key.
- Para acceso externo futuro usar VPN, túnel seguro o proxy HTTPS.

---

## n8n básico

HTTP Request node:

```text
POST http://127.0.0.1:8000/triade/run
```

Headers:

```json
{
  "Content-Type": "application/json",
  "X-TRIADE-API-Key": "TU_CLAVE"
}
```

Body:

```json
{
  "text": "{{$json.message}}",
  "source": "n8n",
  "use_ollama": true,
  "hypothalamus_model": "qwen2.5:3b-instruct",
  "central_model": "qwen2.5:3b-instruct"
}
```

---

## Criterio de cierre 1.0

Se considera cerrado si:

- `pytest` pasa.
- `triade-api.service` está activo.
- `/health` responde `status=ok`.
- `POST /triade/run` bloquea sin key.
- `POST /triade/run` responde 200 con key.
- SQLite incrementa `runs`, `episodes`, `signals`, `verification_reports` y `model_events`.
- Existe backup previo al release.

---

## Estado

```text
TRIADE_SYSTEMD_SERVICE_0.9 → TRIADE_LOCAL_PRODUCTION_HARDENING_1.0
```

---

## Siguiente línea evolutiva

```text
TRIADE_N8N_WORKFLOW_1.1
```

Prioridades:

1. Crear workflow n8n real.
2. Integrar webhook externo controlado.
3. Enviar payload a `/triade/run`.
4. Guardar respuesta de Tríade en logs o almacenamiento.
5. Preparar permisos por fuente.
