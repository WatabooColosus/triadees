# Tríade Ω · Estado 0.6

## Nombre de fase

```text
TRIADE_MODEL_ROLE_CLI_AND_QUALITY_0.6
```

---

## Objetivo

Permitir selección de modelos por rol desde CLI, registrar eventos de modelo en SQLite y comenzar a medir calidad básica de Hipotálamo y Central por run.

---

## Qué agrega esta fase

- Tabla SQLite `model_events`.
- Persistencia de eventos de modelo por rol.
- Métricas simples de calidad por rol:
  - `hypothalamus_quality_score`
  - `central_quality_score`
- IDs de eventos:
  - `hypothalamus_model_event_id`
  - `central_model_event_id`
- Selección de modelos por CLI:
  - `--hypothalamus-model`
  - `--central-model`
- `doctor` ahora muestra:
  - conteo `model_events`
  - resumen agrupado de eventos de modelo
  - calidad promedio por rol/modelo
- Tests ampliados para validar eventos, calidad y overrides.

---

## Comandos de validación

### Sin Ollama

```bash
cd ~/triadees
source .venv/bin/activate
git pull
pytest
python triade_digimon.py run "Validación 0.6 sin Ollama" --no-ollama
python triade_digimon.py doctor --no-ollama
```

Resultado esperado:

```text
hypothalamus_model_event_id: número
central_model_event_id: número
hypothalamus_quality_score: número
central_quality_score: número
model_events: mayor o igual a 2
```

### Con Ollama y modelos por defecto

```bash
python triade_digimon.py run "Validación 0.6 con modelos por defecto"
python triade_digimon.py doctor
```

### Con modelos seleccionados por CLI

```bash
python triade_digimon.py run "Validación 0.6 con modelos elegidos" \
  --hypothalamus-model qwen2.5:3b-instruct \
  --central-model llama3:latest
```

---

## Tabla model_events

```sql
CREATE TABLE IF NOT EXISTS model_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    ok INTEGER DEFAULT 0,
    error TEXT,
    quality_score REAL DEFAULT 0.0,
    latency_ms INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
```

Roles esperados:

```text
hypothalamus
central
```

---

## Criterio de calidad MVP

### Hipotálamo

Evalúa:

- Modelo respondió correctamente.
- `intent` válido.
- `urgency` válida.
- `risk` válido.
- PV-7 completo.

### Central

Evalúa:

- Modelo respondió correctamente.
- Longitud mínima de respuesta.
- Respuesta no excesivamente larga.
- Mención de Tríade.
- Cierre de frase básico.

Estas métricas son simples y deben evolucionar en fases siguientes.

---

## Estado

```text
TRIADE_DUAL_MODEL_ROLES_0.5 → TRIADE_MODEL_ROLE_CLI_AND_QUALITY_0.6
```

---

## Siguiente fase sugerida

```text
TRIADE_API_LOCAL_FASTAPI_0.7
```

Prioridades:

1. Crear API local con FastAPI.
2. Endpoints `/health`, `/triade/run`, `/triade/recall`, `/triade/doctor`.
3. Mantener compatibilidad con CLI.
4. Preparar conexión con n8n.
5. Crear pruebas básicas de API.
