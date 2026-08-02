# TRIADE · Lo que queda, y lo que no sé

Auditoría 2026-08-02. Este archivo separa **hechos confirmados con evidencia** de
**incertidumbres explícitas**. Nada de lo que está aquí es hipótesis presentada
como hecho.

---

## A · Confirmado con evidencia — sigue abierto

### A-1 · La educación neuronal no aplica ni mide (P1-01)

`neuron_education_applications`: **0 filas**. `neuron_certifications`: **0**.
Las 7 sesiones que alcanzan `lesson_prepared` tienen `baseline_score=NULL`,
`post_score=NULL`, `applied_run_count=0`, `result='uncertain'`.

El tramo `aplicación → runs de evaluación → medición antes/después → decisión
improved/neutral/degraded → consolidación o rollback` **no tiene implementación**.
No es que falle: no existe.

### A-2 · `self_improvement_canary_observation` no tiene productor (P1-02)

Búsqueda AST sobre los 703 ficheros Python del repo: **cero** sitios que
construyan una tarea de ese tipo, ni en producción, ni en scripts, ni en pruebas.
Cero ejecuciones históricas. Un canary que arranca no se observa nunca.

### A-3 · El aprendizaje gobernado está apagado en producción

`TRIADE_POST_RUN_LEARNING` **no aparece en `.env`**. Consecuencia medida: cero
tareas `learning_candidate_generation` en toda la historia de `autonomous_tasks`,
mientras las etapas 2 y 3 (`deduplication` 325, `evidence_generation` 349)
corren constantemente sobre candidatos sembrados por la ruta antigua.

El nervio está conectado (commit `0c05715`) y verificado en copia. Falta la
decisión de encenderlo.

### A-4 · La ruta antigua vuelca transcripciones (P2, contamina el corpus)

**180 filas** de `learning_queue` son volcados crudos (`run_id:… input:…
response:…`). 655 de 656 candidatos atascados en `internally_checked`. La ruta
antigua sigue escribiendo: última fila 2026-08-01T21:45.

### A-5 · El extractor no filtra ataques a la identidad (P2-02)

Verificado: una instrucción para anular identidad y desactivar el RegressionGate
se acepta como `preference` con `risk_level='low'` fijo. La barrera de
recuperación sí lo bloquea, así que no llega a inyectarse — pero es una sola
puerta, y el corpus se contamina.

### A-6 · Dos tipos de tarea declarados sin productor

`memory_consolidation_review` y `self_improvement_canary_observation`: política
de concurrencia, intervalo adaptativo, handler completo, cero productores, cero
ejecuciones.

---

## B · Incertidumbres explícitas — no lo sé

### I-1 · Por qué `autonomous_lease_heartbeats` tiene 3 filas

**Lo que sé.** La tabla tiene 3 filas, todas del 2026-07-30 19:15-19:16.
`LeaseHeartbeat` está realmente cableado (`worker_loop.py:801` lo construye,
`1278` pasa `renew` al ejecutor con intervalo `min(lease/3, 15 s)`).

**Lo que no sé.** Si la explicación es benigna —casi ninguna tarea supera los
15 s, así que la primera renovación no llega a dispararse— o si la renovación no
funciona para las tareas largas. Las dos `neuron_education_cycle` colgadas
deberían haber renovado y no lo hicieron, pero también sufrieron una transición
a `retry_wait` que puede explicar su lease.

**Cómo resolverlo.** Inyectar una tarea que duerma más de 3 intervalos y observar
si aparecen filas con `renewed=1` y si `lease_expires_at` avanza.

### I-2 · Si la deduplicación agrupa correctamente

325 ejecuciones y 428 duplicados agrupados. **No verifiqué la corrección de los
grupos**: que el canónico elegido sea el adecuado y que no agrupe contenidos
distintos. Solo consta que corre y escribe.

### I-3 · Por qué 349 generaciones de evidencia no producen ningún saber

`learning_evidence_generation` corre 349 veces y `evidence_verified` sigue en 1
desde el 1-ago. La auditoría previa apuntaba a que
`evidence_bridge.require_improvement()` es un gate estricto y correcto al que le
falta el productor de la mejora. **No lo reverifiqué en esta auditoría**; lo
arrastro como hipótesis previa, no como hallazgo nuevo.

### I-4 · Comportamiento sin Ollama

No inyecté la caída de Ollama. Habría degradado el runtime del usuario durante la
ventana de auditoría y no era proporcionado con un P0 recién cerrado en
observación. **Capacidad nº 25: NOT OBSERVED**, no «funciona».

---

## C · Lo que NO se demostró en esta auditoría

Lo digo explícitamente para que nadie lo lea como verificado:

1. **Fase 3, pasos 9-19 completos.** Demostré extracción, idempotencia, latencia,
   rollback por variable y degradación. **No** demostré el recorrido completo de
   un candidato hasta `validated_in_runs` ni su uso trazable en un run posterior:
   requiere encender el aprendizaje en producción y esperar días de tráfico real.
2. **Prueba C de la Fase 9** (educación neuronal end-to-end): imposible, el
   circuito no existe más allá de `lesson_prepared` (A-1).
3. **Fase 10 en matriz completa de Python.** Ejecuté la suite en 3.12 (1.789
   pruebas, 0 fallos). No la ejecuté en 3.11 ni con la concurrencia desactivada
   como rollback.
4. **Repeticiones de escenarios de carreras.** No repetí las pruebas sensibles a
   carreras las veces necesarias para descartar un fallo probabilístico.
5. **Fase 6 por tipo de memoria.** Solo verifiqué memoria semántica (heredado de
   auditoría previa) y la cola de aprendizaje. Episódica, identidad protegida,
   preferencias y artefactos de run: sin comprobar.
6. **Conexiones SQLite no cerradas.** No hice el barrido de fugas que pide la
   Fase 6.

---

## D · Plan de siguiente iteración, por orden

1. **Resolver I-1** con la sonda de tarea larga. Es el único hueco que queda en
   el circuito de recuperación, y ahora es barato medirlo.
2. **Encender `TRIADE_POST_RUN_LEARNING` en modo sombra**: la ruta nueva procesa
   y registra, la antigua sigue operativa, y se comparan candidatos, latencia,
   seguridad y duplicación durante una ventana de días.
3. **Filtro de seguridad en extracción** (A-5), con `risk_level` derivado del
   contenido en vez de literal fijo. Defensa en profundidad, no puerta única.
4. **Productor de `self_improvement_canary_observation`** (A-2): el ciclo de
   automejora no cierra sin él.
5. **Diseñar el resolutor de la educación neuronal** (A-1), con contrato de
   pruebas primero: versión anterior, diff, evidencia, baseline, métricas
   posteriores y rollback.
6. Retirar la ruta antigua **solo** cuando 2 haya corrido en sombra sin
   divergencias.
