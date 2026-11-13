# Tríade Ω · Estado 0.4

## Nombre de fase

```text
TRIADE_OLLAMA_ADAPTER_0.4
```

---

## Objetivo

Agregar una primera capa real de modelo local usando Ollama, sin romper la estabilidad del MVP SQLite.

La fase 0.4 mantiene fallback por plantilla si Ollama no está instalado, no está corriendo o el modelo no está descargado.

---

## Qué agrega esta fase

- Paquete `triade/models/`.
- Adaptador `OllamaClient` usando HTTP local.
- Configuración `triade.yml`.
- Cargador simple de configuración `triade/core/config.py`.
- `Central` capaz de generar respuesta con Ollama.
- Fallback seguro por plantilla.
- Metadatos de modelo en `OutputPacket`.
- Registro del modelo usado en tabla `runs`.
- `doctor` reporta estado de Ollama y modelos disponibles.
- CLI con opción `--no-ollama`.
- Tests que validan fallback y metadatos sin exigir Ollama.

---

## Configuración base

Archivo:

```text
triade.yml
```

Contenido base:

```yaml
models:
  provider: ollama
  base_url: http://127.0.0.1:11434
  timeout: 60
  fallback_enabled: true
  roles:
    hypothalamus: qwen2.5:3b-instruct
    central: qwen2.5:3b-instruct
```

---

## Comandos de validación sin Ollama

```bash
cd ~/triadees
source .venv/bin/activate
git pull
pytest
python triade_digimon.py run "Validación 0.4 sin Ollama" --no-ollama
python triade_digimon.py doctor --no-ollama
```

Resultado esperado:

```text
model_provider: template
model_name: template-fallback
model_ok: false
```

---

## Comandos de validación con Ollama

Primero verificar Ollama:

```bash
ollama --version
ollama list
```

Si no está el modelo:

```bash
ollama pull qwen2.5:3b-instruct
```

Luego:

```bash
python triade_digimon.py doctor
python triade_digimon.py run "Hola Tríade, responde usando modelo local Ollama"
```

Resultado esperado si Ollama responde:

```text
model_provider: ollama
model_name: qwen2.5:3b-instruct
model_ok: true
```

Si Ollama falla, Tríade debe conservar el run y responder con fallback seguro.

---

## Nuevos campos en OutputPacket

```json
{
  "model_provider": "ollama|template",
  "model_name": "qwen2.5:3b-instruct|template-fallback",
  "model_ok": true,
  "model_error": null
}
```

---

## Registro en SQLite

La tabla `runs` usa:

```text
model_hypothalamus
model_central
```

`doctor` muestra `model_usage` para revisar qué modelos han sido usados en runs locales.

---

## Limitaciones actuales

- El Hipotálamo todavía usa reglas MVP; su modelo está configurado pero no conectado.
- El modelo central usa un prompt base, todavía no hay memoria semántica avanzada.
- No hay streaming.
- No hay API FastAPI.
- No hay selección dinámica de modelo desde CLI, solo desde `triade.yml`.

---

## Estado

```text
TRIADE_DIAGNOSTIC_AND_FULL_PERSISTENCE_0.3 → TRIADE_OLLAMA_ADAPTER_0.4
```

---

## Siguiente fase sugerida

```text
TRIADE_DUAL_MODEL_ROLES_0.5
```

Prioridades:

1. Conectar modelo de Hipotálamo para producir señales.
2. Mantener fallback de reglas si falla el modelo Hipotálamo.
3. Registrar `model_hypothalamus_ok` y errores por rol.
4. Mejorar prompts por rol.
5. Agregar selección de modelo por CLI.
