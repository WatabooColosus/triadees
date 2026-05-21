# Tríade Ω · Estado 1.2E

## Nombre de fase

```text
TRIADE_NEURON_API_N8N_1.2E
```

## Objetivo

Exponer gestión de neuronas internas por FastAPI y preparar workflows n8n para crear/listar neuronas.

## Archivos modificados/agregados

```text
apps/api_app.py
tests/test_neuron_api.py
n8n/triade_neuron_list_workflow.json
n8n/triade_neuron_create_workflow.json
```

## Endpoints nuevos

### Listar neuronas

```text
GET /triade/neurons
```

### Ver neurona

```text
GET /triade/neurons/{name}
```

### Crear neurona

```text
POST /triade/neurons
```

Body:

```json
{
  "name": "Neurona API",
  "mission": "Misión verificable de la neurona.",
  "domain": "core",
  "rules": ["Debe registrar evidencia."]
}
```

## Workflows n8n

```text
n8n/triade_neuron_list_workflow.json
n8n/triade_neuron_create_workflow.json
```

Reemplazar en cada HTTP Request:

```text
REEMPLAZA_TU_API_KEY_AQUI
```

por la clave local.

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
sudo systemctl restart triade-api
```

Listar por API:

```bash
curl -i http://127.0.0.1:8000/triade/neurons \
  -H "X-TRIADE-API-Key: TU_CLAVE"
```

Crear por API:

```bash
curl -i -X POST http://127.0.0.1:8000/triade/neurons \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: TU_CLAVE" \
  -d '{"name":"Neurona API Real","mission":"Crear una neurona desde la API para validar gestión interna.","domain":"api","rules":["Debe ser verificable.","Debe registrar evidencia."]}'
```

## Estado

Esta fase permite que la gestión de órganos internos ya no dependa solo de CLI, sino que pueda integrarse con n8n y otras fuentes HTTP autorizadas.

## Siguiente fase sugerida

```text
TRIADE_LEARNING_QUEUE_1.3
```

Objetivo: activar cola de aprendizaje controlado.
