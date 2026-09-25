# Recarga autorizada de Tríade — 2026-09-21

Resultado: API restablecida con el entrypoint corregido y sin nuevas colisiones
en la ventana observada. Metabolismo y heartbeat avanzan en el mismo proceso.
Esto no certifica que todos los workers completen sus tareas ni elimina la
degradación por recursos.

## Operación realizada

La autorización del usuario fue «Si te autorizo», en respuesta a detener el
arranque duplicado y reiniciar la API para aplicar las correcciones.

- Antes de operar: `git status --short`, `git branch --show-current`,
  `git rev-parse HEAD`, `git fetch origin` y comparación con `origin/main`.
  Main sigue en `9c1fd1187760e42335f58dbfa0bbe153fd52fc01`, divergencia `0 0`.
- Inspección elevada a las 20:41:36 UTC: dos supervisores bajo SYSTEM,
  PID 27864 y 35740, ambos ejecutando `scripts/triade_service_worker.ps1`.
  API antigua: PID 33532, hija del segundo supervisor y dueña de 8010.
  El primero creaba instancias rechazadas por el puerto ocupado.
- Se comprobaron fecha de creación, comando, relación padre/hijo y listener
  antes de detener los dos supervisores. El hijo duplicado terminó por sí mismo.
- Ctrl+C no logró cerrar la API SYSTEM. Se terminó exclusivamente el PID 33532
  verificado a las 20:45:38–20:45:42 UTC. Fue un cierre forzado del proceso, no
  un cierre ordenado de Uvicorn; no se borraron locks ni datos para simular limpieza.
- `PRAGMA quick_check`, mediante conexión SQLite `mode=ro`: **ok**.
- `Start-ScheduledTask TriadeOmegaSystem` aceptó la solicitud, pero a las 20:47:15
  la tarea estaba `Queued` y no había listener ni supervisor. No se cambió su
  configuración. Se inició directamente el supervisor corregido, elevado,
  PID 26536. Su API PID 4988 arrancó a las 20:47:19 UTC.
- El servicio activo se recuperó mediante ese supervisor directo; no se afirma
  que la tarea SYSTEM ni el arranque tras reiniciar Windows hayan quedado certificados.
- Se conservaron copias de los logs anteriores en `artifacts/audit-20260921/`.

El nuevo log comienza con la reserva del listener y después con el inicio de
la app: `Uvicorn running ...`, `Started server process [4988]`,
`Waiting for application startup`, `Application startup complete`.
Esto coincide con `scripts.serve_local_api`, que reserva el puerto antes de importar
la aplicación y evita los efectos del arranque rechazado.

## Evidencia posterior

Snapshots reproducibles, sin construir servicios ni generar tareas artificiales:

```powershell
python artifacts/audit-20260921/observe_runtime.py after-reload-1
python artifacts/audit-20260921/observe_runtime.py after-reload-2
python artifacts/audit-20260921/observe_runtime.py after-reload-3
Get-NetTCPConnection -State Listen -LocalPort 8010
```

El Python usado fue el runtime existente de Codex. Los JSON conservan marcas UTC,
contadores, resultados HTTP y metadatos operativos, sin contenido de conversaciones
ni credenciales. El script abre SQLite con `mode=ro` y filtra eventos mediante
`julianday`, evitando comparar formatos distintos de timestamp como texto.

| Observación UTC | API/heartbeat PID | Heartbeat actualizado UTC | Ciclo heartbeat | Último ciclo metabólico completado |
|---|---:|---|---:|---:|
| 20:48:00 | 4988 | 20:47:53 | 1 | 1683 |
| 20:48:52 | 4988 | 20:48:43 | 1 | 1686 |
| 20:49:45 | 4988 | 20:49:42 | 3 | 1689 |

- `/health`: 200 `ok` en las tres observaciones. Pantalla de inicio de sesión
  de Tríade cargada en navegador después de la recuperación.
- `/health/live`, `/health/deep`, `/api/runtime/always-on/status`,
  `/api/runtime/workers-always-on/status` y `/api/runtime/heartbeat`: **403** sin
  sesión. Se solicitó al usuario iniciar sesión; no se deshabilitó el control
  ni se fabricaron credenciales para obtener un resultado verde.
- Un solo `always_on_started` y un solo `workers_started` desde la recarga;
  ciclos de runtime completados: 1 → 2 → 3. Los tres también registran
  `runtime_cycle_skipped_resource_cooldown`: hay continuidad, pero trabajo
  cognitivo restringido por recursos.
- Worker run conserva la misma identidad desde 20:47:35 y estado `running`.
  La tarea `system_debt_scan` renovó heartbeat/lease hasta 20:49:21.
  **A las 20:49:36 aparece `task_timeout`**, aunque el evento está etiquetado
  `status=ok`. Esa etiqueta no convierte un timeout en ejecución exitosa.
- Tareas `completed` no aumentaron en estas tres muestras: 106. Persisten 191
  dead_letter, 7 pending, 1 running y 1 completion_uncertain. No se reintentaron
  ni limpiaron manualmente. La recuperación normal puso una formación neuronal
  previa en completion_uncertain; no hay prueba de que su efecto deba repetirse.
- Qualia: 254 → 255 experiencias. Última: 20:49:36. El último Cristal sigue
  siendo id 41, anterior a la recarga; no se afirma progreso nuevo de Cristal
  en esta ventana.
- Ollama responde; `/api/ps` muestra `nomic-embed-text:latest`. No se ejecutó
  inferencia artificial para presentar al proveedor como sano.
- RAM disponible reportada por `/health`: 0,48 → 0,35 → 1,30 GB, sobre 7,21 GB.
  La mejora de la última muestra coincide con terminar una tarea por timeout;
  no se atribuye toda esa diferencia a la corrección del arranque.
- Log stderr nuevo: 199 bytes, cero `10048`, cero `ERROR`, cero `Traceback`
  al corte 20:49:45 UTC. Tampoco aparecen eventos `status=error` desde la recarga,
  pero el timeout se informa por separado porque se registra como `ok`.
- Ya se planificó una tarea `encrypted_backup` después de arrancar con el script
  actualizado. No aparecieron nuevos `backup_key_missing`; aún no hay prueba
  de backup terminado ni restauración verificada.

## Pendientes concretos

1. Verificar las rutas protegidas con una sesión autorizada; el 403 prueba el
   control de acceso, no el estado profundo del proceso.
2. Investigar el timeout de `system_debt_scan` y el avance efectivo de la cola.
3. Corregir la selección de modelos bajo presión y el contador del heartbeat:
   `MetabolicCoordinator._action_heartbeat` crea un objeto nuevo por llamada,
   de modo que puede sobrescribir el contador con 1. Existen otros pulsos que
   avanzan el contador; usar PID y timestamps para continuidad hasta unificarlo.
4. Diagnosticar por qué la tarea SYSTEM queda en cola y certificar arranque
   persistente. La recuperación actual mediante supervisor directo no sustituye
   esa validación.
5. Comprobar terminación del backup, consolidación semántica y los pendientes de
   autonomía/ingesta consentida del informe de auditoría inicial.

No se cambiaron archivos de código en esta continuación, ni configuración del host,
ni tareas programadas. Se añadieron acta y herramientas/evidencias locales ignoradas
por Git. Las pruebas dirigidas de la corrección ya estaban aprobadas en el turno
anterior; aquí se comprobó su despliegue y comportamiento observado. Sin commit ni push.
