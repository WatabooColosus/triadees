# TRIADE_RUNTIME_VERIFICATION.md — Registro de verificación ejecutada

**SHA auditado:** `e3cba75` (base) — documento creado en la misma sesión.
**Fecha:** 2026-07-31
**Regla:** solo se registra lo que se ejecutó de verdad. Cada resultado se marca
**[REAL]** (comando ejecutado, salida observada), **[INFERIDO]**,
**[NO COMPROBABLE]**.

---

## 1. Comandos ejecutados y resultado real

| # | Comando | Resultado | Marca |
|---|---|---|---|
| 1 | `git rev-parse HEAD` | `e3cba75be71561bc2fac006ddab76059884bcb5a` | [REAL] |
| 2 | `git status --short` | árbol limpio | [REAL] |
| 3 | `git ls-files '*.py' \| wc -l` | 647 | [REAL] |
| 4 | `wc -l` sobre `triade/ apps/ scripts/` | 95.425 líneas | [REAL] |
| 5 | `systemctl show ... -p MainPID` ×6 units | 4 activos, 2 inactivos (backup oneshot+timer) | [REAL] |
| 6 | `ss -tlnp \| grep :8010\|:11434` | API PID 800638 :8010; Ollama PID 346892 :11434 | [REAL] |
| 7 | `ls /proc/800638/task` | **12 hilos** en el proceso API | [REAL] |
| 8 | `ls /proc/772056/task` | **1 hilo** en el proceso workers | [REAL] |
| 9 | `grep -rn "threading.Thread(" triade/ apps/` | 9 creadores (7 en producción) | [REAL] |
| 10 | `grep -rn "asyncio.create_task\|ensure_future" triade/ apps/` | **0 resultados** | [REAL] |
| 11 | `cat runs/background/.triade_workers.lock` | dueño = PID 772056 (proceso systemd) | [REAL] |
| 12 | `GET /api/runtime/workers-always-on/status` | `active=True status=running thread_alive=False` | [REAL] |
| 13 | Consulta SQL `runtime_health_snapshots` | 1234 filas: 807 `stalled`, 427 `healthy` | [REAL] |
| 14 | Consulta SQL `runtime_recovery_events` | **510 filas, todas `runtime_recovered`** | [REAL] |
| 15 | Últimos 8 snapshots de salud | `healthy`, cadencia 60s exacta | [REAL] |
| 16 | `MAX(created_at)` en recovery_events | `2026-07-29T07:21:06` (ninguna desde entonces) | [REAL] |
| 17 | `py-spy dump --pid <api>` | **falló: py-spy no instalado** | [NO COMPROBABLE] |

---

## 2. Estado del sistema en el momento de la auditoría

**[REAL]** Los 4 servicios activos, API respondiendo 200, Ollama con 6 modelos,
`always_on effective_mode=full_local_guarded degraded=False`, integridad SQLite `ok`.

**[REAL]** Salud actual: los últimos snapshots consecutivos son todos `healthy`,
con cadencia exacta de 60 s. **Los 807 `stalled` son históricos** (concentrados
alrededor del 2026-07-29), no reflejan el estado presente.

---

## 3. Error metodológico propio detectado y corregido

**[REAL]** Una consulta ad-hoc mía usó
`WHERE created_at > datetime('now','-1 hour')` y devolvió 108 filas donde solo
podía haber ~60. Causa: los timestamps se almacenan en ISO con `T`
(`2026-07-31T01:48:01+00:00`) mientras `datetime('now')` devuelve
`2026-07-31 00:53:00` con espacio; SQLite compara TEXT y `'T'` (0x54) ordena
después del espacio (0x20), así que **todas** las filas del día comparan como
mayores. Es el mismo defecto que se encontró y corrigió antes en
`mission_planner.py`. **Se descarta ese 108 como dato inválido.** Se registra
aquí porque afecta a cualquier consulta futura sobre estas tablas.

**Implicación [I]:** cualquier consulta manual o de dashboard que compare
`created_at` contra `datetime('now')` en estas tablas es sospechosa por defecto.
**[NV]** No se auditaron todas las consultas del repo en busca de este patrón en
esta fase (el `grep` previo solo cubrió `datetime('now')` literal en código, que
dio 1 sola ocurrencia, ya corregida).

---

## 4. Watchdog — verificación específica (Fase 3)

### 4.1 Lo que el watchdog SÍ hace [REAL]

`triade/runtime/runtime_recovery.py:48-64`, ejecutado incluso sin callables:

- `:51` `self.tasks.recover_expired()` → **recuperación real de leases expiradas**.
- `:53-55` `PRAGMA quick_check` → **verificación real de integridad SQLite**.
- `:56-57` si la integridad falla → `raise` → estado `critical`.
- `triade/runtime/watchdog.py:93` → escribe cada tick en `runtime_health_snapshots`.

**Conclusión parcial:** el watchdog **no es puramente observacional**. Repara
leases y valida integridad.

### 4.2 Lo que el watchdog NO hace en producción [REAL]

`triade/runtime/watchdog.py:31-38` — `tick()` acepta tres callables de reparación:
`stop_workers`, `start_workers`, `verify_heartbeat`.

`scripts/runtime_watchdog.py:19` — el entrypoint real de producción llama:

```python
result = watchdog.tick(process_running=True)
```

**No pasa ninguno de los tres.** Consecuencia directa en
`runtime_recovery.py`:

- `:49` `if stop_workers:` → None → **no se ejecuta**.
- `:58` `if start_workers:` → None → **no se ejecuta**.
- `:60` `heartbeat_ok = verify_heartbeat() if verify_heartbeat else True`
  → **asume `True` sin comprobar nada**.

Además `process_running=True` está **hardcodeado** en `:19`: el watchdog nunca
comprueba si el proceso vigilado vive; se lo afirma a sí mismo.

### 4.3 Consecuencia observada en datos reales [REAL]

Las 510 filas de `runtime_recovery_events` son **todas** `state='runtime_recovered'`
y su `actions_json` es siempre:

```json
[{"action":"recover_expired_leases","task_ids":[]},
 {"action":"sqlite_quick_check","result":"ok"},
 {"action":"verify_heartbeat","result":true}]
```

- `task_ids: []` → **no recuperó ninguna tarea, ni una vez**.
- `verify_heartbeat: true` → **es el valor por defecto asumido**, no una comprobación.
- Causa registrada: `heartbeat_stale`.

**Hallazgo:** el sistema detectó 510 veces un heartbeat obsoleto, no ejecutó
ninguna acción correctiva sobre él, asumió que se había arreglado, y registró
**éxito** (`runtime_recovered`). Es un **falso positivo de recuperación
persistido 510 veces**.

**Matiz honesto [I]:** en la práctica el proceso no quedó desatendido, porque
systemd tiene `Restart=always` y ese sí reinicia procesos muertos. El watchdog
aporta la recuperación de leases; lo que no aporta —pese a declararlo— es la
verificación de que el runtime volvió a latir.

---

## 5. Lo que NO se pudo verificar en esta sesión [NO COMPROBABLE]

- Mapeo tid → nombre de hilo Python en el proceso vivo (falta `py-spy`; se
  descartó instrumentar producción).
- Comportamiento del watchdog bajo fallo real inducido (requeriría provocar una
  caída en producción — prohibido por las reglas del encargo).
- Fases 4 a 17 completas (metabolismo detallado, workers 19×15 dimensiones,
  runner, contexto, neuronas, memoria, modelos, LoRA, ocultos, matriz de
  conexiones, pruebas E2E, remediación).
