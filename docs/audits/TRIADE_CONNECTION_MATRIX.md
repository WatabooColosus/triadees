# TRIADE_CONNECTION_MATRIX.md — Workers, estados y conexiones a SQLite

**SHA:** `e3cba75` · **Fecha:** 2026-07-31
**Cobertura:** Fase 5 (workers/estados) + Fase 9 (tablas/persistencia).
Fases 6, 7, 8, 10–16 **no cubiertas**.

Marcas: **[E]** evidencia · **[I]** inferencia · **[H]** hipótesis · **[NV]** no verificado.

---

## 1. Máquina de estados real de `autonomous_tasks`

### 1.1 Dónde se define la tabla

**[E]** **No está en `schemas.sql`.** Se crea en
`triade/memory/migrations/009_runtime_resilience.sql:2-23`:

```sql
status TEXT NOT NULL DEFAULT 'pending',
```

**[E] No existe `CHECK` constraint sobre `status`.** El vocabulario de estados no
está restringido a nivel de esquema: cualquier cadena es aceptable para SQLite.

**[E]** Índices reales declarados (migración 009:24-27):

- `idx_autonomous_tasks_claim` sobre `(status, retry_after, priority, created_at)`
  → cubre exactamente el predicado de `claim()`. **Correcto.**
- `idx_autonomous_tasks_lease` sobre `(lease_expires_at, worker_id)`
  → cubre `recover_expired()`. **Correcto.**

### 1.2 Estados reales observados vs asignados

**[E]** Estados presentes en la DB de producción (`GROUP BY status`):

| Estado | Filas |
|---|---|
| `completed` | 1165 |
| `observed` | 96 |
| `skipped` | 82 |
| `blocked` | 38 |
| `completion_uncertain` | 8 |
| `dead_letter` | 1 |

**[E]** Estados que el código asigna en `triade/runtime/task_leases.py`:
`completed`, `completion_uncertain`, `deferred`, `leased`, `recovered`,
`retry_wait`, `running`.
**[E]** El claim además acepta como origen: `pending`, `queued`, `recovered`
(`task_leases.py:199`).

**[I]** Los estados transitorios (`leased`, `running`, `recovered`, `retry_wait`,
`deferred`, `pending`, `queued`) tienen 0 filas en el momento de la auditoría
porque son intermedios y el sistema estaba en reposo. No indica que no se usen.

**Comparación con los estados que el encargo asumía:** de la lista esperada
(`pending, claimed, running, completed, failed, blocked, cancelled, expired,
recovered, retrying`), **`claimed`, `cancelled`, `expired` y `retrying` no
existen** con esos nombres. Los equivalentes reales son `leased` (no "claimed"),
`retry_wait` (no "retrying") y la expiración no es un estado sino una transición
a `recovered`.

### 1.3 Auditoría de transiciones — existe y es correcta

**[E]** `triade/memory/migrations/012_truthful_task_states.sql` crea
`autonomous_task_transitions` con `from_status`, `to_status`, `reason`,
`lease_generation`, y **FOREIGN KEY a `autonomous_tasks(task_id)`** + índice por
tarea. Es una tabla de auditoría de transiciones real, no un log suelto.

---

## 2. Concurrencia: atomicidad, leases y fencing

### 2.1 Claim atómico — **[E] correcto**

`triade/runtime/task_leases.py:141-142` y `:192-199`:

```python
with self._connect() as conn:
    conn.execute("BEGIN IMMEDIATE")          # adquiere write-lock inmediato
    ...
    UPDATE autonomous_tasks SET status='leased', worker_id=?, ...,
           lease_generation=lease_generation+1
    WHERE task_id=? AND (status IN ('pending','queued','recovered') ...)
```

**`BEGIN IMMEDIATE` + UPDATE condicional = compare-and-swap atómico.** Dos workers
no pueden reclamar la misma tarea. **[E]** `lease_generation` se incrementa en cada
claim → **fencing token real**.

### 2.2 Recuperación de leases expiradas — **[E] real**

`task_leases.py:504-516`:

```python
conn.execute("BEGIN IMMEDIATE")
SELECT task_id FROM autonomous_tasks
  WHERE status IN ('leased','running') AND lease_expires_at<=?
→ UPDATE ... SET status='recovered', worker_id=NULL, ...
```

**[E]** Ambos lados de la comparación de fecha usan `_iso()` (mismo formato), por
lo que **aquí no aplica** el defecto ISO-T documentado en P2-03.

**Respuesta a la pregunta del encargo "¿puede una tarea quedar permanentemente en
`running`?":** **[E] No**, siempre que `lease_expires_at` esté poblado: el barrido
la devuelve a `recovered`. **[H]** Quedaría atascada si `lease_expires_at` fuese
NULL — no se verificó si existe una ruta que deje ese campo nulo con estado
`leased`/`running`.

### 2.3 Renovación de lease — **[E] existe**

`triade/runtime/lease_heartbeat.py:1` (`"""Periodic lease renewal with generation
fencing."""`), `:22-23` `renew()` delega en `store.renew(...)`.

---

## 3. SQLite: hallazgo sobre WAL

**[E]** Estado real de la DB de producción, consultado en vivo:

```
journal_mode = wal
busy_timeout = 5000
```

**[E]** `busy_timeout=5000` **sí** lo fija el código: `task_leases.py:78`
(`PRAGMA busy_timeout=5000`).

**[E] Pero `journal_mode` NO lo fija ningún archivo del repositorio.** Un `grep`
de `journal_mode` sobre `triade/`, `apps/` y `scripts/` (excluyendo tests) devuelve
**cero resultados** en contexto de asignación.

**Riesgo [I]:** WAL es una propiedad **persistente** del archivo de base de datos;
está activo porque alguien lo activó en algún momento fuera del código. Si la DB se
recreara desde cero (nuevo despliegue, restore a un fichero nuevo, entorno de CI),
arrancaría en `journal_mode=delete` — sin lectores concurrentes durante escritura,
con mucha mayor probabilidad de `database is locked` bajo la concurrencia real de
este sistema (múltiples procesos + 7 hilos). **Clasificado como P1-04.**

---

## 4. Censo de tablas: 104 totales, 32 vacías (31 %)

**[E]** Conteo real sobre la DB de producción.

### 4.1 Tablas vacías (0 filas)

```
auto_identity, benchmark_results, benchmark_tasks, capability_history,
capability_registry, federated_exchange_log, federated_merge_log,
federated_merge_nodes, goal_dependencies, goals, governed_peft_active_slot,
kg_contradictions, kg_edges, kg_nodes, meta_model_candidates,
meta_model_decisions, meta_model_evaluations, metabolic_config,
neuron_certifications, neuron_education_applications, orchestrator_locks,
regression_quarantine, regression_reports, reinforcement_log,
relational_modulation_events, relational_modulation_states,
runtime_queue_compatibility_events, sandbox_executions,
semantic_governance_events, semantic_memory, stable_capability_state,
user_sessions
```

**Nota metodológica importante:** *vacía ≠ muerta*. Varias están vacías por diseño
condicional y eso es **correcto**:

- `governed_peft_active_slot` → vacía porque **ningún LoRA se ha activado en
  producción** (coherente con el gate de aprobación humana; hallazgo previo).
- `federated_*` (3) → vacías porque no ha habido intercambio federado real.
- `orchestrator_locks` → vacía en reposo (se limpia al arrancar,
  `single_port_app.py:70-71`).
- `sandbox_executions` → el `AutonomousSandbox` se conectó recientemente.

### 4.2 Consumidores sin productor — **[E] hallazgo P2**

Prueba aplicada: buscar cualquier `INSERT INTO` / `UPDATE` de la tabla en código de
producción (excluyendo `tests/`).

| Tabla | Writers en producción | Readers | Veredicto |
|---|---|---|---|
| `goals` | **0** | 1 | **consumidor sin productor** |
| `neuron_certifications` | **0** | 1 | **consumidor sin productor** |

**`goals`** — **[E]** único lector: `triade/consciousness/salience.py:103`

```sql
SELECT title, description FROM goals WHERE status = 'active' LIMIT 5
```

**[E]** No existe ningún `INSERT INTO goals` ni `UPDATE goals` en `triade/`,
`apps/` ni `scripts/`. **[E]** Solo `tests/test_consciousness.py` escribe en ella.
→ El cálculo de "saliencia" de la consciencia lee objetivos que **nunca se crean**;
degrada silenciosamente a lista vacía. La tabla `goal_dependencies` también está
vacía. **[I]** La planificación autónoma por objetivos no existe en ejecución.

**`neuron_certifications`** — **[E]** único lector:
`triade/neuron_factory/certification.py:46` (subconsulta sobre sí misma).
**[E]** Cero writers en producción **y cero en tests**. Coherente con el hallazgo
previo de que `triade/neuron_factory/` solo se conecta a `self_improvement` y a
paneles de dashboard, no al ciclo 24/7.

### 4.3 `semantic_memory` vacía pero con 8 lectores

**[E]** `semantic_memory`: 0 filas, 1 writer, **8 readers**. La memoria semántica
real vive en `semantic_documents` + `semantic_embeddings` (que sí tienen datos).
**[H]** `semantic_memory` parece ser un vestigio del esquema anterior que múltiples
módulos siguen consultando y del que siempre obtienen vacío. **[NV]** No se
verificó si esos 8 lectores tienen fallback correcto o si degradan en silencio.

---

## 5. Respuestas directas de las Fases 5 y 9

| Pregunta del encargo | Respuesta | Marca |
|---|---|---|
| ¿El claim es atómico? | Sí: `BEGIN IMMEDIATE` + UPDATE condicional | [E] |
| ¿Hay fencing? | Sí: `lease_generation` incremental | [E] |
| ¿Se renuevan las leases? | Sí: `LeaseHeartbeat.renew()` | [E] |
| ¿Puede una tarea quedar en `running` para siempre? | No, si `lease_expires_at` no es NULL | [E] / [H] |
| ¿Hay WAL? | Sí en la DB, **pero no lo garantiza el código** | [E] |
| ¿Hay `busy_timeout`? | Sí, 5000 ms, fijado en código | [E] |
| ¿Hay CHECK sobre `status`? | **No** | [E] |
| ¿Hay auditoría de transiciones? | Sí, `autonomous_task_transitions` con FK | [E] |
| ¿Tablas huérfanas? | 2 consumidores sin productor: `goals`, `neuron_certifications` | [E] |
| ¿Estados del encargo correctos? | No: `claimed`/`cancelled`/`expired`/`retrying` no existen | [E] |

---

## 6. No verificado en esta fase [NV]

- Documentación de los 19 task types en las 15 dimensiones pedidas (payload,
  permisos, recursos, artifact, receipt, retry, rollback, tests, fallo) — solo se
  cubrió la máquina de estados y la concurrencia.
- Los 8 `completion_uncertain` y el 1 `dead_letter`: causa concreta.
- Writers/readers del resto de las 104 tablas (se auditó una muestra de 14).
- Retención/limpieza/crecimiento indefinido por tabla.
- Si los 8 lectores de `semantic_memory` degradan con seguridad.
