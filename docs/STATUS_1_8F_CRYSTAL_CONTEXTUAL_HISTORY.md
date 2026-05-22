# Triade Omega - Crystal Contextual History 1.8F

## Fase

TRIADE_CRYSTAL_CONTEXTUAL_HISTORY_1.8F

## Objetivo

Evitar comparaciones temporales falsas del Cristal. Antes de esta fase, Crystal comparaba cada run contra los ultimos estados globales persistidos, aunque fueran tareas, proyectos o neuronas distintas.

A partir de 1.8F, la ventana historica se filtra por contexto comparable.

## Problema corregido

Un run de diagnostico tecnico no debe producir degradacion o mejora al compararse automaticamente con:

- una conversacion casual
- una pieza para Xiaos
- una tarea de Elestial
- una ejecucion de una neurona diferente

## Archivos

- triade/core/contracts.py
- triade/core/crystal.py
- triade/core/bodega.py
- triade/core/runner.py
- triade/memory/schemas.sql
- apps/single_port_app.py
- tests/test_crystal_contextual_history.py
- tests/test_crystal_context_migration.py
- tests/test_single_port_context.py

## Campos nuevos de CrystalPacket

- context_scope
- context_key
- comparison_basis

## Campos nuevos de crystal_states

- context_scope TEXT
- context_key TEXT
- comparison_basis TEXT
- source TEXT
- intent TEXT
- session_id TEXT
- project_id TEXT
- active_neuron TEXT

Bodega aplica migracion defensiva por ALTER TABLE a bases existentes y crea un indice para context_key despues de asegurar la columna.

## Jerarquia de contexto

Runner construye context_key usando la siguiente prioridad:

1. project_neuron, si existen project_id y active_neuron
2. neuron, si existe active_neuron
3. project, si existe project_id
4. session, si existe session_id
5. source_intent, cuando no se recibe contexto explicito

Todos los scopes incluyen intent para evitar comparar una conversacion contra una accion de construccion dentro del mismo proyecto.

## Ejemplos de context_key

Sin contexto explicito:

- source_intent|intent=conversation|source=single-port-ui

Con proyecto:

- project|intent=conversation|project_id=triade-local

Con proyecto y neurona:

- project_neuron|intent=build_or_update|project_id=xiaos|active_neuron=neurona-xiaos

## Comportamiento temporal

- Si no existe un cristal anterior con la misma context_key, temporal_status sera baseline.
- Si existe historial equivalente, Crystal calcula q_delta, stability_delta y tendencia solo con ese contexto.
- Los estados antiguos sin context_key no contaminan la primera linea base contextual nueva.

## API y UI

POST /api/run ahora acepta:

```json
{
  "text": "Continuar refinamiento",
  "source": "single-port-ui",
  "use_ollama": false,
  "context": {
    "project_id": "triade-local",
    "active_neuron": "cristal",
    "session_id": "sesion-01",
    "context_scope": "project_neuron"
  }
}
```

La UI en 8010 incorpora campos opcionales:

- Proyecto
- Neurona activa
- Sesion
- Scope

## Evidencia por run

El contexto utilizado aparece en:

- input.json dentro de context
- crystal.json como context_scope, context_key y comparison_basis
- memory_diff.json dentro de crystal_temporal_state
- integrity.json dentro de crystal_temporal_state
- SQLite crystal_states

## Validacion local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
sudo systemctl daemon-reload
sudo systemctl restart triade-chat-ui
```

Prueba de aislamiento entre dos proyectos:

```bash
curl -X POST http://127.0.0.1:8010/api/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"text":"Primera linea proyecto A","source":"api-test","use_ollama":false,"context":{"project_id":"proyecto-a","context_scope":"project"}}'

curl -X POST http://127.0.0.1:8010/api/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"text":"Continuidad proyecto A","source":"api-test","use_ollama":false,"context":{"project_id":"proyecto-a","context_scope":"project"}}'

curl -X POST http://127.0.0.1:8010/api/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"text":"Primera linea proyecto B","source":"api-test","use_ollama":false,"context":{"project_id":"proyecto-b","context_scope":"project"}}'
```

Resultado esperado:

- primer run proyecto-a: baseline y history_window=0
- segundo run proyecto-a: history_window mayor o igual a 1
- primer run proyecto-b: baseline y history_window=0

Consulta SQLite:

```bash
sqlite3 triade/memory/triade.db "SELECT run_id, context_scope, context_key, temporal_status, history_window, q_delta FROM crystal_states ORDER BY id DESC LIMIT 10;"
```

## Estado

Codigo subido a main. Pendiente de validacion local del usuario.

## Siguiente bloque recomendado

Tras validar 1.8F, Crystal v2 queda suficientemente afinado para pasar al siguiente bloque grueso:

TRIADE_SEMANTIC_MEMORY_1.9A

Objetivo: embeddings locales y recuperacion semantica real desde Bodega.
