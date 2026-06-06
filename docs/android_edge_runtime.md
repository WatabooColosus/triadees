# Android Edge Runtime · Tríade Ω

## Estado operativo

Tríade Ω soporta nodos Android como capacidad edge de procesamiento. El nodo Android ejecuta inferencia local con `llama.cpp` y un modelo GGUF dentro del propio dispositivo.

## Flujo validado

```text
/api/run
→ TriadeRunner
→ EdgeContext
→ Android Node
→ llama.cpp nativo
→ modelo GGUF local
→ context_probe
→ edge_context.json
→ plan.json
→ memory_diff.edge_usage
```

## Verdad técnica

La federación Android actual es **task-parallel**.

La PC envía una tarea completa al Android. Android ejecuta esa tarea con sus propios recursos. Android devuelve una respuesta. La Central valida y decide si la usa.

Esto **no** es RAM compartida, no suma VRAM, no divide un mismo modelo entre PC y Android, no es tensor-parallel y no modifica memoria estable por sí solo.

## Roles

### PC / 8010

- Orquesta jobs.
- Ejecuta Central, Hipotálamo, Bodega, Cristal y Safety.
- Guarda runs y evidencia.
- Valida respuestas edge.
- Aplica fallback determinista.
- Mantiene auditoría.

### Android / TinyLlama

- Ejecuta inferencia local ligera.
- Procesa `context_probe`.
- Sugiere intención, urgencia, riesgo, `needs_tool` y keywords.
- Devuelve `raw_output` auditable.

Android no decide por la Central, no escribe memoria estable, no modifica archivos del repo y no ejecuta acciones sin validación.

## Archivos principales

```text
triade/federation/edge_router.py
triade/core/edge_processing.py
triade/core/edge_context.py
triade/core/pulse_context.py
triade/core/runner.py
apps/single_port_app.py
scripts/audit_edge_usage.py
scripts/audit_live_pulse_consistency.py
```

## Artefactos por run

Cuando el edge está activo, cada run puede incluir:

```text
edge_context.json
plan.json
plan_enriched.json
memory_diff.json
output.json
```

Campo compacto esperado:

```json
{
  "used_edge": true,
  "accepted": true,
  "node_id": "local-...",
  "intent_probe": {
    "intent": "connect_apk_node",
    "urgency": "medium",
    "risk": "low",
    "needs_tool": true
  },
  "keywords": ["necesito", "conectar", "nodo"],
  "policy": "auxiliary_signal_only_central_validates"
}
```

## Pulso Vivo

El Pulso Vivo debe mostrar datos reales usados por Tríade.

Checks esperados:

```text
federation: ok
llm_android_host: ok
router: ok
ollama: ok si Ollama está activo
docker: ok si Docker está activo
semantic_memory: ok si gobierno semántico responde
signed_transport: ok si transporte firmado está activo
```

El contexto del run debe conservar datos reales:

```json
{
  "federation": {
    "node_count": 1,
    "online_count": 1,
    "android_native_online": 1,
    "android_llm_hosts": 1,
    "summary": "1 nodos Android alimentando",
    "llm_summary": "1 hosts LLM Android reales"
  }
}
```

## Auditoría

Auditar uso edge:

```bash
python scripts/audit_edge_usage.py --limit 30 --only-edge
```

Auditar consistencia Pulso Vivo vs run:

```bash
python scripts/audit_live_pulse_consistency.py
```

## Prueba manual de generación Android

```bash
curl -X POST http://127.0.0.1:8010/api/distributed-runtime/android-local-generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Responde en español breve: ¿qué es Tríade?","max_tokens":64,"context_tokens":2048,"wait_timeout":120}'
```

## Prueba manual de edge_context

```bash
python - <<'PY2'
from triade.core.edge_context import build_edge_context
import json, time

text = "Necesito conectar la APK como nodo real de procesamiento para Tríade."
t0 = time.time()
ctx = build_edge_context(text, enable_summary=False)
print(json.dumps({
    "elapsed_ms": int((time.time()-t0)*1000),
    "used_edge": ctx.get("used_edge"),
    "accepted": ctx.get("accepted"),
    "node_id": ctx.get("node_id"),
    "intent_probe": ctx.get("intent_probe"),
    "keywords": ctx.get("keywords"),
    "evidence_keys": list((ctx.get("evidence") or {}).keys()),
}, ensure_ascii=False, indent=2))
PY2
```

## Política de seguridad

El edge es una señal auxiliar. La Central siempre valida.

```text
Edge propone.
Central valida.
Bodega registra.
Safety bloquea si aplica.
```
