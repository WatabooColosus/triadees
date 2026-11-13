# Tríade Ω · Model Router API/UI 1.6B

## Nombre de fase

```text
TRIADE_MODEL_ROUTER_API_UI_1.6B
```

## Objetivo

Exponer recomendaciones del Model Router por HTTP para que puedan usarse desde UI, n8n o servicios locales.

## Estado actual

Por seguridad de integración, el router se expone inicialmente como una API independiente:

```text
apps/model_router_api.py
```

## Endpoints

### Health

```text
GET /health
```

### Doctor de modelos

```text
GET /models/doctor
```

Parámetros:

```text
intent=conversation|analyze|memory|build_or_update
urgency=low|medium|high
```

## Ejecución local

```bash
python -m uvicorn apps.model_router_api:app --host 127.0.0.1 --port 8020
```

## Pruebas

```bash
curl http://127.0.0.1:8020/health
curl "http://127.0.0.1:8020/models/doctor?intent=analyze&urgency=medium"
```

## Validación

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
```

## Siguiente paso

Integrar la recomendación en Chat UI para visualizar modelos sugeridos antes de enviar mensaje.
