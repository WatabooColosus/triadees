# Verificación de arranque programado

Estado anterior, observado 2026-09-21 23:12 UTC: TriadeOmegaSystem habilitada
con BootTrigger, pero Ready, último resultado 0. Ejecutaba start_triade_windows.ps1,
que lanzaba el supervisor desacoplado y terminaba. API 520, supervisor 30552,
sin instancia de tarea ejecutándose. Settings: ExecutionTimeLimit PT72H,
StopIfGoingOnBatteries true, StartWhenAvailable false. El aviso era correcto.

Con autorización explícita se guardó el XML previo en
artifacts/audit-20260921/TriadeOmegaSystem-before-direct.xml y se cambió la acción
a triade_service_worker.ps1 directamente, con directorio del repositorio.
Se habilitaron StartWhenAvailable y el log Operational de TaskScheduler,
ExecutionTimeLimit PT0S, condiciones de batería desactivadas, IgnoreNew y
RestartOnFailure 10 / PT1M. Se conservó el principal SYSTEM y el BootTrigger.
Se detuvieron únicamente la API/supervisor anteriores y se inició la tarea.
El primer intento falló al construir XML, antes de cambiar tarea o procesos;
el segundo terminó correctamente a las 23:16:16 UTC.

Comprobación del código: task State=4 (Running), EnginePID=9524; evento 129
del mismo task registró PID 9524 a las 23:16:16.457 UTC. API PID 27060, padre
9524, comando del padre correspondiente a la acción configurada. Un listener
en 8010. Resultado de build_service_supervision: service_managed=true,
autostart_enabled=true, always_on=true, always_on_blockers=[]. LastTaskResult
267009 corresponde a tarea en ejecución; no se presenta como una finalización.

La nueva comprobación usa EnginePID únicamente si es el supervisor directo;
alternativamente correlaciona el evento 129 con PID y hora de creación para
rechazar eventos de PIDs reutilizados. No basta con que la tarea exista.
Referencia: https://learn.microsoft.com/en-us/windows/win32/taskschd/runningtask-enginepid

14 pruebas pasaron (test_service_supervision y test_windows_supervisor_singleton),
Ruff y git diff --check pasaron. Rama main, HEAD
9c1fd1187760e42335f58dbfa0bbe153fd52fc01, origin actualizado, divergencia 0/0.
Sin commit ni push; se conservaron cambios anteriores.

Observaciones 23:16:44 y 23:17:56 UTC: /health=200, Ollama disponible,
heartbeat PID 27060 avanzó hasta 23:17:54, metabolismo 2425→2430 completado,
worker nuevo iniciado a las 23:16:30.942 UTC. Endpoints de diagnóstico
autenticados siguen dando 403 al observador sin sesión. No se reinició Windows:
se verificaron configuración de boot y lanzamiento real mediante Scheduler,
no un ciclo físico de apagado/encendido.

Incidencia adicional: mission_planner.backup_key_missing a las 23:16:31 UTC.
La lectura diagnóstica de presencia de variables (sin imprimir claves) confirmó
TRIADE_BACKUP_KEY, TRIADE_BACKUP_KEY_FILE y TRIADE_AUTH_VAULT_KEY ausentes en el
supervisor SYSTEM y su API. El fichero de clave existe y su ACL incluye SYSTEM;
la causa de que no se cargue no está demostrada. No se cambió ACL ni clave ni
se afirma salud completa. Esta incidencia queda pendiente de reparación.

Evidencias en artifacts/audit-20260921: task-supervision-probe.json,
scheduled-start-result.json, scheduled-supervision-live.json,
scheduled-task-runtime.json, scheduled-runtime-1.json, scheduled-runtime-2.json,
env-presence.json. Diffs: scheduled-supervision.patch y scheduled-probe-new.patch.
Estado final Git: scheduled-git-status.txt.
