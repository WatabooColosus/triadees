# Auditoría de Tríade — 21 de septiembre de 2026

**Actualización posterior:** el usuario autorizó la recarga. Véase
`reports/VERIFICACION_REINICIO_2026-09-21.md` para la intervención, la recuperación
de la API y sus límites. El resto de este documento conserva el corte inicial.

Tríade está activa, pero no se puede certificar operación óptima ni continuidad
sana de todos sus workers. El programador externo es quien realiza esta auditoría;
las misiones y la autonomía descritas por el usuario corresponden a Tríade.
El dibujo se interpreta como especificación de arquitectura, no como instrucciones
operativas provenientes de un documento adjunto.

## Alcance y base

- Checkout Windows local, `main`, HEAD `9c1fd1187760e42335f58dbfa0bbe153fd52fc01`.
- `git fetch origin` seguido de `git rev-list --left-right --count HEAD...origin/main`: `0 0`.
- Cambios previos conservados: `scripts/run_manual_tool.py`,
  `scripts/start_triade_windows.ps1`, `scripts/triade_service_worker.ps1`,
  `triade/observability/activation_contracts.py`.
- Inspección de arquitectura, arranque, locks, salud, modelos, colas, aprendizaje,
  Qualia/Cristal, frontend y configuración CI. Hay 355 archivos `test_*.py` en
  el primer nivel de tests: esta auditoría NO equivale a ejecutar la suite completa,
  auditar cada línea, verificar Android/federación remotos ni certificar la UI.
- SQLite inspeccionada con `sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)`.
  No se insertaron tareas, conversaciones, neuronas ni evidencias de salud.
  Las pruebas usaron bases aisladas dentro de `artifacts/audit-20260921/`.

## Hallazgos prioritarios

### P0: arranques competidores alteran el estado antes de fallar por puerto ocupado

`Get-NetTCPConnection -State Listen` identifica la API del puerto 8010 con PID
33532, creada el 18 de septiembre. El log
`artifacts/service_logs/triade-uvicorn.stderr.log`, actualizado durante la auditoría,
muestra otros PID completando startup y fallando con `WinError 10048`, seguidos de
shutdown. A las 20:31:41 UTC se observaron 108 eventos `always_on_started`,
108 `runtime_stop_requested` y 108 `workers_stop_requested` en la ventana reciente
consultada. Esa consulta previa comparaba texto de timestamps con formato mixto;
los conteos son diagnósticos, no una tasa exacta por hora certificada.

El supervisor usa Uvicorn en modo de un proceso. Ese arranque importa e inicia la
aplicación antes de reservar el puerto. Por tanto, una instancia rechazada puede
iniciar y parar subsistemas que comparten la misma base y archivos de control.
Esto es coherente con el heartbeat observado:

| Observación UTC | PID del heartbeat | Ciclo | Última actualización UTC |
|---|---:|---:|---|
| 20:31:07 | 21988 | 1 | 20:31:05 |
| 20:31:41 | 8308 | 1 | 20:31:28 |
| 20:34:55 | 25608 | 1 | 20:34:20 |
| 20:36:30 | 31360 | 1 | 20:36:25 |

Cambiar de PID manteniendo ciclo 1 no prueba un heartbeat continuo del servidor
que atiende HTTP. Los ciclos metabólicos avanzan, pero algunos pertenecen a
arranques efímeros. No se puede declarar saludable el conjunto por esa actividad.

**Reparación preparada:** `scripts/serve_local_api.py` reserva el socket antes de
importar la app; mantiene ese mismo socket durante la ejecución y lo cierra al
terminar. El supervisor Windows invoca este entrypoint. Una colisión termina
antes de ejecutar los subsistemas. Falta recargar el supervisor existente:
editar su archivo no sustituye el bucle PowerShell que ya corre en memoria.

### P0: identificación de locks no portable a Windows

`triade/runtime/process_lock.py` leía `/proc/<pid>/cmdline` y `/proc/<pid>/stat`.
En Windows devolvía vacío/None y podía recuperar un lock cuyo dueño seguía vivo.
La prueba `test_structured_live_lock_verifies_command_line` falló antes de la
reparación: devolvía `recovered` en lugar de `live_owner`.

**Reparación preparada:** usar `psutil` para comando y fecha de creación en Windows;
comprobar identidad de creación antes de depender del comando. El PID 33532 permite
leer fecha de creación pero no línea de comando desde esta sesión. Por eso también
se conserva un lock legacy de un PID vivo cuando el comando no es accesible:
falta de permiso no demuestra que el dueño haya muerto. Se mantiene el control
de autoridad por run existente en `WorkerStateStore`.

### P1: presión de memoria y selección de modelo contradictoria

`GET /health` devolvió 200 con RAM total 7,21 GB y disponible 0,17–0,28 GB en
las lecturas de aproximadamente 20:32 UTC. Ollama respondió en `/api/ps` y `/api/tags`
a través del diagnóstico de salud; la primera observación sólo mostraba
`nomic-embed-text:latest` cargado. Esto no demuestra inferencia de Central sana.

El router selecciona `qwen3:4b` para Central e Hipotálamo mientras lo enumera en
`rejected_by_hardware`. Causa visible en `triade/models/model_router.py`:
`_filter_by_hardware` devuelve `allowed or candidates[-2:]`; la ruta fallback
también puede tomar el primer instalado sin respetar los rechazos. Pendiente:
definir y probar una salida explícita sin modelo apto, revisar consumidores del
contrato y medir RAM/VRAM tras eliminar arranques competidores. No se cambiaron
modelos ni se descargaron pesos durante esta auditoría.

### P1: cola de errores, backup y aprendizaje sin cierre

Snapshot 20:36:30 UTC:

- Cola canónica `autonomous_tasks`: 106 completed, 189 dead_letter, 6 pending,
  1 running. `worker_tasks` está vacía; consultarla sola daría una conclusión falsa.
- Última actualización de dead_letter: 20:35:29 UTC. El total no demuestra que
  todas sean fallas nuevas; falta clasificar causas y efectos inciertos sin reintentar
  ni borrar automáticamente.
- Eventos `mission_planner.backup_key_missing` a las 20:22:18, 20:26:33 y
  20:30:44 UTC: el planificador no encuentra configuración de clave de backup.
  Los scripts declaran carga condicional de clave; esa declaración no demuestra
  que el proceso vivo la tenga. No se imprimieron ni modificaron claves.
- `learning_queue`: 5 evidence_verified y 18 internally_checked.
- `semantic_documents`: 6 candidate de tipo conversation_run; no hay documentos
  stable en esa tabla. No presentar candidatos como conocimiento consolidado.

## Contraste con el diseño solicitado

| Componente | Evidencia | Límite o pendiente |
|---|---|---|
| Central | `triade/core/central.py`, planificación y respuesta invocadas por Runner | Inferencia y latencia dependen de recursos y selección de modelo; no basta un plan almacenado |
| Creadora y Formativa | `neuron_creator.py`, `neuron_trainer.py`, `neuron_formation_pipeline.py`; ambas registradas stable con misión | Contratos contradictorios: `candidate_only`, `auto_stable_allowed=True`, prohibición de auto-promoción y normalización que impide stable. Hace falta unificar la autonomía efectiva, con evidencia, antes de ampliar actividad |
| Siete impulsos | Diez neuronas fundacionales registradas: Central, Creadora, Formativa y siete impulsos clásicos en `foundational_neurons.py` | Ser stable en registro declara disponibilidad del contrato, no aprendizaje demostrado |
| Hipotálamo | Tono, intención, riesgo, mood persistente, PV-7/PV-14 y modulación por Qualia en `hypothalamus.py` | Los nombres de dimensiones internas de `vice_virtue.py` difieren de los impulsos clásicos. No son siete modelos entrenados independientes |
| Bodega | Memoria episódica/semántica, categorías y subcategorías de `qualia_storage_packets`, trazabilidad por run | Consolidación estable pendiente; crecimiento de filas no equivale a aprender ni a indexar todas las fuentes externas |
| Qualia → Cristal → Central | Runner lee señales Qualia, modula Hipotálamo, recupera memoria, regula Cristal y después planifica con Central | Las experiencias del run se publican al final: parte del feedback alimenta ciclos posteriores |
| Cuentas/correos/apps autorizados | Hay gobernanza de datasets, permisos y entradas de conversación/federación | No se encontró un pipeline general OAuth/ingesta/revocación de correo/apps conectado a Qualia. No hay evidencia de esas fuentes en `qualia_experiences`; no está verificado ni terminado |

Qualia y Cristal sí mostraron progreso espontáneo durante la observación:
el último Cristal pasó de id 40 (20:11:03 UTC, Q=0,609) a id 41
(20:33:16 UTC, Q=0,705), con fuente `system_pulse_continuous`.
`post_run_learning` y `semantic_continuity` pasaron de 32 a 33 experiencias, y
`system_events` de 26 a 27, con última escritura 20:34:40 UTC. Esto acredita actividad
de ese recorrido; el incremento de Q no demuestra mejora general ni aprendizaje estable.

## Verificación y límites operativos

- `GET /health` y `/api/health`: 200. Son diagnósticos generales; su `status=ok`
  no certifica workers, heartbeat ni continuidad.
- `/health/live` y `/health/deep`: 403 `authenticated_session_required`.
  El middleware de modo público protege esas rutas. No se deshabilitó autenticación
  ni se fabricó una sesión. Falta verificarlas con sesión autorizada.
- Harbormaster no corre en este Windows: su módulo importa `pwd`. Se usaron
  `Get-NetTCPConnection`, CIM y psutil como alternativa de sólo lectura.
- Primera prueba tuvo errores de preparación por `--basetemp` relativo y el cambio
  de cwd de conftest; se corrigió el comando usando una ruta absoluta.
- Suite dirigida: **34 passed** (22,72 s): launcher, lifecycle/recovery/stop locks,
  Cristal, modulación Qualia, arquitectura workers, neuronas fundacionales,
  integración Runner/Qualia y fuentes gobernadas.
- Después de endurecer el caso de comando inaccesible: **15 passed** (2,78 s)
  en launcher/lifecycle/recovery/stop locks, incluyendo dos regresiones nuevas.
- Ruff check de los cuatro archivos Python modificados: correcto.
- Sin reinicio, commit, push, modificación de host ni reparación manual de filas.
  No se afirma que los cambios estén cargados en la API ni que el error haya
  desaparecido de los logs de los procesos antiguos.

Comando de validación final dirigida (TEMP/TMP apuntaron a artifacts/audit-20260921/tmp):

```powershell
python -m pytest tests/test_local_api_port_reservation.py tests/test_worker_lifecycle_hardening.py tests/test_worker_stop_lock.py tests/test_worker_runtime_recovery.py --basetemp C:/Users/sven6/Documents/Triade/artifacts/audit-20260921/test-base-6
```

## Siguiente intervención, pendiente de autorización operativa

1. Reidentificar el dueño de 8010 y el padre del bucle competidor inmediatamente
   antes de actuar; detener exclusivamente el arranque duplicado y recargar la API
   con el entrypoint corregido. No borrar locks, runs ni colas.
2. Verificar con autenticación liveness, deep health, Always-On y workers; comprobar
   dos observaciones del mismo proceso con heartbeat creciente, progreso de tareas,
   metabolismo y logs sin nuevas colisiones. Verificar Ollama sin inventar actividad.
3. Resolver configuración efectiva de backups y selección de modelos bajo presión.
4. Clasificar dead letters; después unificar autonomía Creadora/Formativa y completar
   ingesta consentida con alcance por usuario/fuente, procedencia y revocación.

La regla local dice: «Reinicia únicamente los servicios que necesiten recargar el
cambio y solicita autorización inmediatamente antes de cualquier reinicio o acción
con sudo». También exige autorización para modificar configuración del host.
La aplicación en vivo queda pendiente de esa autorización.
