# Fase 1 — Conversación mínima recuperada

Fecha: 2026-08-06
Rama: `fix/revive-triade-runtime`

## Resultado

El circuito mínimo quedó probado contra un proceso real:

```text
frontend servido → POST /api/run → Runner → Central → Ollama local
→ respuesta → cliente
```

Entrada enviada:

```text
Responde únicamente: TRIADA_VIVA
```

Respuesta recibida:

```text
TRIADA_VIVA
```

No se usó Claude, Codex, OpenAI, Gemini, Anthropic ni ningún proveedor remoto.

## Cambios

- `triade.yml` activa `runtime.conversation_only`: durante esta fase no se
  autoinician workers, runner continuo ni metabolismo, aunque los defaults
  generales Always-On permanecen compatibles.
- La ruta de chat desactiva por defecto la recuperación semántica; se reactivará
  explícitamente en la fase de persistencia.
- La SPA declara `semantic_recall_enabled: false` para no depender de Bodega
  semántica antes de cerrar el circuito básico.
- Se añadió `tests/test_chat_end_to_end_real.py`, que en modo real verifica el
  HTML, el bundle, `/api/run`, Central, Ollama y el episodio persistido.
- Se regeneró el bundle frontend servido por FastAPI.

## Evidencia real

- `request_id`: `phase1-final-20260806`
- `run_id`: `run-20260806-014033-37335fa7`
- HTTP: `200`
- Latencia: `25.698 s`
- Modelo: `qwen2.5:3b-instruct`
- Proveedor: `ollama` local
- Central: `ok: true`
- Episodio Bodega: `291`
- Señal Hipotálamo: `292`
- Cristal: `291`
- Ruta de run: `runs/run-20260806-014033-37335fa7`

La persistencia observada pertenece a `triade/memory/triade.db`. No se guardan
secretos ni cadenas internas de razonamiento en esta prueba.

## Pruebas

```text
TRIADE_REAL_E2E=1 TRIADE_E2E_BASE_URL=http://127.0.0.1:8011 \
  pytest -q tests/test_chat_end_to_end_real.py
1 passed
```

También pasan `compileall`, Ruff sobre el test, formato Ruff y mypy sobre el
test. La prueba real requiere un runtime local levantado y Ollama disponible;
sin `TRIADE_REAL_E2E=1` queda deliberadamente fuera de la suite CI que no tiene
modelo local.

## Límite de fase

Esto demuestra conversación mínima, no aprendizaje, metabolismo, workers ni
recuperación semántica. La fase 2 debe demostrar persistencia y recuperación tras
reinicio antes de reactivar procesos autónomos.
