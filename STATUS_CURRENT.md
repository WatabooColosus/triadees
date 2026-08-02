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

### URL pública

```
https://8010-01kyngxf5vrjegqz9xrck5fwrf.cloudspaces.litng.ai/
```

**No se deriva del hostname del cloudspace.** El host actual es
`cs-01kz05gd8rh0sbn85qachsgzp2` y construir la URL a partir de él devuelve 404.
La buena es la de arriba.

### Si la web da 502

**Un 502 no es un fallo de Tríade.** Lo devuelve el proxy del Studio cuando no
hay nada escuchando en el 8010. La aplicación, cuando está viva, no sirve 5xx.

Comprobar en este orden:

```bash
grep -cE '" 5[0-9][0-9] ' logs/studio-web.log   # 0 => la app no fallo
pgrep -f 'uvicorn apps.single_port_app'          # vacio => esta parada
curl -s -o /dev/null -w '%{http_code}\n' localhost:8010/api/health
```

Si está parada, relanzarla con el bloque de arriba. **Causa más frecuente:
alguien paró el runtime para correr la suite completa** (§7) — son ~7 minutos
con la URL pública caída. Es una consecuencia conocida del procedimiento, no una
avería.

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

> **Tira la web durante ~7 minutos.** Hay que parar el runtime o las pruebas
> fallan en falso por contención con la base de producción, y con el 8010 vacío
> el proxy del Studio devuelve **502**. Es esperado. Avisar antes si hay alguien
> mirando el panel, y comprobar que vuelve al terminar.

```bash
for p in $(pgrep -f 'uvicorn apps.single_port_app'); do kill $p; done
python -m pytest -p no:randomly     # 1809 pruebas, ~6:30
# y RELANZAR la app (bloque de §2); luego:
curl -s -o /dev/null -w '%{http_code}\n' localhost:8010/api/health   # 200
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

---

## 10 · Corte 2026-08-02 · aprendizaje continuo cerrado

Segunda auditoría del día, rama `audit/triade-continuous-learning-runtime`.

**El circuito de aprendizaje desde conversaciones está cerrado y verificado en
producción**, de la conversación al uso posterior. Pasó del 11 % al 88 %
verificado. Faltaban tres eslabones, y los tres eran invisibles hasta encender
el circuito:

1. El **control contaminado** por la ruta antigua (invalidaba toda medición).
2. El **filtro de seguridad ausente** en la extracción.
3. La **rama de auditoría del prompt** descartaba el saber verificado — y esto
   corrige una conclusión falsa de la iteración anterior: no era que el modelo
   de 3B ignorase el bloque, es que el bloque no llegaba.

### Comprobación rápida del aprendizaje

```bash
python triade_digimon.py doctor continuous-learning
```

Devuelve `off`, `idle`, `stalled` o `healthy`, y **cada apartado declara de qué
tabla sale y en qué ventana**. Resuelve la configuración por entorno → `.env` →
defecto, y dice de dónde salió cada valor: el doctor corre desde una shell que
no tiene las variables del runtime, y mirar sólo `os.environ` daba `off` con el
aprendizaje encendido.

### Registro de autonomía

`triade/constitution/autonomy.py` responde en un solo sitio qué puede hacer
Tríade sin permiso: `AUTO_SAFE`, `AUTO_EXPERIMENTAL`, `HUMAN_REQUIRED`,
`FORBIDDEN`. Lo no declarado es `HUMAN_REQUIRED` — se falla cerrado.

**Está construido y probado pero todavía no gobierna ningún handler.** Es
contrato sin consumidor, que es justo el patrón que esta auditoría persigue.
Conectarlo es lo primero de la iteración siguiente.

### Inventario regenerable

```bash
python scripts/build_system_inventory.py    # -> audit/TRIADE_TASK_WIRING.md
```

714 módulos, 641 clases, 6.066 funciones, 24 tipos de tarea, 51 variables
`TRIADE_*`. El artefacto avisa de su propio límite: sólo ve literales, así que
marca como huérfanos cuatro tipos que se encolan con `task_type` en variable y
no están rotos.

### Validación de ventana larga

```bash
python scripts/run_long_validation.py --hours 2  --label v1
python scripts/run_long_validation.py --hours 24 --label v2
python scripts/run_long_validation.py --hours 72 --label v3
```

Escribe JSONL en `artifacts/long-run/`. **Si el SHA cambia a mitad, la ventana
se invalida** y el fichero lo dice: reutilizar evidencia de otro commit es la
forma más fácil de certificar algo que nunca corrió.

### Veredicto de este corte

**OPERATIVO CON LIMITACIONES.** Detalle y porcentajes por subsistema en
[`audit/TRIADE_CAPABILITY_MATRIX.md`](audit/TRIADE_CAPABILITY_MATRIX.md).

Lo que impide declararlo OPERATIVO: la educación neuronal no pasa de
`lesson_prepared` (0 % verificado), las ventanas de 24 h y 72 h no se han
cumplido, y el registro de autonomía aún no gobierna.
