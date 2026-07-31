# TRIADE_CONTEXT_TRACE.md — Runner, invariantes y coherencia contextual

**SHA:** `e3cba75` · **Fecha:** 2026-07-31 · **Fases 6 y 7 del encargo.**

Marcas: **[E]** evidencia · **[I]** inferencia · **[H]** hipótesis · **[NV]** no verificado.

---

## 1. Orden real del ciclo conversacional

**[E]** Verificado leyendo `triade/core/runner.py` (1808 líneas). El orden de
ejecución real, por número de línea:

| # | Etapa | Función | Línea |
|---|---|---|---|
| 1 | Señales | `self.hypothalamus.analyze(input_packet)` | `:326` |
| 2 | Memoria | `self.bodega.recall(...)` | `:429` |
| 3 | Gobernanza semántica | `govern_memory(...)` | `:438` |
| 4 | Cristal | `self.crystal.regulate(...)` | `:449` |
| 5 | Plan | `self.central.plan(input, signals, memory, crystal)` | `:453` |
| 6 | Safety | `self.safety.review(signals, plan, crystal, memory)` | `:499` |
| 7 | Respuesta | `self.central.respond(...)` (4 ramas) | `:504,544,548,554` |
| 8 | Memoria episódica | `self.bodega.store_episode(...)` | `:950` |
| 9 | Verificación | `self.verifier.verify(...)` | `:1004` |
| 10 | Persistir informe | `store_verification_report(report)` | `:1005` |
| 11 | Neuronas | `_process_neuron_contributions(...)` | `:1116` |
| 12 | Integridad y cierre | `write_run_integrity(...)` | `:1376` |

**El orden coincide con el diseño documentado.** No se detectó reordenamiento.

---

## 2. Las 12 invariantes del encargo, una por una

| # | Invariante | Veredicto | Evidencia |
|---|---|---|---|
| 1 | No hay respuesta sin señales del Hipotálamo | ✅ **CUMPLE** | `:326` < `:504` |
| 2 | Cristal regula antes del plan | ✅ **CUMPLE** | `:449` < `:453` |
| 3 | Safety revisa antes de la salida | ✅ **CUMPLE** | ver §3 |
| 4 | Verifier revisa después de la salida | ✅ **CUMPLE** | `:1004` > `:554` |
| 5 | El run cierra con integridad | ✅ **CUMPLE** | `:1376` `write_run_integrity` |
| 6 | Memoria episódica no antes de salida válida | ⚠️ **MATIZ** | ver §4 |
| 7 | Memoria estable no se modifica directamente | ✅ **CUMPLE** | hallazgos previos (gates de consolidación) |
| 8 | Ninguna neurona modifica `identity_core` | ✅ **CUMPLE (fuerte)** | ver §5 |
| 9 | Artifacts del mismo `run_id` | ✅ **CUMPLE** | `run_id` propagado desde `InputPacket` |
| 10 | El contexto recuperado pertenece a la solicitud actual | ❌ **NO GARANTIZADO** | ver §6 |
| 11 | Estados temporales no se filtran entre runs | ✅ **CUMPLE** | ver §6.2 |
| 12 | Los fallbacks no se saltan órganos | ✅ **CUMPLE** | ver §3 |

---

## 3. Invariantes 3 y 12 — las 4 ramas de respuesta

**[E]** `runner.py:499-554`. Existen **cuatro** llamadas distintas a
`central.respond(...)`, pero **todas están dentro de ramas posteriores a
`safety.review()` (`:499`)**:

| Rama | Línea | Condición |
|---|---|---|
| Bloqueada | `:504` | `safety.status == "blocked"` |
| Sandbox | `:544` | `safety.status == "sandbox_only"` |
| Aprobación humana | `:548` | `safety.status == "requires_human_approval"` |
| Normal | `:554` | `else` |

**[E]** Las cuatro reciben la firma completa
`(input_packet, signals, memory, crystal, plan)`. **Ningún fallback omite un
órgano.** Invariantes 3 y 12 **cumplen**.

**[E] Dato adicional:** el runner **sí maneja** `sandbox_only` (`:507`), pese a que
auditorías previas del proyecto (`ARCHITECTURE_MAP.md`, deuda D-09) indicaban que
Safety nunca lo emite. Es decir: la rama existe y está lista, pero **[I]**
probablemente nunca se ejecuta. Capacidad presente sin activación.

---

## 4. Invariante 6 — matiz real sobre la memoria episódica

**[E]** `store_episode` está en `:950`, **después** de generar la respuesta
(`:504-554`) → la invariante literal ("no antes de una salida válida") **se
cumple**.

**Pero [E]:** `:950` está **antes** de `verifier.verify()` (`:1004`).

**[I]** Consecuencia: el episodio se persiste antes de saber si la salida pasó la
verificación. Si el `Verifier` marca la respuesta como deficiente, el episodio ya
está en memoria. **[NV]** No se comprobó si existe una ruta que retire o degrade un
episodio tras una verificación negativa.

**Clasificación:** no es una violación de la invariante tal como está redactada,
pero sí una diferencia respecto a la lectura más estricta ("no persistir lo no
verificado"). Se registra como observación, no como fallo.

---

## 5. Invariante 8 — `identity_core` (defensa en profundidad, confirmada)

**[E]** Búsqueda de **cualquier** escritura (`INSERT INTO` / `UPDATE` /
`DELETE FROM`) sobre `identity_core` en todo el código de producción:

```
scripts/run_phase_03_identity_continuity.py:37   ← ÚNICA, y es un script de fase puntual
```

**Cero escrituras desde `triade/` y `apps/`.** El runtime, por construcción, no
tiene ruta para modificar la identidad.

**[E] Además, guarda explícita en el runner** (`runner.py:117-123`): las
contribuciones de neuronas que tocan `identity_core` se marcan `blocked` con
`block_reason: "identity_core_violation"`.

**[E]** `experimental_neuron_runtime.py:13` lo declara regla innegociable y `:111`
expone `identity_core_protected: True`.

**Veredicto: la invariante más crítica está bien defendida** — ausencia de ruta de
escritura **más** bloqueo explícito. No es solo declarativo.

---

## 6. Invariante 10 — hallazgo: no existe aislamiento por usuario ni sesión

### 6.1 La memoria episódica no tiene ámbito

**[E]** `InputPacket` (`triade/core/contracts.py:88-94`) contiene únicamente:

```python
user_input: str
source: str = "console"
context: dict[str, Any]
run_id: str
timestamp: str
```

**No existe `session_id` ni `user_id`.**

**[E]** `Bodega.recall(...)` (`bodega.py:29-37`) tampoco los acepta: su firma solo
tiene parámetros de recuperación semántica.

**[E]** `_search_episodic(query, limit=5)` (`bodega.py:506-520`) construye:

```sql
SELECT id, run_id, title, summary, tags, confidence, created_at
  ... WHERE content LIKE ? OR summary LIKE ? OR title LIKE ? OR tags LIKE ?
```

**Sin ninguna cláusula de usuario, sesión o ámbito.** Cualquier run puede recuperar
episodios de cualquier run anterior, de cualquier origen.

### 6.2 En cambio, el estado temporal del Cristal **sí** está acotado

**[E]** `bodega.py:205,232,248,255` — los estados del Cristal se almacenan y
recuperan con `context_scope`, `context_key`, `source`, `intent`, `session_id`,
`project_id`, `active_neuron`. **La invariante 11 sí se cumple** para el Cristal:
su historial temporal no se mezcla entre contextos distintos.

### 6.3 Valoración honesta del riesgo

**[I]** Tríade Ω es hoy un sistema **local monousuario**. Bajo ese modelo, "memoria
de otro usuario" no es una amenaza real y la ausencia de ámbito es una decisión
razonable, no un descuido.

**Pero [E] existen tres vectores que ya apuntan a multiusuario:**

1. `triade/core/user_session.py` existe, y la tabla `user_sessions` está en el
   esquema (vacía, 0 filas).
2. `apps/public_relay_app.py` es una superficie **pública** desplegada
   (Procfile/railway.json), con `/api/register` y `/api/heartbeat`.
3. Existe federación con nodos Android (`android/triade-node/`, cliente Java real).

**Conclusión [I]:** hoy no hay fuga porque solo hay un usuario. **El día que entre
un segundo origen, la memoria episódica no tiene ningún mecanismo que impida que
un run recupere episodios de otro.** Se clasifica como **P1 latente**, no como
incidente activo. `source` (`"console"`, `"react-ui"`, etc.) existe en el
`InputPacket` y sería el punto natural donde anclar un ámbito, pero **[E]** no se
usa para filtrar el recall.

---

## 7. Trazabilidad de identificadores [parcial]

**[E] Verificado:** `run_id` nace en `InputPacket` (`contracts.py:92`,
`default_factory=new_run_id`) y se propaga a `SignalPacket.run_id`
(`contracts.py:101`), a los artefactos del run y al `verification_report_id`
(`runner.py:1005-1006`).

**[E]** `learning_outcome_evidence_ref` se ancla como
`f"verification_report:{verification_id}"` (corregido en sesión previa) → la
evidencia de aprendizaje apunta al informe de verificación correcto del mismo run.

**[NV] No verificado en esta fase:** `trace_id`, `need_id`↔`task_id`,
`candidate_id`↔`evidence_id`, `artifact_id`, `receipt_id`, `model_event_id`, y la
comprobación de que un receipt apunte al efecto correcto. El encargo pide un
rastreo E2E controlado con todos ellos; **no se ejecutó**.

---

## 8. Comparación ciclo conversacional vs ciclo 24/7

**[E]** Confirmado en esta y en auditorías previas de la sesión:

| Órgano | Ciclo conversacional | Ciclo 24/7 (workers) |
|---|---|---|
| Hipotálamo | ✅ real (`runner.py:326`) | ❌ **no se invoca** |
| Cristal | ✅ real (`:449`) | ✅ real (conectado en sesión previa) |
| Bodega | ✅ real (`:429`) | ✅ real |
| Safety | ✅ real (`:499`) | ✅ real (`_safety_for_task`) |
| Central | ✅ real (`:453,504+`) | ⚠️ solo en handlers concretos |
| Verifier | ✅ real (`:1004`) | ❌ **no en tareas internas** |

**[I]** El ciclo de fondo **no** es una réplica del conversacional: opera sin
señales del Hipotálamo y sin Verifier. No es necesariamente incorrecto (son
trabajos distintos), pero contradice la idea de que "los mismos órganos trabajan
siempre".

---

## 9. No verificado [NV]

- Rastreo E2E controlado con los 12 identificadores del encargo.
- Si existe ruta que degrade un episodio tras verificación negativa.
- Si la rama `sandbox_only` se ejecuta alguna vez en la práctica.
- Crecimiento no acotado del contexto y qué porción de la Bodega llega al modelo.
