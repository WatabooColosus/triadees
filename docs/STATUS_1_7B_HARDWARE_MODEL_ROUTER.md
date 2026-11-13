# Tríade Ω · Hardware-Aware Model Router 1.7B

## Nombre de fase

```text
TRIADE_HARDWARE_AWARE_MODEL_ROUTER_1.7B
```

## Objetivo

Hacer que el Model Router elija modelos no solo por rol/tarea, sino también por la capacidad real del sistema donde corre.

## Archivos agregados/modificados

```text
triade/models/hardware_profile.py
triade/models/model_router.py
apps/model_router_api.py
tests/test_hardware_profile.py
tests/test_model_router.py
```

## Hardware detectado

El perfilador detecta:

```text
cpu_count
ram_total_gb
ram_available_gb
tier: low | medium | high
notes
```

## Reglas iniciales

### Low

Evita modelos pesados como:

```text
llama3:latest
llama3.1:8b
qwen3:4b si la RAM disponible no alcanza
```

Prioriza:

```text
qwen3:1.7b
qwen2.5:3b-instruct
qwen2.5-coder:1.5b-base
nomic-embed-text
```

### Medium

Permite modelos medianos y 8B si hay RAM disponible suficiente:

```text
qwen2.5:3b-instruct
qwen2.5-coder:3b
qwen3:4b
llama3:latest
llama3.1:8b si memoria disponible >= umbral
```

### High

Permite máxima profundidad:

```text
llama3.1:8b
llama3:latest
qwen3:4b
qwen2.5-coder:3b
```

## API actualizada

```text
GET /health
GET /models/doctor
```

Ahora devuelven:

```text
hardware
router.hardware
rejected_by_hardware por decisión
hardware_tier por decisión
```

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
sudo systemctl restart triade-model-router
curl http://127.0.0.1:8020/health
curl "http://127.0.0.1:8020/models/doctor?intent=analyze&urgency=medium"
```

## Siguiente fase

```text
TRIADE_MODEL_ROUTER_AUTO_RUNNER_1.7C
```

Objetivo: que Runner use automáticamente el modelo recomendado cuando el usuario no fija modelos manuales.
