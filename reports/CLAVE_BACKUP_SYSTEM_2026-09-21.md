# Carga de clave de backup bajo SYSTEM — 2026-09-21

## Causa y reparación

La ruta aparente `C:\Users\sven6\AppData\Local\Triade\backup.key` estaba virtualizada por el paquete MSIX de Codex. SYSTEM no veía ese archivo. `GetFinalPathNameByHandleW` resolvió su ubicación física dentro de `OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\Triade`.

Se añadió `config/backup_key_location.json` (solo ubicación, sin material secreto) y el supervisor consulta esa ubicación antes de los fallbacks existentes. No se regeneró ni copió la clave ni se modificaron sus ACL. El diagnóstico temporal bajo SYSTEM confirmó `selected=true`, `loaded=true`, `vaultLoaded=true` a las 23:24:31 UTC. La tarea temporal fue retirada.

## Recarga autorizada y estado observado

La primera parada de TriadeOmegaSystem dejó la API anterior PID 27060 viva; no se inició un duplicado. Se comprobó su identidad por PID, fecha de creación y comando antes de detenerla y completar la recarga autorizada.

A las 23:30:21 UTC se inició desde Task Scheduler el supervisor PID 6912, padre de la API PID 15668. El evento 129 y EnginePID=6912 correlacionan la tarea con el proceso. La inspección elevada de las 23:31:07 UTC confirmó las tres variables de clave presentes en ambos procesos, sin registrar sus valores. `service_managed=true`, `autostart_enabled=true`, `always_on=true`, bloqueos vacíos y un único listener 8010. Esto comprueba el arranque desde la tarea; no constituye una prueba de reinicio de Windows.

A las 23:31:33 UTC `/health` respondió 200/ok y Ollama estaba disponible. Las cinco rutas protegidas de diagnóstico respondieron 403 sin sesión; no se afirma haber validado su contenido autenticado. Entre 23:31:33 y 23:33:03 UTC, el heartbeat del PID 15668 avanzó de 23:31:22 a 23:32:58 y el metabolismo de ciclo 2474 a 2479. El contador de heartbeat permaneció en 1; la evidencia de avance es su timestamp.

Los workers esperan inicialmente el lease vigente de `task-22bd798e75c24f76a5f13b06cad5f479` (`system_debt_scan`), con vencimiento 23:38:15 UTC. No se alteraron manualmente filas, locks ni reservas. La RAM disponible llegó a 0,34 GB; se observó `resource_cooldown`.

## Validación de código

`python -m pytest tests/test_windows_supervisor_singleton.py -q --basetemp=<repo>/artifacts/t62`: 3 pruebas aprobadas (bloqueo exclusivo, ubicación física configurada, fallback).

En la ampliación previa a backup hubo cinco fallos relacionados con modos POSIX bajo Windows: `test_clave_con_permisos_abiertos_es_deuda`, `test_el_arranque_cierra_una_clave_abierta`, `test_una_clave_ya_cerrada_no_se_toca`, `test_backup_and_manifest_are_private`, `test_backup_key_file_requires_restricted_permissions`. Esos tests y `triade/memory/encrypted_backup.py` no se modificaron. No se presenta esa suite como aprobada.

`git diff --check` sin errores. Rama main, HEAD `9c1fd1187760e42335f58dbfa0bbe153fd52fc01`; tras `git fetch origin`, divergencia HEAD...origin/main 0/0. Se conservaron cambios anteriores y no se hizo commit ni push.

## Evidencia

En `artifacts/audit-20260921/`: `system-backup-diagnostic-fixed.json`, `backup-key-reload-result.json`, `backup-key-reload-completion.json`, `backup-key-live.json`, `backup-key-task.json`, `backup-key-cleanup.json`, `backup-key-runtime-2.json`, `backup-key-runtime-3.json`, `backup-key-changes.patch`, `backup-key-git-status.txt`. El patch incluye el diff acumulado del supervisor contra HEAD y los archivos nuevos completos; no atribuye cambios anteriores exclusivamente a esta recarga.

## Resultado al cierre (23:41:22 UTC / 18:41:22 Colombia)

El watchdog recuperó los workers sin intervención manual al vencer la reserva. Nuevo run `worker-2026-09-21T233901.806602Z0000-734c56e1`, iniciado 23:39:01 UTC, lock vinculado a PID 15668. A las 23:39:15 UTC el planificador creó automáticamente `encrypted_backup` task-574391a1beae4e4e9da031a902e8ec52, prioridad 4. A las 23:40:02 la tarea `system_debt_scan` renovó su lease: evidencia de actividad posterior a la recuperación. El metabolismo alcanzó el ciclo 2499 a las 23:39:55 UTC.

A las 23:41:22 UTC el nuevo backup seguía `pending`, mientras el worker atendía `system_debt_scan`. La última copia completada seguía siendo de las 22:53:06 UTC, anterior a esta recarga. Por tanto, queda comprobada la carga real de la clave y la nueva planificación automática, pero NO una copia nueva completada ni un nuevo simulacro de restauración. No se adelantó artificialmente la tarea ni se alteró la cola para producir evidencia.

La consulta de `worker_events` desde 23:30:21 UTC no devolvió eventos con status=error. Los avisos previos de watchdog corresponden a la espera del lease; no se confunden con pruebas de ejecución. Persisten las limitaciones por RAM y el acceso 403 a endpoints protegidos sin sesión.

Evidencias finales adicionales: `backup-key-tasks.json`, `backup-key-runtime-5.json`, `backup-key-runtime-final.json`. Comandos: `python artifacts/audit-20260921/observe_runtime.py backup-key-runtime-final`; `python artifacts/audit-20260921/read-backup-tasks.py`; inspección elevada con `verify-backup-live-admin.ps1`. Los observadores SQLite usan `mode=ro`.
