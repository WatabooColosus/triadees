# TRIADE_LORA_SERVING_TRUTH.md — ¿El LoRA "activo" se usa de verdad?

**SHA:** `e3cba75` · **Fecha:** 2026-07-31 · **Fase 11 del encargo.**

El encargo exige explícitamente: *"No consideres un adapter operativo solo porque
tenga estado `active` en SQLite"*, y pide diferenciar siete niveles distintos.
Este documento responde exactamente eso.

Marcas: **[E]** evidencia · **[I]** inferencia · **[H]** hipótesis · **[NV]** no verificado.

---

## 1. Veredicto

**El adaptador está marcado `active` en la base de datos, aprobado por un humano
real, y no influye en ninguna respuesta que Tríade genere.**

La ruta de inferencia real **nunca consulta** el slot activo de LoRA.

---

## 2. Los siete niveles del encargo, resueltos con evidencia

| Nivel | Estado | Evidencia |
|---|---|---|
| 1. Adapter **entrenado** | ✅ SÍ | `trainable_adapters` = 2 filas reales |
| 2. Adapter **inscrito** | ✅ SÍ | `governed_peft_versions` = 1 fila |
| 3. Adapter **en canary** | ✅ SÍ | `peft_canary_events` = 3 filas (2 generaciones reales + 1 activación) |
| 4. Adapter **con observaciones** | ✅ SÍ | `governed_peft_observations` = 1 fila |
| 5. Adapter **aprobado** | ✅ SÍ | `peft_serving_state.approved_by = 'Santiago'` (humano real) |
| 6. Adapter **activo en DB** | ✅ SÍ | `peft_serving_state.status = 'active'`, slot `production` |
| 7. Adapter **realmente cargado** | ❌ **NO** | ver §3 |
| 8. Adapter **realmente usado en inferencia** | ❌ **NO** | ver §3 |

**[E]** Fila real en producción:

```
peft_serving_state: {slot: 'production',
                     adapter_path: '.../artifacts/adapters/triade-continuity-canary',
                     status: 'active',
                     approved_by: 'Santiago'}
```

---

## 3. Prueba de que la inferencia no lo usa

### 3.1 Nadie lee el slot activo fuera de su propio módulo

**[E]** `grep -rln "governed_peft_active_slot\|peft_serving_state"` sobre `triade/`
y `apps/` (sin tests) devuelve **exactamente dos archivos**:

```
triade/training/peft_canary.py          ← el módulo que lo ESCRIBE
triade/training/serving_governance.py   ← el módulo que lo ESCRIBE
```

**Cero lectores** en `triade/models/`, `triade/core/runner.py`,
`triade/core/central.py` — es decir, **cero lectores en toda la ruta que genera
las respuestas**.

### 3.2 El cliente de Ollama no conoce el concepto de adaptador

**[E]** `grep -ci "adapter|lora|peft"`:

- `triade/models/model_router.py` → **0 coincidencias**.
- `triade/models/ollama_client.py` → **1 coincidencia**, y es la línea 1:
  `"""Ollama adapter with safe fallback for Tríade."""` — la palabra "adapter"
  aquí es el *patrón de diseño adaptador*, **no** un adaptador LoRA.

**[E]** La petición real que se envía a Ollama (`ollama_client.py:83-91`) es:

```python
payload: dict[str, Any] = {"model": model, ...}
if system: payload["system"] = system
data = json.dumps(payload).encode("utf-8")
```

Solo un **nombre de modelo** en texto. No hay parámetro de adaptador, ni ruta de
pesos, ni referencia al slot activo.

### 3.3 Las dos rutas nunca se cruzan (explicación estructural)

**[I]** `PeftCanaryServer` (`triade/training/peft_canary.py`) carga el adaptador
en el propio proceso Python vía transformers/PEFT. Las conversaciones de Tríade,
en cambio, salen por HTTP a Ollama (proceso externo, binario Go). **Son dos motores
de inferencia distintos.** Un adaptador cargado por PEFT en el proceso Python no
puede afectar a lo que responde Ollama.

**[E]** `PeftCanaryServer`/`GovernedPeftServing` solo se usan en tres sitios:
`serving_governance.py`, `peft_canary.py` y `apps/routes/governance.py` — es decir,
la superficie de gobernanza/canary. **Nunca en el ciclo conversacional.**

---

## 4. Incoherencia adicional entre las dos tablas de gobernanza

**[E]** `peft_serving_state` = 1 fila con `status='active'`, pero
`governed_peft_active_slot` = **0 filas**.

Dos tablas destinadas a registrar el slot activo, en desacuerdo entre sí.
**[NV]** No se determinó cuál es la canónica ni si algún consumidor futuro leería
la vacía y concluiría "no hay adaptador activo".

---

## 5. Qué significa esto en la práctica

**No es un fallo de seguridad.** Al contrario: el gate de aprobación humana
funcionó (hay un `approved_by` real), y el hecho de que el adaptador no llegue a
producción significa que **ningún peso entrenado por el propio sistema está
influyendo hoy en sus respuestas**, que es el resultado más conservador posible.

**Es un fallo de honestidad del estado.** El sistema muestra
`slot=production, status=active` — literalmente "activo en producción" — cuando
el adaptador no toca ni una sola inferencia real. Cualquier panel, informe o
decisión basada en ese campo estaría equivocada.

**[I]** Cerrar el ciclo LoRA de verdad exigiría una de dos cosas, ninguna trivial:
1. Convertir el adaptador a un modelo Ollama (`ollama create` con el adapter
   fusionado) y hacer que el router seleccione ese nombre de modelo; o
2. Mover la inferencia de producción al motor PEFT en proceso, abandonando Ollama
   para ese rol.

**Recomendación de auditoría (no ejecutada, solo propuesta):** hasta que exista una
de esas dos rutas, el estado no debería poder marcarse `active`; debería existir un
estado intermedio explícito del tipo `approved_not_served`, para que el propio
sistema no afirme algo que no hace.

---

## 6. Límites de este análisis [NV]

- No se probó una inferencia con el adaptador cargado (habría requerido activar
  LoRA, **prohibido explícitamente** por las reglas del encargo).
- No se auditaron las métricas obligatorias del entrenamiento (forgetting, OOD,
  validation loss) ni los hashes del manifest.
- No se verificó el rollback ni su requisito de aprobación.
- No se determinó si el canary usa tráfico real o prompt sintético (pendiente de
  la Fase 11 completa).
