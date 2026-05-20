# Tríade Ω · Estado 0.5

## Nombre de fase

```text
TRIADE_DUAL_MODEL_ROLES_0.5
```

---

## Objetivo

Conectar el Hipotálamo Emocional a modelo local Ollama para generar señales afectivo-cognitivas, manteniendo fallback por reglas si falla el modelo.

La Central ya usaba Ollama desde la fase 0.4. En esta fase se formaliza la arquitectura de doble rol:

```text
entrada → Hipotálamo modelo/reglas → señales → Central modelo/fallback → respuesta
```

---

## Qué agrega esta fase

- `Hypothalamus` acepta `model_client` y `model_name`.
- El Hipotálamo puede solicitar JSON de señales al modelo local.
- El JSON se valida y normaliza antes de crear `SignalPacket`.
- Si Ollama falla o devuelve JSON inválido, se usa fallback por reglas.
- `Runner` registra metadatos separados por rol:
  - `hypothalamus_model_provider`
  - `hypothalamus_model_name`
  - `hypothalamus_model_ok`
  - `hypothalamus_model_error`
  - `central_model_provider`
  - `central_model_name`
  - `central_model_ok`
  - `central_model_error`
- `integrity.json` incluye metadatos por rol.
- `memory_diff.json` incluye metadatos por rol.
- La salida del chat muestra Hipotálamo y Central por separado.
- Tests actualizados para validar fallback por rol.

---

## Señales que debe producir el Hipotálamo

```json
{
  "intent": "conversation|build_or_update|analyze|memory",
  "tone": "string",
  "urgency": "low|medium|high",
  "risk": "low|medium|high|critical",
  "pv7": {
    "humildad": 0.7,
    "generosidad": 0.7,
    "respeto": 0.8,
    "paciencia": 0.7,
    "templanza": 0.7,
    "caridad": 0.7,
    "diligencia": 0.8
  },
  "notes": []
}
```

---

## Validación sin Ollama

```bash
cd ~/triadees
source .venv/bin/activate
git pull
pytest
python triade_digimon.py run "Validación 0.5 sin Ollama" --no-ollama
python triade_digimon.py doctor --no-ollama
```

Resultado esperado:

```text
hypothalamus: rules:rules-fallback ok=false
central: template:template-fallback ok=false
```

---

## Validación con Ollama

```bash
ollama list
python triade_digimon.py doctor
python triade_digimon.py run "Validación 0.5 con Hipotálamo y Central usando Ollama"
```

Resultado esperado si ambos roles responden:

```text
hypothalamus_model_provider: ollama
hypothalamus_model_name: qwen2.5:3b-instruct
hypothalamus_model_ok: true
central_model_provider: ollama
central_model_name: qwen2.5:3b-instruct
central_model_ok: true
```

Si el Hipotálamo falla, el sistema debe conservar:

```text
hypothalamus_model_provider: ollama
hypothalamus_model_ok: false
```

Y usar señales por reglas.

---

## Limitaciones actuales

- El modelo del Hipotálamo puede devolver JSON inválido; se controla con fallback.
- Todavía no hay métricas de calidad por señal.
- No hay selección dinámica de modelo por CLI.
- No hay streaming ni API.
- No hay tabla dedicada para metadatos de modelo por rol; se usa `runs`, `memory_diff` e `integrity`.

---

## Estado

```text
TRIADE_OLLAMA_ADAPTER_0.4 → TRIADE_DUAL_MODEL_ROLES_0.5
```

---

## Siguiente fase sugerida

```text
TRIADE_MODEL_ROLE_CLI_AND_QUALITY_0.6
```

Prioridades:

1. Permitir elegir modelos por CLI.
2. Agregar métricas de calidad de señales.
3. Crear tabla dedicada para model events.
4. Mejorar prompt del Hipotálamo.
5. Preparar API local.
