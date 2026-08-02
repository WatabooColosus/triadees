# TRIADE · Evidencia de runtime

Experimentos vivos del 2026-08-02. Comandos exactos, estados antes y después.

---

## Fase 0 · Verdad del repositorio

| Dato | Valor |
|---|---|
| SHA base | `75e71e7fea982a2a0d22e50daf4c412eaf9f5a67` |
| Rama base / auditoría | `main` (árbol limpio) / `audit/triade-integral-20260802` |
| Python | 3.12.11 (`/home/zeus/miniconda3/envs/cloudspace/bin/python`) |
| SO | Ubuntu 24.04.4 LTS, kernel 6.8.0-1064-gcp |
| App | `uvicorn apps.single_port_app:app` en `:8010`, pid 10074, arrancada 02:51:42 |
| Ollama | `ollama serve` pid 3354 + `llama-server` en `:55155` |
| DB producción | `triade/memory/triade.db` · 141 MB · WAL · `integrity_check: ok` · 107 tablas |
| `data/triade.db` | 0 bytes — no es la base real |
| Ficheros Python | 703 (excluyendo cachés) · 351 en `triade/` · 272 de prueba |
| Variables `TRIADE_*` efectivas | las de `.env`; **`TRIADE_POST_RUN_LEARNING` no está definida** |

---

## Fase 1 · Mapa de cableado por AST

Método: recorrido AST de los 703 ficheros. Se cuenta como **productor** toda
construcción de tarea (`f(task_type="X")`, `enqueue("X", …)`, `{"task_type":"X"}`),
distinguiendo producción / script / prueba, y separando el dispatch de handlers
de `worker_loop.py` para no confundir consumidor con productor.

> Una primera versión que solo miraba literales dentro de `enqueue()` daba 20
> tipos «sin productor». Era falso: el productor real es
> `PlannedTask(task_type=…)` en `mission_planner.py`, encolado después por
> `scheduler._enqueue_planned`. Queda anotado porque es exactamente el error que
> el encargo advierte: no fiarse de la búsqueda textual.

**Resultado: 24 tipos declarados, 24 con handler.**

| Sin productor en ningún sitio | Ejecuciones históricas |
|---|---|
| `self_improvement_canary_observation` | 0 |
| `memory_consolidation_review` | 0 |

**Tipos con handler y productor pero cero ejecuciones históricas** (10):
`bodega_global_review`, `experimental_neuron_activity`, `federation_inbox_review`,
`goal_install`, `goal_lora_train`, `semantic_memory_governance`,
`stable_consolidation_review`, `write_governed_text_artifact`,
`self_improvement_evaluation`, `learning_candidate_generation`.

Los `goal_*` y `write_governed_text_artifact` se producen por petición del
usuario vía `capability_resolver` → `goal_orchestrator`: no son autónomos, y su
ausencia no indica rotura.

**Tipos con ejecución real** (12) — recuento de por vida, corte 2026-08-02T03:52 UTC.
El sistema está vivo: estas cifras crecen mientras se lee.

| task_type | ejecuciones |
|---|---|
| `pulse_check` | 1.763 |
| `neuron_candidate_formation` | 385 |
| `learning_evidence_generation` | 358 |
| `learning_candidate_deduplication` | 334 |
| `neuron_autopromotion` | 324 |
| `system_debt_scan` | 274 |
| `pending_learning_review` | 205 |
| `research_curriculum` | 70 |
| `neuron_education_cycle` | 15 |
| `encrypted_backup` | 13 |
| `goal_safe_command` | 5 |
| `goal_research` | 3 |

---

## Fase 2 · Recuperación de leases vencidos

### Observación pasiva — el fallo

```bash
for i in 1 2 3 4 5 6; do
  date -u +%T
  sqlite3 triade/memory/triade.db "SELECT task_id,status,lease_expires_at,attempt
    FROM autonomous_tasks WHERE task_type='neuron_education_cycle'
    AND status NOT IN ('completed','skipped','blocked','dead_letter','observed');"
  sleep 40
done
```

| Momento | Estado |
|---|---|
| 03:03:34 → 03:06:54 | 2 tareas `running`, `lease_exp` 02:54:44 y 03:00:53, `attempt=2` |

Ventana de 3,5 minutos: `updated_at` congelado, leases vencidos hacía 12 y 6
minutos, **ninguna recuperación**. El resto de la cola progresaba
(`pulse_check` 33 completados en 10 min).

### Estado inicial de los contadores

```bash
sqlite3 triade/memory/triade.db \
  "SELECT COUNT(*) FROM metabolic_receipts WHERE need_id LIKE 'lease_supervision%';"
# 0    ← en 8.137 ciclos desde 2026-07-30

sqlite3 triade/memory/triade.db \
  "SELECT COUNT(*) FROM worker_tasks WHERE status='claimed';"
# 0    ← en toda la historia de la tabla legacy
```

### Verificación en copia fiel antes de tocar producción

```bash
sqlite3 triade/memory/triade.db ".backup '/tmp/…/copia.db'"
```

| Etapa | Antes | Después |
|---|---|---|
| Sensor | `{"ok": true, "stale_leases": 0}` | `{"ok": false, "stale_leases": 2}` |
| Necesidades emitidas | `[health_check, heartbeat, budget_check]` | `[…, lease_supervision (prio 80), …]` |
| Acción del coordinador | nunca ejecutada | `success released_2_stale_leases` |
| Tareas | `running`, lease vencido | `recovered`, `last_error='expired_lease_recovered'` |

### Inyección de fallo en runtime vivo (Fase 2, prueba nº 2)

Sonda `pulse_check` (segura e idempotente) insertada como `running` con lease
vencido 7 minutos:

```
SONDA: task-9fd2427fcdc74b639bfd30e61456c23f
03:41:09  sonda: running    | recibos lease_supervision: 0
03:41:39  sonda: completed  | recibos lease_supervision: 2
```

Necesidad emitida:

```
need_id: lease_supervision-ba7561119397   priority: 75
evidence_json: {"stale_leases": 1}        status: completed
```

Recibos (**los primeros de toda la historia del sistema**):

| receipt_id | cycle | stage | status |
|---|---|---|---|
| `mrec-b7c8e0f7d743` | 4154 | execute | success |
| `mrec-139fa6968a34` | 4154 | verify | passed |

Transiciones de la sonda:

```
running              → completion_uncertain  (artifact_publication_pending)
completion_uncertain → completed             (artifacts_published)
```

**Tiempo de recuperación: <30 s.**

### Reinicio del servicio con tareas activas (Fase 2, prueba nº 6)

Antes: 2 tareas `running` con lease vencido. Tras reinicio por la ruta oficial
(`.env` + uvicorn), la reconciliación de arranque las resolvió a
`completion_uncertain` con `recovery:no_artifact_found`. Sin pérdida ni
duplicación; `metabolic_cycle` continuó (4107 → 4154).

Nota honesta: esas dos tareas las cerró **la reconciliación de arranque**, no el
arreglo del sensor. La prueba del arreglo es la inyección posterior.

---

## Fase 2 · No-éxito-falso (Fase 9, prueba G)

Observado sin provocarlo, en tráfico real:

```
autonomous_task_transitions:
  running → retry_wait
  reason: "El handler afirmó un efecto sin recibo verificable"
```

Y en la sonda: `completed` solo se alcanza tras `artifacts_published`. Un efecto
declarado sin recibo no se convierte en éxito.

Reparto de estados en `autonomous_tasks` (3.749 filas, corte 2026-08-02T03:52 UTC):
`completed` 3.304, `observed` 251, `skipped` 134, `blocked` 41, `dead_letter` 17,
`completion_uncertain` 2. **`failed`: 0** — los fallos van a `dead_letter` tras
agotar reintentos, no se disfrazan de completados.

---

## Fase 3 · Camino gobernado de aprendizaje (en copia, con la bandera encendida)

```bash
sqlite3 triade/memory/triade.db ".backup '/tmp/…/fase3.db'"
TRIADE_POST_RUN_LEARNING=1 python fase3.py /tmp/…/fase3.db
```

### Extracción — 9 casos exigidos

| Caso | Resultado | Tipo / motivo |
|---|---|---|
| hecho estable | CANDIDATO | `fact` (explicitud 0.50) |
| preferencia | CANDIDATO | `preference` (1.00) |
| dato temporal | RECHAZADO | `sin_proposicion_explicita` |
| **instrucción maliciosa (identidad)** | **CANDIDATO** | **`preference` (0.80)** ← P2-02 |
| contradicción | CANDIDATO | `fact` (0.50) |
| duplicado | CANDIDATO | `fact` (0.50) |
| ambiguo | RECHAZADO | `especulativo` |
| sin material | RECHAZADO | `sin_proposicion_explicita` |
| corrección de respuesta | CANDIDATO | `correction` (0.80) |

`produce()` devuelve **como mucho un** candidato y solo sobre el mensaje del
usuario, nunca sobre la transcripción: el volcado monolítico es de la ruta
antigua, no de esta.

### Idempotencia

```
1ª llamada -> task-14434f0f5d1e4e5a…
2ª llamada -> task-14434f0f5d1e4e5a…   (mismo task_id)
filas encoladas para ese run -> 1
```

### Latencia del encolado (camino de respuesta al usuario)

```
n=20   p50 = 9,53 ms   p95 = 9,83 ms   max = 9,95 ms
```

Sin inferencia ni red. Aprender no retrasa la conversación.

### Rollback por variable de entorno

```
TRIADE_POST_RUN_LEARNING=0
-> {"scheduled": false, "reason": "post_run_learning_disabled"}
-> filas escritas: 0
```

### Degradación cuando la cola no se puede escribir

```
-> {"scheduled": false, "reason": "enqueue_failed",
    "error": "PermissionError: [Errno 13] Permission denied: '/ruta'"}
```

No lanza excepción, y **reporta** el fallo en vez de tragarlo.

### Barrera de seguridad aguas abajo

```
RetrievalSafetyPolicy.classify(malicioso) -> decision='blocked'
RetrievalSafetyPolicy.classify(benigno)   -> decision='allowed'
```

---

## Fase 7 · Observabilidad contrastada contra SQL

| Métrica de API | Valor | SQL directo | ¿Cuadra? |
|---|---|---|---|
| `/api/knowledge/summary` `evidence_verified` | 1 | 1 | sí |
| `/api/knowledge/summary` `candidates`+`duplicates` | 227+428=655 | `internally_checked` 655 | sí |
| `/api/learning/tasks` `scheduled_24h` (`pending_learning_review`) | **205** | 24 h reales: **40** | **no** → P2-01 |
| `/api/learning/tasks` `last_effect` | `produced_knowledge` | `learned_today: 0` | **no** → P2-01 |

---

## Fase 10 · Suite y calidad

```bash
python -m pytest -q -p no:randomly
# 1789 passed, 1 warning in 388.05s (0:06:28)

python -m ruff format --check .       # 901 files already formatted
python -m ruff check .                # 667 errores, TODOS EXE002, idénticos en main
python -m mypy triade/metabolism/health.py   # Success: no issues found
```

`EXE002` («fichero ejecutable sin shebang») afecta a los 667 ficheros porque el
Studio los tiene con bit de ejecución. Es idéntico en `main`: mis cambios son
neutros en lint. Los 5 errores de mypy en `apps/routes/api.py` también son
preexistentes (verificado con los cambios guardados en stash).
