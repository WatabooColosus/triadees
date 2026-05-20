# Tríade Ω · Local Release 1.0

## Estado

```text
TRIADE_LOCAL_PRODUCTION_HARDENING_1.0
```

## Componentes

- CLI auditable.
- SQLite persistente.
- Runs JSON por interacción.
- Hipotálamo + Central con modelos por rol.
- Ollama local con fallback.
- FastAPI local.
- API key.
- CORS controlado.
- systemd service.
- Backups documentados.
- Guía n8n.

## Validación esperada

```bash
pytest
sudo systemctl status triade-api
curl http://127.0.0.1:8000/health
```

Run protegido:

```bash
curl -X POST http://127.0.0.1:8000/triade/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: TU_CLAVE" \
  -d '{"text":"Release local 1.0","source":"release","use_ollama":false}'
```

## Siguiente etapa

```text
TRIADE_N8N_WORKFLOW_1.1
```
