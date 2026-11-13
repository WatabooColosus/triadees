# TRIADE · Matriz de capacidades

Auditoría 2026-08-02 · base `75e71e7` · rama `audit/triade-integral-20260802`.

Estados: **VERIFIED** (observado en runtime real, extremo a extremo) ·
**PARTIAL** (funciona una parte demostrable, falta tramo) ·
**DISCONNECTED** (implementado, sin productor o sin consumidor) ·
**BROKEN** · **NOT OBSERVED** (no se pudo demostrar en esta auditoría) ·
**BLOCKED BY ENVIRONMENT**.

Una capacidad **no** se marca VERIFIED por existir el archivo, pasar una prueba
unitaria, responder el endpoint o crear una fila.

| # | Capacidad | Impl. | Conect. | Prueba aislada | Prueba E2E | Runtime | Recuperable | Trazable | Riesgo | Estado | Evidencia |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Proceso always-on (supervisor + heartbeat) | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | `cycles_last_hour: 12`; ciclos metabólicos 4105→4154 continuos; `background_thread_alive: true` |
| 2 | Encolado autónomo de tareas | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | 3.697 tareas históricas; 12 tipos con ejecución real; `mission_planner` produce por consulta SQL, no a ciegas |
| 3 | Reclamación con lease (v2, fencing) | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | `autonomous_tasks` + `lease_generation`; transiciones registradas en `autonomous_task_transitions` |
| 4 | **Recuperación de leases vencidos** | sí | **sí (corregido)** | sí | sí | sí | sí | sí | **era crítico** | **VERIFIED** | P0-01. Antes: 0 recibos en 8.137 ciclos. Después: recuperación en <30 s bajo fallo inyectado |
| 5 | Reconciliación al arrancar | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | Tras reinicio, 2 tareas colgadas → `completion_uncertain` con `recovery:no_artifact_found` |
| 6 | No-éxito-falso (efecto sin recibo) | sí | sí | sí | sí | sí | — | sí | bajo | **VERIFIED** | Transición real: «El handler afirmó un efecto sin recibo verificable» → `retry_wait`; y `artifact_publication_pending` → `completed` solo tras `artifacts_published` |
| 7 | Concurrencia gobernada por carriles | sí | sí | sí | sí | parcial | sí | sí | medio | **PARTIAL** | 24 tipos con política declarada; carriles y claves de exclusión verificados en prueba. No forcé saturación de carriles en runtime vivo |
| 8 | Renovación de lease (heartbeat de tarea) | sí | sí | sí | no | **no** | — | parcial | medio | **NOT OBSERVED** | Cableado real (`worker_loop.py:801,1278`, intervalo ≤15 s). Pero `autonomous_lease_heartbeats` tiene **3 filas, todas del 30-jul**. No pude determinar si es que casi ninguna tarea supera el primer intervalo o si la renovación no dispara. Ver incertidumbre I-1 |
| 9 | Aprendizaje desde conversación · ruta gobernada | sí | sí | sí | sí | **no** | sí | sí | medio | **PARTIAL** | Nervio conectado (`0c05715`) pero **apagado en producción**: `TRIADE_POST_RUN_LEARNING` no está en `.env`. Cero tareas `learning_candidate_generation` en toda la historia |
| 10 | Aprendizaje desde conversación · ruta antigua | sí | sí | sí | — | sí | — | parcial | **alto** | **BROKEN** | Activa y escribiendo: **180 filas** de volcado de transcripción (`run_id:… input:… response:…`). 655 de 656 atascadas en `internally_checked` |
| 11 | Extracción con filtros (idempotencia, latencia, rollback) | sí | sí | sí | sí | no | sí | sí | bajo | **PARTIAL** | Verificado en copia: mismo `task_id` al reintentar, 1 fila; p50 **9,5 ms**; bandera apagada = 0 filas; fallo de cola reportado, no tragado. No observado en producción (flag off) |
| 12 | Filtro de seguridad en **extracción** | **no** | — | — | — | — | — | — | medio | **BROKEN** | P2-02. Instrucción de anular identidad aceptada como `preference` con `risk_level='low'` |
| 13 | Filtro de seguridad en **recuperación** | sí | sí | sí | sí | sí | — | sí | bajo | **VERIFIED** | `classify(malicioso) → blocked`, `classify(benigno) → allowed`; inyección solo admite `evidence_verified`/`stable` |
| 14 | Deduplicación de candidatos | sí | sí | sí | parcial | sí | sí | sí | bajo | **PARTIAL** | 325 ejecuciones reales; agrupa 428 duplicados. No verifiqué la corrección de los grupos |
| 15 | Generación de evidencia | sí | sí | sí | no | sí | sí | sí | medio | **PARTIAL** | 349 ejecuciones y **cero** saberes nuevos desde el 1-ago. Corre sin producir |
| 16 | Consolidación a saber verificado | sí | parcial | sí | no | **no** | — | sí | medio | **NOT OBSERVED** | `evidence_verified: 1` desde 2026-08-01T00:30, creado por script. `stable: 0`. Ninguna consolidación autónoma observada |
| 17 | Inyección de saber en conversación | sí | sí | sí | no | **no** | — | sí | bajo | **NOT OBSERVED** | Código correcto y filtrado. `used_today: 0`, `last_learning_used_at: null`. No hubo saber utilizable que inyectar |
| 18 | Educación neuronal → lección | sí | sí | sí | — | sí | sí | sí | bajo | **PARTIAL** | 21 sesiones; 7 llegan a `lesson_prepared` |
| 19 | Educación neuronal → aplicación y medición | **no** | **no** | no | no | **no** | no | no | **alto** | **DISCONNECTED** | P1-01. `neuron_education_applications`: **0 filas**. `neuron_certifications`: **0** |
| 20 | Canary de automejora: observación y graduación | sí | **no** | no | no | **no** | no | parcial | **alto** | **DISCONNECTED** | P1-02. Handler completo, **cero productores** en todo el repo (AST), cero ejecuciones |
| 21 | Memoria semántica (escritura y recuperación) | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | Verificado en auditoría previa (control 0.00 → tratamiento 1.00, 5/5). Umbral 0.55 |
| 22 | Observabilidad · resumen de saber | sí | sí | sí | sí | sí | — | sí | bajo | **VERIFIED** | `/api/knowledge/summary` cuadra con SQL: 227+428 = 655 `internally_checked`; `evidence_verified: 1` |
| 23 | Observabilidad · actividad de tareas | sí | **sí (corregido)** | sí | sí | sí | — | sí | medio | **VERIFIED** | P2-01. Antes: ventana falsa (205 vs 40 reales) y efecto derivado de contador de por vida |
| 24 | Persistencia tras reinicio de la app | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | Reinicio real: sin pérdida ni duplicación; tareas colgadas reconciliadas; `metabolic_cycle` continúa |
| 25 | Degradación sin Ollama | sí | sí | sí | no | **no** | — | sí | medio | **NOT OBSERVED** | No inyecté la caída de Ollama: habría degradado el runtime del usuario durante la ventana de auditoría |
| 26 | Suite y CI | sí | sí | — | — | — | — | — | bajo | **VERIFIED** | **1.789 pruebas, 0 fallos**, 6:28. `ruff format` limpio; mypy limpio en los ficheros tocados |

---

## Porcentaje por capacidad

No hay porcentaje global: sería un número inventado. Por familia:

| Familia | VERIFIED | PARTIAL | DISCONNECTED / BROKEN | NOT OBSERVED |
|---|---|---|---|---|
| Runtime always-on y recuperación (1-8) | 6 / 8 | 1 / 8 | 1 / 8 | 0 |
| Aprendizaje desde conversación (9-17) | 1 / 9 | 4 / 9 | 2 / 9 | 2 / 9 |
| Educación neuronal y automejora (18-20) | 0 / 3 | 1 / 3 | 2 / 3 | 0 |
| Memoria y observabilidad (21-24) | 4 / 4 | 0 | 0 | 0 |
| Entorno y calidad (25-26) | 1 / 2 | 0 | 0 | 1 / 2 |

**Runtime always-on: 75 % verificado.** El tramo que faltaba (recuperación de
leases) era precisamente el que lo hacía no apto; ya está cerrado y verificado en
vivo. Queda por demostrar la renovación de lease (nº 8).

**Aprendizaje: 11 % verificado.** La ruta gobernada está construida y probada en
copia, pero **apagada en producción**; la que corre de verdad es la antigua, que
vuelca transcripciones.

**Educación neuronal y automejora: 0 % verificado.** Ambos circuitos se detienen
antes de aplicar o medir nada.
