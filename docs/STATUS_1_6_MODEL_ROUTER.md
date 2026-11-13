# Tríade Ω · Model Router 1.6

## Nombre de fase

```text
TRIADE_MODEL_ROUTER_1.6
```

## Objetivo

Permitir que Tríade recomiende modelos por rol/neurona según intención, urgencia, disponibilidad de Ollama y prioridad de velocidad/profundidad.

## Archivos agregados/modificados

```text
triade/models/model_router.py
tests/test_model_router.py
triade_digimon.py
```

## Roles iniciales

```text
hypothalamus
central
creator
trainer
coder
embedding
fast
deep
```

## Comandos CLI

### Recomendar un modelo para un rol

```bash
python triade_digimon.py models route --role central
```

### Priorizar velocidad

```bash
python triade_digimon.py models route --role central --urgency high --prefer-speed
```

### Priorizar profundidad

```bash
python triade_digimon.py models route --role central --intent analyze --prefer-depth
```

### Diagnóstico completo de router

```bash
python triade_digimon.py models doctor
```

## Ejemplo de salida

```json
{
  "status": "ok",
  "ollama": {"ok": true, "models": ["qwen2.5:3b-instruct"]},
  "decision": {
    "role": "central",
    "selected_model": "qwen2.5:3b-instruct",
    "provider": "ollama",
    "reason": "Seleccionado qwen2.5:3b-instruct como mejor candidato disponible para rol central.",
    "fallback_used": false
  }
}
```

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
python triade_digimon.py models doctor
python triade_digimon.py models route --role coder
python triade_digimon.py models route --role central --urgency high --prefer-speed
```

## Estado

1.6A recomienda modelos pero todavía no reemplaza automáticamente los modelos del Runner.

## Siguiente paso

```text
TRIADE_MODEL_ROUTER_API_UI_1.6B
```

Objetivo:
- Exponer recomendación por API.
- Mostrar recomendación en Chat UI.
- Permitir botón "elegir modelo recomendado".

Luego:

```text
TRIADE_MODEL_ROUTER_AUTO_RUNNER_1.6C
```

Objetivo:
- Que Runner pueda usar el router para elegir modelo si el usuario no fija uno manualmente.
