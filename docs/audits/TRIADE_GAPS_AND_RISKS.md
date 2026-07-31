# TRIADE_GAPS_AND_RISKS.md — Riesgos clasificados

**SHA:** `e3cba75` · **Fecha:** 2026-07-31
**Cobertura de esta versión:** Fases 1, 2, 3 (parcial) y 4 (metabolismo). Las
fases 5–16 no están cubiertas; los riesgos que se descubran allí **no** están en
esta lista todavía.

Clasificación: **P0** crítico · **P1** alto · **P2** medio · **P3** bajo.
Marcas: **[E]** evidencia · **[I]** inferencia · **[H]** hipótesis · **[NV]** no verificado.

---

## P1 — Alto

### P1-01 · El watchdog declara recuperación exitosa sin verificarla

**[E]** `scripts/runtime_watchdog.py:19` llama `watchdog.tick(process_running=True)`
sin pasar `verify_heartbeat`. En `triade/runtime/runtime_recovery.py:60`:

```python
heartbeat_ok = verify_heartbeat() if verify_heartbeat else True
```

→ en producción siempre `True` sin comprobar nada, y `:64` marca
`state = "runtime_recovered"`.

**[E] Impacto medido:** 510 filas en `runtime_recovery_events`, **todas**
`runtime_recovered`, **todas** con `task_ids: []` y `verify_heartbeat: true`,
causa `heartbeat_stale`. Es decir: 510 recuperaciones declaradas exitosas que no
comprobaron su propia postcondición.

**Riesgo:** cualquier decisión, alerta o informe que se base en
`runtime_recovery_events.state` está leyendo un éxito no verificado. Enmascara un
problema real de heartbeat en vez de exponerlo.

**Corrección mínima propuesta:** pasar un `verify_heartbeat` real desde el
entrypoint (leer `live_runtime_heartbeat` y comprobar que el timestamp avanzó
después de la recuperación); si no se puede verificar, el estado debe ser
`unverified`, no `runtime_recovered`.

### P1-02 · El watchdog no puede reiniciar workers, pero su contrato dice que sí

**[E]** `triade/runtime/watchdog.py:36-37` acepta `stop_workers` y `start_workers`;
`scripts/runtime_watchdog.py:19` no los pasa; `runtime_recovery.py:49,58` los
saltan por ser `None`.

**[E]** `process_running=True` está hardcodeado en `runtime_watchdog.py:19`: el
watchdog nunca comprueba si el proceso vigilado está vivo.

**Riesgo [I]:** el componente aparenta una capacidad de auto-reparación que en la
configuración real de producción no tiene. Mitigado en la práctica por
`Restart=always` de systemd (que sí reinicia procesos muertos), pero eso significa
que **la reparación real la hace systemd, no Tríade**.

**Nota de honestidad:** el watchdog **sí** repara algo real —
`runtime_recovery.py:51` `recover_expired()` sobre leases— y **sí** valida
integridad SQLite (`:53-55`). No es un componente vacío. El problema es el
desajuste entre lo que su interfaz promete y lo que su despliegue ejecuta.

---

### P1-03 · 93 necesidades metabólicas huérfanas sin ninguna ruta de recuperación

**[E]** En la DB real: 67 needs en `running` y 26 en `pending`, todas de la ventana
2026-07-30 03:21–04:22, mientras el sistema ha corrido 1817 ciclos desde entonces.

**[E] Causa raíz** — `triade/metabolism/recovery.py:16-23` solo escanea ciclos
`WHERE status IN ('running','starting') AND finished_at IS NULL`, y `:45-53` solo
repara needs `WHERE cycle_id=?` del ciclo que está recuperando.

**[E]** Los ciclos padres de esas 93 needs están **cerrados**: 67 con
`status='failed'`, 26 con `status='completed'`, todos con `finished_at` no nulo.
Nunca vuelven a escanearse → sus needs nunca se recuperan.

**[E]** Tasa de ciclos fallidos: 67 de 1817 (≈3,7 %), y cada fallo dejó needs
colgadas.

**Impacto [I]:** no bloquea la operación (siguen creándose ciclos), pero contamina
permanentemente cualquier métrica de backlog y deja trabajo marcado como "en curso"
que nadie ejecutará jamás.

**Corrección mínima propuesta:** al cerrar un ciclo (a `completed` o `failed`),
reconciliar en la misma transacción sus needs no terminales; o añadir un barrido
por antigüedad independiente del estado del ciclo.

---

## P2 — Medio

### P2-01 · Endpoint informa un hilo vivo que está muerto

**[E]** `GET /api/runtime/workers-always-on/status` devuelve
`active=True, status=running` mientras `thread_alive=False`.

**[E] Causa:** `triade/core/worker_autostart.py:219`
`raw_active = bool(thread_alive or service_status.get("running"))`, donde el
segundo término (`background_service.py:92`) comprueba si vive el **dueño del
lock**, que es *otro proceso*.

**Riesgo:** semántica engañosa en un panel de estado. El dato "hay workers
corriendo" es cierto; lo falso es atribuirlo al hilo de este proceso.
`thread_alive` expone la verdad y está en la respuesta, lo que baja la severidad.
**[E]** `restart_attempts=3`: el watchdog reintenta levantar ese hilo y siempre
pierde la carrera del lock (esfuerzo desperdiciado, sin daño a datos).

### P2-02 · Apagado incompleto: 5 de 7 hilos no se detienen ordenadamente

**[E]** `apps/single_port_app.py:147-149` solo detiene `NODE_LIVE_REGISTRY` y
`LIFE_PULSE`. No se llama a `stop_internal_runtime_background()`,
`stop_workers_always_on()`, `coordinator.stop()` ni al de model-acquisition.

**[I]** Al ser `daemon=True` el proceso termina igual, pero esos hilos no liberan
locks ni cierran ciclos ordenadamente. **[H]** Podría explicar ciclos o locks que
quedan marcados abiertos tras `systemctl restart` — **no confirmado**.

### P2-03 · Comparación de fechas ISO-T vs `datetime('now')` en SQLite

**[E]** Reproducido de nuevo en esta sesión (en una consulta ad-hoc propia): los
timestamps se guardan como `...T01:48:01+00:00` y `datetime('now')` devuelve
`... 00:53:00`; SQLite compara TEXT y `'T'` > `' '`, así que **todas** las filas
del día parecen "más recientes". Ya se corrigió una ocurrencia real en
`mission_planner.py` (commit previo).

**[NV]** No se auditó exhaustivamente el repo en busca de este patrón con
parámetros (`?`) en vez del literal `datetime('now')`. **Riesgo residual real.**

### P2-04 · Todo el trabajo de fondo comparte el GIL con el servidor HTTP

**[E]** Cero `asyncio.create_task` propias; 7 hilos daemon dentro del proceso API.
**[I]** El trabajo cognitivo de fondo compite por el GIL con el servidor que
atiende al usuario. Consistente con los cuelgues de dashboard observados
anteriormente en esta sesión (aunque su causa raíz confirmada fue otra: la
serialización de modelos en Ollama).

---

### P2-05 · 6 de 10 necesidades metabólicas son solo entradas de catálogo

**[E]** `triade/metabolism/needs.py:16-79` declara 10 kinds, pero `detect()`
(`:98-132`) solo crea 4, la política (`contracts.py:64,88`) solo habilita esos 4,
y el dispatcher (`coordinator.py:442-448`) solo tiene handler para esos 4.

`memory_maintenance`, `contradiction_detection`, `backlog_review`,
`artifact_review`, `snapshot_maintenance`, `internal_task_generation` **no pueden
dispararse jamás**. Confirmado en datos: 0 filas de esos kinds en `metabolic_needs`.

**Riesgo:** la documentación y el propio catálogo sugieren una cobertura de
mantenimiento (memoria, contradicciones, artifacts, snapshots) que **no existe en
ejecución**. Severidad P2 y no P1 porque no hay degradación activa: simplemente
esas funciones nunca se han prestado.

### P2-06 · 128 ejecuciones metabólicas sin verify aprobado

**[E]** `metabolic_receipts`: 4453 `execute/success` frente a 4325 `verify/passed`.
**[NV]** No se determinó si son verificaciones fallidas, omitidas o desfase de
escritura. Requiere una fase dedicada.

---

## P3 — Bajo

### P3-01 · Dos ejecutores de workers configurados sobre la misma base de datos

**[E]** Hilo `triade-workers-always-on` (proceso API) y proceso
`triade-workers.service` ejecutan ambos `WorkerBackgroundService.start()` con el
mismo `db_path`/`runs_dir`.

**[E] Está correctamente resuelto:** lock atómico `O_CREAT|O_EXCL`
(`worker_loop.py:217-229`) + comprobación previa de dueño vivo (`:209-216`).
Verificado en vivo: el lock lo tiene el proceso systemd (PID 772056).
**No hay doble ejecución.** Se registra como P3 por ser una duplicación de
configuración confusa, no un defecto operativo.

---

## Riesgos del encargo aún NO evaluados [NV]

Estos figuran en la Fase 16 del encargo y **no** se han verificado todavía:
metabolismo habilitado pero sin ciclos reales; canary sin tráfico real; LoRA
activo en DB pero no cargado en inferencia; memoria que consolida sin evidencia;
neuronas promovidas por contadores; competencias actualizadas sin evaluación;
runs cerrados sin artifacts completos; artifacts sin hash; recibos sin efecto;
tablas sin índices; tablas huérfanas; excepciones tragadas (censo completo).

**Nota:** algunos de estos ya tienen hallazgos previos documentados en
`TECHNICAL_DEBT.md` de sesiones anteriores (p. ej. la evidencia de educación que
queda en `decision='pending'` sin proceso que la resuelva), pero **no** con el
rigor de archivo:línea que exige este encargo.
