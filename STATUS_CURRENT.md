# Estado actual · Tríade Ω

**Corte: 2026-08-02.** SHA base de este corte: rama `audit/triade-integral-20260802`
sobre `75e71e7`.

Este documento es la **página viva** del proyecto: qué funciona demostrado, qué
no, cómo operarlo y cómo comprobar cada afirmación. Es el punto de entrada; el
detalle vive en `audit/` y en `TECHNICAL_DEBT.md`.

> **Regla de este documento.** Nada se declara funcional por existir el archivo,
> pasar una prueba unitaria, responder el endpoint o crear una fila. Cada
> afirmación de esta página lleva el comando que la comprueba. Si algo no se
> pudo demostrar, aquí dice *no demostrado*, no *funciona*.

---

## 1 · Veredicto

**OPERATIVO CON LIMITACIONES.**

| Dominio | Estado | Verificado |
|---|---|---|
| Runtime always-on y recuperación | operativo | 6/8 capacidades |
| Memoria y observabilidad | operativo | 4/4 |
| Aprendizaje desde conversación | operativo con un eslabón abierto | 5/9 |
| Educación neuronal y automejora | **no cierra el circuito** | 0/3 |

No hay porcentaje global: sería un número inventado. La matriz completa de 26
capacidades está en [`audit/TRIADE_CAPABILITY_MATRIX.md`](audit/TRIADE_CAPABILITY_MATRIX.md).

---

## 2 · Cómo se levanta

El Studio arranca **vacío**: ni Ollama ni la app se levantan solos tras un
reinicio. Si la URL pública no muestra nada, casi siempre es esto.

```bash
# 1 · Ollama
nohup ollama serve > /tmp/ollama.log 2>&1 &

# 2 · App Tríade (:8010)
cd /teamspace/studios/this_studio/triadees
set -a && . ./.env && set +a
setsid nohup python -m uvicorn apps.single_port_app:app --host 0.0.0.0 --port 8010 \
  --proxy-headers --forwarded-allow-ips='*' >> logs/studio-web.log 2>&1 < /dev/null &
```

Comprobación de que está vivo de verdad:

```bash
curl -s localhost:8010/api/runtime/heartbeat   # workers_active: true
curl -s localhost:8010/api/runtime/build       # learning_enabled, sha, rama
```

**Al parar la app, nunca `pkill -f uvicorn`**: el patrón coincide con la propia
shell que lo ejecuta y la mata. Usar el PID:

```bash
for p in $(pgrep -f 'uvicorn apps.single_port_app'); do kill $p; done
sleep 6   # esperar a que suelte el puerto antes de relanzar
```

**Base de producción**: `triade/memory/triade.db` (WAL, ~141 MB, 107 tablas).
`data/triade.db` está vacía y no es la real.

---

## 3 · Qué funciona, con su comprobación

### Runtime always-on

```bash
curl -s localhost:8010/api/runtime/heartbeat
sqlite3 triade/memory/triade.db \
  "SELECT task_type,status,COUNT(*) FROM autonomous_tasks
   WHERE updated_at > datetime('now','-5 minutes') GROUP BY 1,2;"
```

Debe haber movimiento en varios tipos. 12 tipos de tarea tienen ejecución real.

### Recuperación de leases vencidos

Cerrada el 2026-08-02. Antes **no se recuperaba ninguno**: el sensor vigilaba la
tabla retirada `worker_tasks`. Comprobación:

```bash
sqlite3 triade/memory/triade.db \
  "SELECT COUNT(*) FROM metabolic_receipts WHERE need_id LIKE 'lease_supervision%';"
```

Para verificarlo en vivo, inyectar una sonda con lease vencido y observar que se
recupera en menos de 30 s (procedimiento en
[`audit/TRIADE_RUNTIME_EVIDENCE.md`](audit/TRIADE_RUNTIME_EVIDENCE.md)).

### Aprendizaje desde conversaciones reales

**Encendido en producción** (`TRIADE_POST_RUN_LEARNING=1` en `.env`).

```bash
sqlite3 triade/memory/triade.db \
  "SELECT status,COUNT(*) FROM learning_queue GROUP BY 1;"
curl -s localhost:8010/api/knowledge/summary
```

Circuito demostrado de punta a punta el 2026-08-02:

```
conversación → tarea learning_candidate_generation (idempotente por run_id)
  → worker real → candidato atómico con risk_level del veredicto de seguridad
  → mission_planner encola la medición por su cuenta
  → evidencia con inferencia real: control 0.0 · tratamiento 1.0 · improved
  → evidence_verified
  → recuperado e inyectado en el contexto de un run posterior
```

### No-éxito-falso

Un efecto declarado sin recibo no se convierte en éxito. Se observa en las
transiciones reales:

```bash
sqlite3 triade/memory/triade.db \
  "SELECT DISTINCT reason FROM autonomous_task_transitions ORDER BY 1;"
```

`failed` es 0 en toda la historia: los fallos van a `dead_letter` tras agotar
reintentos, no se disfrazan de completados.

---

## 4 · Qué NO funciona

| ID | Qué | Impacto |
|---|---|---|
| **P1-03** | El saber verificado **se inyecta** en el prompt de producción pero el modelo de 3B lo ignora. Acierta 5/5 en el prompt aislado del experimento. | Inyección ≠ influencia. Se miden en prompts distintos |
| **P1-01** | La educación neuronal muere en `lesson_prepared`. `neuron_education_applications`: **0 filas**; `neuron_certifications`: **0** | No hay aplicación, ni medición, ni rollback |
| **P1-02** | `self_improvement_canary_observation`: handler completo, **cero productores** en todo el repo | Un canary que arranca no se observa nunca |
| **P3-01** | `HealthSensors._check_queue` cuenta sobre `worker_tasks`, retirada | Sensor ciego (no causa falso negativo) |
| **P3-02** | `memory_consolidation_review`: declarado, con política y handler, **sin productor** | Tipo muerto |
| **I-1** | Renovación de lease: cableada, pero `autonomous_lease_heartbeats` tiene 3 filas del 30-jul | **Incertidumbre**, no defecto confirmado |

La ruta antigua de aprendizaje **sigue activa** y contamina el corpus con 180
volcados de transcripción. Ya se puede retirar: ver §6.

---

## 5 · Trampas conocidas de este repositorio

Cosas que han costado horas y volverán a morder:

1. **Comparar timestamps con SQLite.** `datetime('now','-1 day')` devuelve
   `2026-08-01 03:55:12` (espacio) y las tablas guardan
   `2026-08-01T03:55:12.027832+00:00` (`T`). Como `'T' > ' '`, ese corte deja
   pasar filas anteriores. Generar el corte en Python con `.isoformat()`.
2. **Tablas retiradas.** `worker_tasks` no se escribe desde 2026-07-29. Está
   prohibido usarla como representación del estado actual. La cola viva es
   `autonomous_tasks`.
3. **Contención de la suite.** Parar el runtime antes de correr las pruebas
   completas, o fallan en falso.
4. **Búsqueda textual para el cableado.** El productor de la mayoría de tareas
   es `PlannedTask(task_type=…)` en `mission_planner.py`, no un `enqueue()`
   literal. Un análisis que solo mire `enqueue()` reporta 20 tipos huérfanos que
   no lo son.
5. **`pkill -f uvicorn`** mata la propia shell. Usar PID.
6. **Control contaminado.** Un experimento sobre un run no puede usar como
   control nada derivado de ese mismo run.

---

## 6 · Siguiente iteración, por orden

1. **P1-03** — que el saber verificado influya en el prompt real. Medir con la
   misma vara: control/tratamiento sobre el prompt **de producción**, no sobre
   uno aislado. Sin esa medición, ajustar el prompt es opinión.
2. **Retirar la ruta antigua** de aprendizaje, con migración de los 180 volcados.
   Ya hay evidencia dura del daño que hacía.
3. **I-1** con una sonda de tarea larga; luego P1-02, P3-01, P3-02.
4. **Diseñar el resolutor de la educación neuronal** (P1-01), con contrato de
   pruebas primero: versión anterior, diff, evidencia, baseline, métricas
   posteriores y rollback.

---

## 7 · Operación

### Apagar el aprendizaje sin desplegar código

```bash
sed -i 's/^TRIADE_POST_RUN_LEARNING=1/TRIADE_POST_RUN_LEARNING=0/' .env
# reiniciar la app
```

Copia del `.env` previo a la auditoría en `.env.backup-preaudit`.

### Apagar la concurrencia gobernada

```bash
TRIADE_WORKER_CONCURRENCY=0
```

### Suite completa

```bash
for p in $(pgrep -f 'uvicorn apps.single_port_app'); do kill $p; done
python -m pytest -p no:randomly     # 1809 pruebas, ~6:30
```

`ruff check .` reporta ~667 `EXE002` («ejecutable sin shebang») en todo el repo:
es el bit de ejecución del Studio, no deuda de código, e idéntico en `main`.

---

## 8 · Dónde está el detalle

| Documento | Contenido |
|---|---|
| [`audit/TRIADE_SYSTEM_MAP.md`](audit/TRIADE_SYSTEM_MAP.md) | Mapa de cableado: los 24 tipos de tarea con productor, carril y consumidor |
| [`audit/TRIADE_CAPABILITY_MATRIX.md`](audit/TRIADE_CAPABILITY_MATRIX.md) | 26 capacidades con estado y evidencia |
| [`audit/TRIADE_BREAKAGE_LOG.md`](audit/TRIADE_BREAKAGE_LOG.md) | Cada rotura: síntoma, causa raíz, reproducción, corrección, rollback |
| [`audit/TRIADE_RUNTIME_EVIDENCE.md`](audit/TRIADE_RUNTIME_EVIDENCE.md) | Comandos y resultados de los experimentos vivos |
| [`audit/TRIADE_LEARNING_TRACE.md`](audit/TRIADE_LEARNING_TRACE.md) | Una conversación seguida de principio a fin |
| [`audit/TRIADE_ITERATION_2.md`](audit/TRIADE_ITERATION_2.md) | El encendido del aprendizaje y el control contaminado |
| [`audit/TRIADE_REMAINING_GAPS.md`](audit/TRIADE_REMAINING_GAPS.md) | Confirmado frente a *no lo sé*, separados a propósito |
| [`TECHNICAL_DEBT.md`](TECHNICAL_DEBT.md) | Deuda técnica canónica |

---

## 9 · Historial de cortes

| Fecha | SHA | Qué cambió |
|---|---|---|
| 2026-08-02 | `audit/triade-integral-20260802` | Auditoría integral. P0 de recuperación de leases cerrado. Aprendizaje gobernado encendido en producción con filtro de seguridad en extracción y control aislado. Primer saber nacido de una conversación real |
| 2026-08-01 | `75e71e7` | Salud por progreso, watchdog escalonado, aprendizaje gobernado conectado (apagado) |
| 2026-08-01 | `1b8bc1f` | Concurrencia gobernada encendida por defecto |
