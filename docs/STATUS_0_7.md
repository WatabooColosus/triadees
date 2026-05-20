# Tríade Ω · Estado 0.7

## Nombre de fase

```text
TRIADE_API_LOCAL_FASTAPI_0.7
```

---

## Objetivo

Exponer Tríade Ω como API local HTTP para preparar integración con n8n, dashboards, otros nodos autorizados y herramientas externas.

---

## Qué agrega esta fase

- Aplicación FastAPI en `apps/api_app.py`.
- Comando CLI para levantar servidor:

```bash
python triade_digimon.py api
```

- Endpoints iniciales:

```text
GET  /health
POST /triade/run
GET  /triade/recall
GET  /triade/doctor
```

- Dependencias nuevas:

```text
fastapi
uvicorn[standard]
httpx
```

- Tests de API con `fastapi.testclient.TestClient`.

---

## Ejecutar API local

```bash
cd ~/triadees
source .venv/bin/activate
python triade_digimon.py api
```

Por defecto escucha en:

```text
http://127.0.0.1:8000
```

Con host/puerto personalizados:

```bash
python triade_digimon.py api --host 0.0.0.0 --port 8000
```

Para desarrollo:

```bash
python triade_digimon.py api --reload
```

---

## Probar endpoints con curl

### Health

```bash
curl http://127.0.0.1:8000/health
```

### Doctor

```bash
curl "http://127.0.0.1:8000/triade/doctor?use_ollama=false"
```

### Recall

```bash
curl "http://127.0.0.1:8000/triade/recall?query=run&limit=5"
```

### Run sin Ollama

```bash
curl -X POST http://127.0.0.1:8000/triade/run \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Run desde API local",
    "source": "curl",
    "use_ollama": false
  }'
```

### Run con Ollama

```bash
curl -X POST http://127.0.0.1:8000/triade/run \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Run desde API local con Ollama",
    "source": "curl",
    "use_ollama": true,
    "hypothalamus_model": "qwen2.5:3b-instruct",
    "central_model": "qwen2.5:3b-instruct"
  }'
```

---

## Validación local

```bash
cd ~/triadees
source .venv/bin/activate
git pull
pip install -r requirements.txt
pytest
python triade_digimon.py api
```

En otra terminal:

```bash
curl http://127.0.0.1:8000/health
```

---

## Integración futura con n8n

n8n podrá llamar:

```text
POST http://PC_LOCAL:8000/triade/run
```

Con un body JSON como:

```json
{
  "text": "Mensaje que llega desde n8n",
  "source": "n8n",
  "use_ollama": true
}
```

---

## Limitaciones actuales

- No hay autenticación todavía.
- No hay CORS configurado.
- No hay rate limit.
- No se debe exponer a internet sin protección.
- La API está pensada inicialmente para red local o pruebas controladas.

---

## Estado

```text
TRIADE_MODEL_ROLE_CLI_AND_QUALITY_0.6 → TRIADE_API_LOCAL_FASTAPI_0.7
```

---

## Siguiente fase sugerida

```text
TRIADE_API_SECURITY_AND_N8N_0.8
```

Prioridades:

1. Agregar token/API key local.
2. Configurar CORS controlado.
3. Crear workflow n8n básico.
4. Documentar uso desde red local.
5. Preparar servicio systemd para correr 24/7.
